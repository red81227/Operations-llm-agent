"""This module contains class to for user service."""
import re
from typing import Literal

# from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, MessagesState

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import RemoveMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
import datetime
from config.logger_setting import log
from langchain_openai import ChatOpenAI
from src.models.query import Output
from src.service.event.redis.tool_logs import ToolLogs
from src.service.tools.basic_tool_node import BasicToolNode, process_tool_message
from src.service.tools.get_weather_information import get_weather_information, schedule_get_weather_information
from config.project_setting import qwen_llm_config, deepseek_llm_config
from langchain_community.tools.tavily_search import TavilySearchResults
from src.operator.redis import RedisOperator
from src.service.tools.mqtt_watcher import watch_device_status_by_mqtt



class AgentService:
    """Provide functions related to agent service."""
    def __init__(self):
        self.qwen_llm = ChatOpenAI(
                api_key=qwen_llm_config.api_key,
                base_url=qwen_llm_config.llm_url,
                model=qwen_llm_config.llm_model,
                temperature=qwen_llm_config.temperature,
                max_retries=qwen_llm_config.max_retries,
                frequency_penalty=qwen_llm_config.frequency_penalty,
            )
        self.deepseek_llm = ChatOpenAI(
                api_key=deepseek_llm_config.api_key,
                base_url=deepseek_llm_config.llm_url,
                model=deepseek_llm_config.llm_model,
                temperature=deepseek_llm_config.temperature,
                max_retries=deepseek_llm_config.max_retries,
                frequency_penalty=deepseek_llm_config.frequency_penalty,
            )
        
        tools = [get_weather_information, schedule_get_weather_information, watch_device_status_by_mqtt]
        
        self.qwen_llm_with_tools = self.qwen_llm.bind_tools(tools)
        self.deepseek_llm_with_tools = self.deepseek_llm.bind_tools(tools)
        self.tool_node = BasicToolNode(tools)
        self.app = self.init_workflow_app()

        redis_operator = RedisOperator()
        self.tool_logs = ToolLogs(redis_operator)
        

    def chat(self, query: str, user_id: int) -> Output:
        """ define a chat agent
        """
        log.info(f"chat server start")
        
        thread = {"configurable": {"thread_id": user_id}}
        state = self.app.get_state(thread)
        if state.tasks and any(task.interrupts for task in state.tasks):
            for event in self.app.stream(Command(resume=query), thread, stream_mode="updates"):
                if '__interrupt__' in event:
                    interrupt_info = event['__interrupt__'][0]
                    question = interrupt_info.value.get('question', 'No question provided.')
                    return Output(
                        output = question
                    )
        else:
            input = {"messages": [HumanMessage(content=query,
                                            additional_kwargs={"user_id": user_id})
                                ]
                                }
            for event in self.app.stream(input, thread, stream_mode="updates"):
                if '__interrupt__' in event:
                    interrupt_info = event['__interrupt__'][0]
                    question = interrupt_info.value.get('question', 'No question provided.')
                    return Output(
                        output = question
                    )

        top_key = next(iter(event.keys()), None)
        log.info(f"event: {event}")
        node_data = event[top_key]
        return Output(
            output = node_data["messages"].strip()
        )

    
    def init_workflow_app(self):
        """ define a workflow app"""

        # Build graph
        workflow = StateGraph(MessagesState)
        workflow.add_node("validate_scope", self.validate_scope)
        workflow.add_node("check_information", self.check_information)
        workflow.add_node("decision_maker", self.decision_maker)
        workflow.add_node("executor", self.executor)
        workflow.add_node("tools", self.tool_node)

        workflow.add_edge(START, "validate_scope")
        workflow.add_conditional_edges("validate_scope", self.validated_continue)
        workflow.add_conditional_edges("check_information", self.check_information_continue)
        workflow.add_conditional_edges("decision_maker", self.decide_executor)
        workflow.add_conditional_edges("executor", self.route_tools_executor)
        workflow.add_edge("tools", "decision_maker")
        checkpointer = MemorySaver()

        app = workflow.compile(checkpointer=checkpointer)

        workflow_image_path = "/home/app/workdir/data/workflow_graphs/workflow_graph.png"

        # 取得 workflow 圖片並存檔
        with open(workflow_image_path, "wb") as f:
            f.write(app.get_graph().draw_mermaid_png())
        return app



    def validate_scope(self, state: MessagesState):
        log.info("validate_scope")
        log.info(state)
    
        messages = state.get("messages")

        # 定義 prompt
        prompt = f"""
            You are an intelligent assistant responsible for classifying user queries. Your task is to determine whether the user's question relates to either:
            1. **Weather API Service**: Includes queries about weather conditions, forecasts, temperature, precipitation, or other meteorological data.
            2. **Device Status Monitoring Service**: Includes queries related to IoT devices, real-time device status updates, connectivity monitoring, or equipment health.

            ### **Context Consideration**
            - The determination **must be based on both the current user input ("{messages}") and the conversation history ("{state}").**
            - If there is ambiguity in the current query, refer to previous interactions in the conversation to infer the user's intent.
            - If the user's question is a follow-up to a previous related question, assume continuity in the topic.

            ### **Response Instructions**
            - If the question falls under **either** the Weather API Service **or** Device Status Monitoring Service, respond with **"Yes"**.
            - Otherwise, respond with **"No"**.

            ### **Examples**
            **Case 1: Weather-related query**
            - User: "What is the weather forecast for Taipei tomorrow?"
            - Response: "Yes"

            **Case 2: Device monitoring query**
            - User: "Can you check if my sensor is online?"
            - Response: "Yes"

            **Case 3: Follow-up on prior weather query**
            - Previous User Input: "What’s the temperature in Kaohsiung?"
            - Current User Input: "And what about Tainan?"
            - Response: "Yes" (continuation of weather-related inquiry)

            **Case 4: Unrelated question**
            - User: "Tell me about the latest news on electric vehicles."
            - Response: "No"

            Now, based on the given conversation history and current input, determine the correct response.
            """

        # 調用 LLM
        llm_response = self.deepseek_llm.invoke(prompt)
        log.info("validate_scope: " + llm_response.content)
        direct_answer = self.extract_direct_answer(llm_response.content)

        if  "yes" in direct_answer.strip().lower():
            return {'is_valid': True, 'messages': messages}
        return {'is_valid': False, 'messages': "這個服務僅支持天氣API服務相關問題，請重新提問。"}
    
    @staticmethod
    def validated_continue(state: MessagesState) -> Literal["check_information", END]: # type: ignore
        if state['is_valid']:
            return "check_information"
        return END

    def check_information(self, state: MessagesState):
        
        messages = state.get('messages')

        loaction_list = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', '新竹縣', '苗栗縣', '彰化縣', 
                        '南投縣', '雲林縣', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣',
                        '連江縣', '基隆市', '新竹市', '嘉義市']

        # 定義 prompt，新增規則7：當系統推測用戶可能詢問 loaction_list 中的某個地點時，以確認語氣回覆並提出候選位置信息。
        prompt = f"""
        請分析以下問題：" {messages} "
        判斷其中是否包含地理位置信息（例如城市名稱、地點、觀光景點等）。
        請根據下列規則處理：
        1. **若用戶輸入的地點對應到 `loaction_list`: {loaction_list} 中的名稱，請直接回傳該名稱**。
        2. **若用戶提供的是景點名稱（如「日月潭」、「阿里山」），請將其對應到 `loaction_list` 中最合理的縣市名稱**。
        3. **若用戶輸入缺少「縣」或「市」，請根據語意推斷合理的縣市名稱**（例如「新竹」可對應「新竹市」或「新竹縣」）。
        4. **如果輸入內容對應到多個縣市，請回傳所有匹配到的縣市名稱，以逗號分隔（如「桃園、新北」→「桃園市, 新北市」）**。
        5. **若地點不在 `loaction_list` 中，請回覆 "不在允許範圍"**。
        6. **若找不到任何地點資訊，請回覆 "缺少位置信息"**。
        7. **若用戶輸入的資訊存在模糊性，請以確認語氣回覆，並提出候選位置信息，例如："請確認: 您是否指的是 [候選地點]？"。**
        8. **若用戶已明確指出單一地理位置資訊（例如直接提及 "新竹市"），則應直接回傳該名稱，不需進行確認提示。**

        請根據上述規則，**僅返回最終判斷出的地理位置名稱，或在資訊模糊時以確認提問回覆，不得添加任何額外描述**。

        """

        # 調用 LLM
        llm_response = self.deepseek_llm.invoke(prompt)
        log.info("check_information: " + llm_response.content)

        direct_answer = self.extract_direct_answer(llm_response.content)

        if "缺少位置信息" in direct_answer:
            return {'is_complete': False, 'messages': "請提供您的地理位置，才能進行天氣查詢。"}
        elif "不在允許範圍" in direct_answer:
            return {'is_complete': False, 'messages': "地理位置必須在下面列表中: {loaction_list}，才能進行天氣查詢。"}
        elif "請確認:" in direct_answer:
            return {'is_complete': False, 'messages': direct_answer}
        return {'is_complete': True, 'locationName': direct_answer, 'messages': messages}

    @staticmethod
    def check_information_continue(state: MessagesState) -> Literal["decision_maker", END]: # type: ignore
        log.info("check_information_continue :")
        log.info(state)
        if state['is_complete']:
            return "decision_maker"
        return END

    def decision_maker(self, state: MessagesState):
        # 取得會話紀錄及使用者ID
        messages = state.get("messages")
        user_id = messages[0].additional_kwargs.get("user_id")
        
        # 當會話訊息過多時，先進行摘要整理
        if len(state["messages"]) > 6:
            state = self.summarize_conversation(state)

        summary = state.get("summary", "")
        log.info(f"user_id: {user_id}")
        if summary:
            system_message = f"Summary of conversation earlier: {summary}"
            user_info_message = SystemMessage(content=f"user_id: {user_id}")
            messages = [system_message, user_info_message] + state["messages"]
        else:
            user_info_message = SystemMessage(content=f"user_id: {user_id}")
            messages = [user_info_message] + state["messages"]
        
        # 取得使用者過往的工具使用日誌
        logs = self.tool_logs.get_logs(user_id=user_id)
        loaction_list = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣','連江縣,' '基隆市', '新竹市', '嘉義市']

        tool_information = f"""
        工具列表：
        1. get_weather_information
        - 功能：取得指定地點特定氣象要素的天氣預報資訊。
        - 說明：調用中央氣象局開放數據平台 API，獲取各縣市或國際都市的今明36小時天氣預報。
        - 參數：
            • locationName (list[str]): 查詢地點，請使用繁體中文（例如：["桃園縣"]）。locationName 可以是以下縣市名稱之一： {loaction_list}。請依據使用這需求提供正確的縣市名稱。
            • elementName (list[str]): 氣象要素英文代碼，選項包括：
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
            • locationName (list[str]): 查詢地點（繁體中文，例如：["桃園縣"]）。locationName 可以是以下縣市名稱之一： {loaction_list}。請依據使用這需求提供正確的縣市名稱。
            • elementName (list[str]): 氣象要素英文代碼，選項包括：
                - "Wx"：天氣現象
                - "MaxT"：最高溫度
                - "MinT"：最低溫度
                - "CI"：舒適度
                - "PoP"：降雨機率
            • start_time (str): 排程開始時間，格式 "YYYY-MM-DD HH:MM:SS"。
            • duration (int): 排程持續時間（分鐘），預設60分鐘，如果使用者有提供排程持續時間，請依照使用者需求帶入。
            • frequency (int): 排程執行間隔（秒），預設60秒，如果使用者有提供排程間隔時間，請依照使用者需求帶入。
            • user_id (str): 代表當前對話使用者的 ID。請在 Prompt 中尋找以 "user_id:" 為標記的字串（例如："user_id: <some_value>"），並於呼叫時將該值帶入。
        - 回傳：
            • str：JSON 字串，顯示排程啟動成功或使用者拒絕啟用排程的訊息。

        4. watch_device_status_by_mqtt
        - 功能：透過 MQTT 監控設備狀態。
        - 參數：
            • duration (int): 監控持續秒數。
            • user_id (str): 使用者 ID，供訊息推送通知使用。
        - 回傳：
            • Union[str, Dict[str, Any]]：成功訊息或錯誤描述。
        """

        # 3. 規劃與推理階段的提示 (Planning Prompt)
        planning_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    (
                        "您是一位高效能的規劃與推理助理，專門為天氣網站服務設計。您的任務是根據下列工具資訊與使用者過往的工具日誌，"
                        "分析對話內容並決定最佳的行動方案。請注意：\n"
                        "1. 嚴格依據提供的工具資訊、日誌內容與進行分析，禁止捏造未明示之資料。\n"
                        "2. 若使用者問題可依據現有的工具資訊與日誌回答，請以『直接回答:』開頭，直接提供完整的答案給使用者。\n"
                        "3.如果需要使用工具取得資料且最近1分鐘內該工具與參數沒有被執行過，請以『使用工具:』開頭，並詳細列出應調用的工具與步驟。\n"
                        "4. 若缺乏資料仍必須調用工具，請以『使用工具:』開頭，並詳細列出應調用的工具與步驟。\n"
                        "5. 所有的回答都應該以『直接回答:』或『使用工具:』開頭，不應該有其他開頭。"
                        "6. 如日誌中無相關資訊，請選擇最合適的工具進行調用；若使用者要求續行任務或啟動排程，請優先搜尋"
                        "名稱以 'schedule' 為前綴的工具，避免重複排程。\n"
                        "7. 即使先前工具資訊與日誌記錄存在錯誤，仍應依使用者需求嘗試調用工具，連續調用三次都錯誤，才能放棄。\n"
                        "8. 回答內容如果有結構資料，應該依據使用者的問題，整理成簡潔易懂的敘述提供給使用者，整理資料不需要使用工具\n"
                        "9. 請僅返回最終決策，不要返回多個答案，即使內部思考過程中提到不同方案，也只返回最終選擇。\n"
                        "10. 請確保最終回答**僅**包含單一前綴：\n"
                        "    - 若分析結果顯示應使用工具，最終回答必須僅以『使用工具:』作為前綴，不得同時包含『直接回答:』。\n"
                        "    - 若分析結果顯示可直接回答，則僅以『直接回答:』作為前綴。\n"
                        "12. **若使用者的問題中包含「排程」、「定期」或類似關鍵字，表示需要啟動排程服務，最終決策必須選用 名稱以 'schedule' 為前綴的工具。**\n"
                        "【當前資訊】\n"
                        "工具資訊：{tool_information}\n"
                        "工具使用日誌：{logs}\n"
                        "使用者 ID：<User>{user_id}</User>\n"
                        "當前時間：{time}\n"
                        "如果思考後決定使用工具，請以『使用工具:』開頭，並提供詳細的規劃結果。\n"
                        "請根據以上資訊，思考使用者的需求，提供您的詳細規劃結果。回答內容必須僅以『直接回答:』或『使用工具:』開頭，且所有中文字均使用繁體中文。"
                    )
                ),
                HumanMessagePromptTemplate.from_template("{messages}"),
            ]
        ).partial(
            tool_information=tool_information,
            logs=logs,
            time=datetime.datetime.now,
            user_id=user_id,
        )


        # 呼叫規劃 LLM，傳入當前會話紀錄
        planning_runnable = planning_prompt | self.deepseek_llm
        planning_output = planning_runnable.invoke(messages)
        log.info("Planning result:")
        log.info(planning_output.content)

        planning_result = self.extract_direct_answer(planning_output.content)

        # 將規劃結果存入 state，供後續 conditional edge 判斷
        # 移除 <think> 區塊以獲得純文字結果
        return {'messages': planning_output.content, 'planning_result': planning_result}

    def decide_executor(self, state: MessagesState) -> Literal["executor", END]: # type: ignore
        planning_result = state.get("planning_result", "")
        log.info(f"decide_executor planning_result: {planning_result}")
        
        if "直接回答:" in planning_result:
            return END
        elif "使用工具:" in planning_result:
            return "executor"
        return "executor"

    def executor(self, state: MessagesState):
        

        
        messages = state.get("messages")
        user_id = messages[0].additional_kwargs.get("user_id")
        planning_result =  messages[-1]
        log.info(f"executor planning_result: {planning_result}")

        # 取得使用者過往的工具使用日誌
        logs = self.tool_logs.get_logs(user_id=user_id)
        
        # 執行階段：呼叫 execution prompt 進行工具調用
        execution_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "You are a customer support assistant for a weather website. "
                    "Your task is to execute the tool calls as specified in the following messages and planning instructions: {planning_result} "
                    "Use only the available tools to fulfill the plan exactly as instructed. "
                    "If the user wants to continue a task or initiate a schedule, search for tools with names starting with 'schedule' "
                    "Do not deviate from the plan or fabricate any information.\n"
                    "User ID: <User>{user_id}</User>\n"
                    "Current time: {time}.\n\n"
                    "\nHere are the recent tool usage logs: {logs}"
                    "\nRespond based on the tool usage logs. Avoid making assumptions or creating unsupported answers. "
                    "\nIf the user wants to continue a task or initiate a schedule, search for tools with names starting with 'schedule' "
                    "and determine if any are suitable for the request.\n"
                    "\nSchedules must always be initiated through the appropriate tools; do not start them manually.\n"
                    "\nVerify in the recent tool usage logs if a schedule was successfully initiated. "
                    "Only consider the service initiated if a schedule is found in the logs.\n"
                    "\nIf the user tries to initiate duplicate schedules for the same context, remind them to avoid redundancy.\n"
                    "Please respond with the execution result.\n"
                    "一定要使用繁體中文輸出"
                ),
                HumanMessagePromptTemplate.from_template(""),
            ]
        ).partial(
            planning_result=planning_result,
            logs=logs,
            user_id=user_id,
            time=datetime.datetime.now,
                            )
        
        # 執行工具調用，使用綁定工具的 qwen_llm
        execution_runnable = execution_prompt | self.qwen_llm_with_tools
        execution_result = execution_runnable.invoke({})
        log.info("Execution result:")
        log.info(execution_result)
        
        return {'messages': execution_result, "execution_result" : execution_result}


    def route_tools_executor(self, state: MessagesState) -> Literal["tools", "decision_maker"]:
        # 檢查最後一則訊息是否包含 <tool_call> 標記
        if state.get("execution_result") and '<tool_call>' in state["execution_result"].content:
            return "tools"
        return "decision_maker"
        
    def summarize_conversation(self, state: MessagesState):
        # First, we summarize the conversation
        summary = state.get("summary", "")
        if summary:
            # If a summary already exists, we use a different system prompt
            # to summarize it than if one didn't
            summary_message = (
                f"This is summary of the conversation to date: {summary}\n\n"
                "Extend the summary by taking into account the new messages above:"
            )
        else:
            summary_message = "Create a summary of the conversation above:"

        messages = state.get("messages", "") + [HumanMessage(content=summary_message)]
        response = self.deepseek_llm.invoke(messages)
        # We now need to delete messages that we no longer want to show up
        # I will delete all but the last two messages, but you can change this
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]
        return {"summary": response.content, "messages": delete_messages}

    @staticmethod
    def extract_direct_answer(content: str) -> str:
        """
        從模型的輸出中移除所有 <think>...</think> 區塊，
        然後檢查剩餘文字中是否有 '直接回答:' 標記，
        如果有則擷取並回傳直接回答內容；否則回傳空字串。
        """
        # 移除所有 <think>...</think> 區塊（DOTALL 表示換行也能匹配）
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

        