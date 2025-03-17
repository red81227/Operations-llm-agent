"""This module contains class to for user service."""

from typing import Literal, Optional, Dict, Any, List
import datetime
import os
import functools
from config.logger_setting import log
from langchain_openai import ChatOpenAI
from src.models.query import Output
from src.service.event.redis.tool_logs import ToolLogs
from src.service.event.redis.user_state import UserState
from src.service.tools.basic_tool_node import BasicToolNode
from src.service.tools.get_weather_information import (
        get_weather_information, 
        schedule_get_weather_information,
        list_weather_schedules,
        stop_weather_schedule
    )
from config.project_setting import qwen_14b_awq_llm_config, deepseek_32b_awq_llm_config, deepseek_14b_awq_llm_config
from src.operator.redis import RedisOperator
from src.service.tools.mqtt_watcher import watch_device_status_by_mqtt
from src.util.function_utils import extract_direct_answer, extract_thinking
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, MessagesState
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import RemoveMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command
from langchain.prompts.chat import (
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

# Taiwan county/city list
LOCATION_LIST = [
    '臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', '新竹縣', '苗栗縣', '彰化縣', 
    '南投縣', '雲林縣', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣',
    '連江縣', '基隆市', '新竹市', '嘉義市'
]

# Define the path for the workflow diagram
WORKFLOW_DIAGRAM_PATH = "/home/app/workdir/data/workflow_graphs/workflow_graph.png"

class AgentService:
    """Provide functions related to agent service."""
    
    # System prompts for different stages
    VALIDATE_SCOPE_PROMPT = """
            您是一個負責分類用戶查詢的智能助手。您的任務是確定用戶的問題是否與以下任一服務相關：

    天氣 API 服務：包括有關天氣狀況、預報、溫度、降水或其他氣象數據的查詢。

    設備狀態監控服務：包括與物聯網設備、實時設備狀態更新、連接監控或設備健康相關的查詢。

    ### **上下文考量**
    判斷必須基於當前用戶輸入（"{latest_message}"）和對話歷史（"{message_history}")。
    如果當前查詢存在模糊性，請參考之前的互動以推斷用戶的意圖。
    如果用戶的問題是之前相關問題的後續，請假設話題的連續性。
    ### **回應指示**
    如果問題屬於天氣 API 服務或設備狀態監控服務，請簡短描述用戶的*意圖*，尤其留意地理名稱、設備名稱、時間資訊。
    如果問題不符合任何一項服務，請回應 "No"。

    現在，根據給定的對話歷史和當前輸入，確定正確的回應。
    """
    
    CHECK_LOCATION_PROMPT = """
    請分析以下問題：" {user_intent} "
    判斷其中是否包含地理位置信息（例如城市名稱、地點、觀光景點等）。
    請根據下列規則處理：
    1. **若用戶輸入的地點對應到 `LOCATION_LIST`: {locations} 中的名稱，請直接回傳該名稱**。
    2. **如果輸入內容對應到多個縣市，請回傳所有匹配到的縣市名稱，以逗號分隔（如「桃園、新北」→「桃園市, 新北市」）**。
    3. **若地點不在 `LOCATION_LIST` 中，請回覆 "不在允許範圍"**。
    4. **若找不到任何地點資訊，請回覆 "缺少位置信息"**。
    5. **若用戶輸入的資訊存在模糊性，例如不確定查詢縣或是市，或給景點名稱，請以確認語氣回覆，並提出候選位置信息，例如："請確認: 您是否指的是 [候選地點]？"。**
    6. **若用戶已明確指出單一地理位置資訊（例如直接提及 "新竹市"），則應直接回傳該名稱，不需進行確認提示。**

    請根據上述規則，**僅返回最終判斷出的地理位置名稱，或在資訊模糊時以確認提問回覆，不得添加任何額外描述**。
    """
    
    THINKING_SUMMARIZATION_PROMPT = """
    請將模型思考過程轉成**繁體中文**，保留*推導過程*與*使用工具*，
    總結文字內容，並濃縮到50字以內。模型思考過程:{thinking_content}
    """
    
    PLANNING_SYSTEM_PROMPT = """
    您是一位高效能的規劃與推理助手，專門為天氣網站服務設計。您的任務是根據下列工具資訊與使用者過往的工具日誌，
    請仔細思考並分析對話內容並決定最佳的行動方案。請注意：

    1. 嚴格依據提供的工具資訊、日誌內容與進行分析，禁止捏造未明示之資料。
    2. 若使用者問題可依據現有的*工具使用日誌*回答，直接提供完整的答案給使用者。
    3. 如果需要使用工具取得資料，請以『使用工具:』開頭，並詳細列出應調用的工具與使用參數。
    4. 如工具使用日誌中無相關資訊，請選擇最合適的工具進行調用
    5. 即使先前工具資訊與日誌記錄存在錯誤，仍應依使用者需求嘗試調用工具，連續調用三次都錯誤，才能放棄。
    6. 回答內容如果有結構資料，應該依據使用者的問題，整理成簡潔易懂的敘述提供給使用者，整理資料不需要使用工具
    7. 請僅返回最終決策，不要返回多個答案，即使內部思考過程中提到不同方案，也只返回最終選擇。
    8. **若使用者的問題中包含「排程」、「定期」、「持續」或類似關鍵字，可能表示需要啟動排程服務，請優先參考名稱以 'schedule' 為前綴的工具。
    9. 通常最新資料表示1分鐘內的資料。
    10. 對於可以直接回答的問題，請更具使用者的需求，整理好答案並直接回答。
    11. 確認*工具使用日誌*工具使用後的結果，結果可能是工具的回傳值，也可能是使用者希望對工具參數進行修改的需求，也有可能執行失敗，請根據工具回傳結果，適當的執行工具或是回復。
    12. 如果決定使用工具，只回傳*工具名稱*與*工具參數*，不要有其他資訊。
    13. 如果參數與時間相關，例如持續時間或執行頻率，請仔細看清楚工具所要帶入的時間單位是小時、分鐘或是秒。
    14. 如果使用者希望查詢排程任務，請使用「list_weather_schedules」工具查詢目前進行中的排程。
    15. 如果使用者希望停止排程任務，請使用「stop_weather_schedule」工具停止指定的排程任務。

    【當前資訊】
    最新的訊息：{latest_message}
    工具資訊：{tool_information}
    工具使用日誌：{tool_logs}
    使用者 ID：<User>{user_id}</User>
    當前時間：{time}

    如果思考後決定使用工具，請以『使用工具:』開頭，並提供詳細的規劃結果。
    請根據以上資訊，思考使用者的需求，提供您的詳細規劃結果，並使用*繁體中文*回答。
    """
    
    EXECUTION_SYSTEM_PROMPT = """
    You are a customer support assistant responsible for executing tool calls as specified in the planning instructions.
    Your task is to execute the tool calls as specified in the following messages and planning instructions: {planning_result}
    Use only the available tools to fulfill the plan exactly as instructed.
    If the user wants to continue a task or initiate a schedule, search for tools with names starting with 'schedule'
    Do not deviate from the plan or fabricate any information.
    
    User ID: <User>{user_id}</User>
    Current time: {time}.

    Here are the recent tool usage logs: {logs}
    
    Respond based on the tool usage logs. Avoid making assumptions or creating unsupported answers.
    If the user wants to continue a task or initiate a schedule, search for tools with names starting with 'schedule'
    and determine if any are suitable for the request.

    Schedules must always be initiated through the appropriate tools; do not start them manually.
    If the user tries to initiate duplicate schedules for the same context, remind them to avoid redundancy.
    
    Please respond with the execution result.
    一定要使用繁體中文輸出
    """

    def __init__(self):
        # Initialize LLMs
        self._init_llm_models()
        
        # Initialize tools
        self._init_tools()
        
        # Initialize workflow
        self.app = self.init_workflow_app()

        # Initialize Redis for tool logging
        redis_operator = RedisOperator()
        self.tool_logs = ToolLogs(redis_operator)
        self.user_state = UserState(redis_operator)
    
    def _init_llm_models(self):
        """Initialize LLM models."""
        # Using configuration directly to initialize models
        self.qwen_14b_awq_llm = ChatOpenAI(**self._get_llm_config_dict(qwen_14b_awq_llm_config))
        self.deepseek_32b_awq_llm = ChatOpenAI(**self._get_llm_config_dict(deepseek_32b_awq_llm_config))
        self.deepseek_14b_awq_llm = ChatOpenAI(**self._get_llm_config_dict(deepseek_14b_awq_llm_config))
    
    @staticmethod
    def _get_llm_config_dict(config) -> Dict[str, Any]:
        """Convert config object to dictionary for LLM initialization."""
        return {
            'api_key': config.api_key,
            'base_url': config.llm_url,
            'model': config.llm_model,
            'temperature': config.temperature,
            'max_retries': config.max_retries,
            'frequency_penalty': config.frequency_penalty,
        }
    
    def _init_tools(self):
        """Initialize tools and bind them to LLMs."""
        self.tools = [
            get_weather_information, 
            schedule_get_weather_information, 
            watch_device_status_by_mqtt,
            list_weather_schedules,
            stop_weather_schedule
        ]
        
        self.qwen_llm_with_tools = self.qwen_14b_awq_llm.bind_tools(self.tools)
        self.tool_node = BasicToolNode(self.tools)

    @functools.lru_cache(maxsize=32)
    def get_tool_information(self) -> str:
        """Get tool information with caching for better performance."""
        return f"""
        工具列表：
        1. get_weather_information
        - 功能：取得指定地點特定氣象要素的天氣預報資訊。
        - 說明：調用中央氣象局開放數據平台 API，獲取各縣市或國際都市的今明36小時天氣預報。
        - 參數：
            • locationName (list[str]): 必填，查詢地點，請使用繁體中文（例如：["桃園縣"]）。locationName 可以是以下縣市名稱之一： {LOCATION_LIST}。請依據使用這需求提供正確的縣市名稱。
            • elementName (list[str]): 必填，氣象要素英文代碼，選項包括：
                - "Wx"：天氣現象
                - "MaxT"：最高溫度
                - "MinT"：最低溫度
                - "CI"：舒適度
                - "PoP"：降雨機率
        - 回傳：
            • str：JSON 字串格式的天氣預報資訊；若 API 請求失敗，則回傳錯誤訊息。

        2. schedule_get_weather_information
        - 功能：啟動排程服務，持續取得指定地點特定氣象要素的天氣預報資訊。
        - 說明：在指定的 start_time（格式 "YYYY-MM-DD HH:MM:SS"）開始，持續 duration 分鐘，每 frequency 秒呼叫一次天氣 API，請依據使用者需求決定排程持續時間（duration 分鐘）與排程執行間隔（frequency秒）。
        - 參數：
            • locationName (list[str]): 必填，查詢地點（繁體中文，例如：["桃園縣"]）。locationName 可以是以下縣市名稱之一： {LOCATION_LIST}。請依據使用這需求提供正確的縣市名稱。
            • elementName (list[str]): 必填，氣象要素英文代碼，選項包括：
                - "Wx"：天氣現象
                - "MaxT"：最高溫度
                - "MinT"：最低溫度
                - "CI"：舒適度
                - "PoP"：降雨機率
            • start_time (str): 排程開始時間，格式 "YYYY-MM-DD HH:MM:SS"，預設當下時間。
            • duration (int): 排程持續時間（分鐘），預設60分鐘，如果使用者有提供排程持續時間，請依照使用者需求帶入。
            • frequency (int): 排程執行間隔（秒），預設60秒，如果使用者有提供排程間隔時間，請依照使用者需求帶入。
        - 回傳：
            • str：JSON 字串，顯示排程啟動成功或使用者拒絕啟用排程的訊息。

        3. watch_device_status_by_mqtt
        - 功能：此函數啟動一個排程服務，持續監聽指定設備的 MQTT 訊息，適用於需要在特定時間段內監控設備狀態，並根據設備的 MQTT 訊息即時向使用者推送通知的情境。服務的運行時間由 duration 參數決定，單位為秒，預設值為 3600 秒（即 1 小時）。在監聽期間，服務會根據接收到的訊息內容，向指定的 user_id 發送推播通知。
        - 參數：
            • duration (int): 監聽服務的持續時間，單位為秒。預設值為 3600 秒，如果使用者有提供監聽服務的持續時間，請依照使用者需求帶入。
        - 回傳：
            • str：成功訊息或錯誤描述。
            
        4. list_weather_schedules
        - 功能：列出當前使用者的所有進行中的天氣預報排程。
        - 說明：此工具會返回使用者目前啟動的所有天氣預報定時任務，包含每個任務的詳細資訊，如查詢地點、氣象要素、開始和結束時間、更新頻率等。
        - 參數：無需額外參數
        - 回傳：
            • str：JSON 字串格式，包含所有進行中定時任務的資訊；若無排程或查詢失敗，則回傳相應的訊息。
            
        5. stop_weather_schedule
        - 功能：停止指定的天氣預報排程任務。
        - 說明：用戶可以通過提供排程任務的 job_id 來停止特定的天氣預報排程。如果用戶沒有提供 job_id，系統會請求用戶先使用 list_weather_schedules 工具查詢目前進行中的排程，然後選擇要停止的排程。
        - 參數：
            • job_id (str): 選填，要停止的排程任務 ID。若未提供，系統將互動式引導用戶選擇要停止的排程。
        - 回傳：
            • str：JSON 字串格式，顯示停止排程成功或失敗的訊息。
        """

    def summarize_thinking(self, thinking_content: str) -> str:
        """Summarize thinking content in traditional Chinese."""
        llm_response = self.deepseek_14b_awq_llm.invoke(
            self.THINKING_SUMMARIZATION_PROMPT.format(thinking_content=thinking_content)
        )
        return extract_direct_answer(llm_response.content)

    def chat(self, query: str, user_id: int) -> Output:
        """Main chat agent entry point."""
        log.info("Chat server start")
        
        # Convert user_id to string and use a simpler thread config format
        config = {"configurable": {"thread_id": str(user_id), "user_id": str(user_id)}}

        # Check for interruptions
        retrieved_data = self.user_state.get_state(user_id)
        waiting_human_response = retrieved_data.get("waiting_human_response", False)
        if waiting_human_response:
            retrieved_data["waiting_human_response"] = False
            self.user_state.update_state(user_id, retrieved_data)
            input_data = Command(resume=query)
        else:
            input_data = {
                "messages": HumanMessage(content=query)
            }
        

        for chunk in self.app.stream(input_data, config=config, stream_mode="updates"):
            log.info(chunk)
        
        if '__interrupt__' in chunk:
            interrupt_info = chunk['__interrupt__'][0]
            question = interrupt_info.value.get('question', 'No question provided.')
            log.info(f"interrupt_info: {interrupt_info}")

            retrieved_data = self.user_state.get_state(user_id)
            retrieved_data["waiting_human_response"] = True
            self.user_state.update_state(user_id, retrieved_data)

            return Output(output=question)
        
        top_key = next(iter(chunk.keys()), None)
        node_data = chunk[top_key]
        answer = node_data["messages"].content

        retrieved_data = self.user_state.get_state(user_id)
        latest_thinking = retrieved_data.get("latest_thinking", "")

        thinking = self.summarize_thinking(latest_thinking)

        return Output(output=f"推理: {thinking}\n\n結果: {answer}")


    def init_workflow_app(self):
        """Initialize and configure the workflow graph."""
        workflow = StateGraph(MessagesState)
        
        # Add nodes to the workflow
        workflow.add_node("summarize_conversation", self.summarize_conversation)
        workflow.add_node("validate_scope", self.validate_scope)
        workflow.add_node("check_information", self.check_information)
        workflow.add_node("decision_maker", self.decision_maker)
        workflow.add_node("executor", self.executor)
        workflow.add_node("tools", self.tool_node)

        # Define the workflow graph edges
        workflow.add_edge(START, "summarize_conversation")
        workflow.add_edge("summarize_conversation", "validate_scope")
        workflow.add_conditional_edges("validate_scope", self.validated_continue)
        workflow.add_conditional_edges("check_information", self.check_information_continue)
        workflow.add_conditional_edges("decision_maker", self.decide_executor)
        workflow.add_conditional_edges("executor", self.route_tools_executor)
        workflow.add_edge("tools", "decision_maker")
        
        # Setup checkpointing
        checkpointer = MemorySaver()
        app = workflow.compile(checkpointer=checkpointer)

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(WORKFLOW_DIAGRAM_PATH), exist_ok=True)
        
        # Save workflow diagram
        with open(WORKFLOW_DIAGRAM_PATH, "wb") as f:
            f.write(app.get_graph().draw_mermaid_png())
            
        return app

    def summarize_conversation(self, state: MessagesState, config: RunnableConfig):
        """Summarize long conversations to maintain context."""
        messages = state.get("messages")
        if len(messages) <= 10:
            return state
            
        # # For long conversations, summarize history
        # latest_message = messages[-1]
        # summary_message = "Summarize the conversation above in 100 words or less:"
        
        # messages.append(HumanMessage(content=summary_message))
        # response = self.deepseek_32b_awq_llm.invoke(messages)

        # # Add summary as new message
        # new_message = HumanMessage(content=response.content[:100])

        # # Replace old messages with summary
        # [RemoveMessage(id=m.id) for m in messages[:-5]]

        return {"messages": [RemoveMessage(id=m.id) for m in messages[:-5]]}
    
    def validate_scope(self, state: MessagesState, config: RunnableConfig):
        """Validate if user query is within supported services scope."""
        log.info("validate_scope")
        
        messages = state.get("messages")
        latest_message = messages[-1].content
        user_id = config["configurable"]["user_id"]

        # Call LLM for validation using the class prompt template
        prompt = self.VALIDATE_SCOPE_PROMPT.format(
            latest_message=latest_message, 
            message_history=messages[:-1]
        )
        
        llm_response = self.deepseek_32b_awq_llm.invoke(prompt)
        log.info("validate_scope: " + llm_response.content)
        direct_answer = extract_direct_answer(llm_response.content)

        retrieved_data = self.user_state.get_state(user_id)
        retrieved_data["latest_intent"] = direct_answer
        retrieved_data["latest_thinking"] = extract_thinking(llm_response.content)
        self.user_state.update_state(user_id, retrieved_data)

        # Return validation result
        if "no" == direct_answer.strip().lower():
            return {'is_valid': False, 'messages': AIMessage(
                content = "這個服務僅支持天氣API服務相關問題，請重新提問。"
            )}
        return {'is_valid': True}
        
    @staticmethod
    def validated_continue(state: MessagesState) -> Literal["check_information", END]: # type: ignore
        """Determine next step after scope validation."""
        return "check_information" if state.get('is_valid', False) else END

    def check_information(self, state: MessagesState, config: RunnableConfig):
        """Check if the query contains necessary location information."""
        
        user_id = config["configurable"]["user_id"]
        retrieved_data = self.user_state.get_state(user_id)
        latest_intent = retrieved_data.get("latest_intent", "")

        # Call LLM for location checking using the class prompt template
        prompt = self.CHECK_LOCATION_PROMPT.format(
            user_intent=latest_intent,
            locations=LOCATION_LIST
        )

        llm_response = self.deepseek_32b_awq_llm.invoke(prompt)
        log.info("check_information: " + llm_response.content)

        direct_answer = extract_direct_answer(llm_response.content)

        retrieved_data["latest_thinking"] = extract_thinking(llm_response.content)
        self.user_state.update_state(user_id, retrieved_data)

        # Handle different location check results
        response_map = {
            "缺少位置信息": AIMessage(content="請提供您的地理位置，才能進行天氣查詢。"),
            "不在允許範圍": AIMessage(content=f"地理位置必須在下面列表中: {LOCATION_LIST}，才能進行天氣查詢。"),
        }
        
        for key, message in response_map.items():
            if key in direct_answer:
                return {'is_complete': False, 'messages': message}
                
        if "請確認:" in direct_answer:
            return {'is_complete': False, 'messages': AIMessage(content=direct_answer)}
            
        return {'is_complete': True}

    @staticmethod
    def check_information_continue(state: MessagesState) -> Literal["decision_maker", END]: # type: ignore
        """Determine next step after information checking."""
        return "decision_maker" if state.get('is_complete', False) else END

    def decision_maker(self, state: MessagesState, config: RunnableConfig):
        """Make decisions based on user intent and available tools."""
        messages = state.get("messages")
        latest_message = messages[-1].content
        user_id =  config["configurable"]["user_id"]

        retrieved_data = self.user_state.get_state(user_id)
        latest_intent = retrieved_data.get("latest_intent", "")
        log.info(f"decision_maker messages: {latest_intent}")
        # Get user's tool usage history
        tool_logs = self.tool_logs.get_logs(user_id=user_id)
        log.info(f"tool logs: {tool_logs}")
        
        # Create planning prompt template
        planning_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self.PLANNING_SYSTEM_PROMPT),
                HumanMessagePromptTemplate.from_template(latest_intent),
            ]
        ).partial(
            latest_message=latest_message,
            tool_information=self.get_tool_information(),
            tool_logs=tool_logs,
            time=datetime.datetime.now,
            user_id=user_id,
        )

        # Call planning LLM
        planning_runnable = planning_prompt | self.deepseek_32b_awq_llm
        planning_output = planning_runnable.invoke({})
        log.info("Planning result:")
        log.info(planning_output.content)
        latest_planning = extract_direct_answer(planning_output.content)

        # Extract thinking and planning result
        retrieved_data["latest_thinking"] = extract_thinking(planning_output.content)
        retrieved_data["latest_planning"] = latest_planning
        self.user_state.update_state(user_id, retrieved_data)

        # Handle direct answers vs. tool use
        if "使用工具:" not in latest_planning:
            return {'messages': AIMessage(content=latest_planning)}

        return {'planning_result': latest_planning}

    def decide_executor(self, state: MessagesState) -> Literal["executor", END]: # type: ignore
        """Decide whether to use executor or end workflow."""
        planning_result = state.get("planning_result", "")        
        return "executor" if "使用工具:" in planning_result else END

    def executor(self, state: MessagesState, config: RunnableConfig):
        """Execute planned tool calls."""

        user_id = config["configurable"]["user_id"]
        
        retrieved_data = self.user_state.get_state(user_id)
        latest_intent = retrieved_data.get("latest_intent", "")
        latest_planning = retrieved_data.get("latest_planning", "")

        # Get tool usage logs
        logs = self.tool_logs.get_logs(user_id=user_id)
        
        # Create execution prompt
        execution_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self.EXECUTION_SYSTEM_PROMPT),
                HumanMessagePromptTemplate.from_template(latest_intent),
            ]
        ).partial(
            planning_result=latest_planning,
            logs=logs,
            user_id=user_id,
            time=datetime.datetime.now,
        )
        
        # Execute tools with bound LLM
        execution_runnable = execution_prompt | self.qwen_llm_with_tools
        execution_result = execution_runnable.invoke({})
        
        return {'messages': execution_result}

    def route_tools_executor(self, state: MessagesState) -> Literal["tools", "decision_maker"]:  # type: ignore
        """Route to tools or back to decision maker based on message content."""
        messages = state.get("messages")
        last_message = messages[-1].content
        return "tools" if '<tool_call>' in last_message else "decision_maker"


