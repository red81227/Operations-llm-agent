"""This module contains class to for user service."""
from typing import Literal

# from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, MessagesState

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import RemoveMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
import datetime
from config.logger_setting import log
from langchain_openai import ChatOpenAI
from src.models.query import Output
from src.service.tools.basic_tool_node import BasicToolNode, process_tool_message
from src.service.tools.get_weather_information import get_weather_information, schedule_get_weather_information
from config.project_setting import llm_config
from langchain_community.tools.tavily_search import TavilySearchResults


class AgentService:
    """Provide functions related to agent service."""
    def __init__(self):
        self.llm = ChatOpenAI(
                api_key=llm_config.api_key,
                base_url=llm_config.llm_url,
                model=llm_config.llm_model,
                temperature=llm_config.temperature,
                max_retries=llm_config.max_retries,
                top_p=llm_config.top_p,
                frequency_penalty=llm_config.frequency_penalty,
            )
        tools = [get_weather_information, schedule_get_weather_information, TavilySearchResults(max_results=3)]
        
        self.llm_with_tools = self.llm.bind_tools(tools)
        self.tool_node = BasicToolNode(tools)
        self.app = self.init_workflow_app()
        

    def chat(self, query: str, user_id: int) -> Output:
        """ define a chat agent
        """
        log.info(f"chat server start")
        
        thread = {"configurable": {"thread_id": user_id}}
        state = self.app.get_state(thread)
        if state.tasks and any(task.interrupts for task in state.tasks):
            for event in self.app.stream(Command(resume=query), thread, stream_mode="updates"):
                pass
        else:
            input = {"messages": [HumanMessage(content=query,
                                               additional_kwargs={"user_id": user_id})
                                  ]
                                }
            for event in self.app.stream(input, thread, stream_mode="updates"):
                pass

        if '__interrupt__' in event:
            interrupt_info = event['__interrupt__'][0]
            question = interrupt_info.value.get('question', 'No question provided.')
            return Output(
                output = question
            )
        top_key = next(iter(event.keys()), None)
        node_data = event[top_key]
        return Output(
            output = node_data["messages"].content
        )

    
    def init_workflow_app(self):
        """ define a workflow app"""

        # Build graph
        workflow = StateGraph(MessagesState)
        workflow.add_node("ValidateScopeNode", self.ValidateScopeNode)
        workflow.add_node("CheckInformationNode", self.CheckInformationNode)
        workflow.add_node("call_model", self.call_model)
        workflow.add_node("tools", self.tool_node)

        workflow.add_edge(START, "ValidateScopeNode")
        workflow.add_conditional_edges("ValidateScopeNode", self.validated_continue)
        workflow.add_conditional_edges("CheckInformationNode", self.check_information_continue)
        workflow.add_conditional_edges("call_model", self.route_tools)
        workflow.add_edge("tools", "call_model")
        checkpointer = MemorySaver()
        # Add
        return workflow.compile(checkpointer=checkpointer)



    def ValidateScopeNode(self, state: MessagesState):
        log.info("ValidateScopeNode")
        log.info(state)
    
        messages = state.get("messages")

        # 定義 prompt
        prompt = f"""
        Below is a question: "{messages}"
        Please determine whether this question is related to the weather API service. If it is, respond with "Yes"; otherwise, respond with "No".
        """

        # 調用 LLM
        llm_response = self.llm.invoke(prompt)
        log.info("ValidateScopeNode: " + llm_response.content)
        decision = llm_response.content.strip().lower()

        if  "yes" in decision:
            return {'is_valid': True, 'messages': messages}
        return {'is_valid': False, 'messages': AIMessage(content ="這個服務僅支持天氣API服務相關問題，請重新提問。")}
    
    @staticmethod
    def validated_continue(state: MessagesState) -> Literal["CheckInformationNode", END]: # type: ignore
        if state['is_valid']:
            return "CheckInformationNode"
        return END

    def CheckInformationNode(self, state: MessagesState):
        
        messages = state.get('messages')
        user_id = state.get("user_id")
        
        loaction_list = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣','連江縣,' '基隆市', '新竹市', '嘉義市']

        # 定義 prompt
        prompt = f"""
            請分析以下問題：" {messages} "
            判斷其中是否包含地理位置信息（例如城市名稱、地點等）。如果包含，請提取地理位置信息；如果不包含，請回答 "缺少位置信息"。
            請注意，用戶輸入的地理位置信息可能存在拼寫錯誤。請將提取的地理位置信息與以下位置列表進行比對：{loaction_list}。
            如果提取的地理位置信息未在列表中出現，請回答 "不在允許範圍"；如果在列表中，請僅返回該地理位置的繁體中文名稱，不要添加任何額外描述。
            例如：
            用戶輸入："我想知道桃園市的氣溫預報。"
            回答："桃園市"
            用戶輸入："請問san francisco的天氣如何？"
            回答："不在允許範圍"
            """
        # 調用 LLM
        llm_response = self.llm.invoke(prompt)
        log.info("CheckInformationNode: " + llm_response.content)
        decision = llm_response.content.strip()

        if "缺少位置信息" in decision:
            return {'is_complete': False, 'messages': AIMessage(content ="請提供您的地理位置，才能進行天氣查詢。")}
        elif "不在允許範圍" in decision:
            return {'is_complete': False, 'messages': AIMessage(content =f"地理位置必須在下面列表中: {loaction_list}，才能進行天氣查詢。")}
        return {'is_complete': True, 'locationName': decision, 'messages': messages}

    @staticmethod
    def check_information_continue(state: MessagesState) -> Literal["call_model", END]: # type: ignore
        log.info("check_information_continue :")
        log.info(state)
        if state['is_complete']:
            return "call_model"
        return END

    def call_model(self, state: MessagesState):

        messages = state.get("messages")
        user_id = messages[0].additional_kwargs.get("user_id")
        
        if len(state["messages"]) > 6:
            state = self.summarize_conversation(state)

        log.info("call_model")
        log.info(state)
    
        summary = state.get("summary", "")
        log.info(f"user_id: {user_id}")
        if summary:
            system_message = f"Summary of conversation earlier: {summary}"
            user_info_message = SystemMessage(content=f"user_id: {user_id}")
            messages = [system_message, user_info_message] + state["messages"]
        else:
            user_info_message = SystemMessage(content=f"user_id: {user_id}")
            messages = [user_info_message] + state["messages"]
        # 定義 prompt

        primary_assistant_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a customer support assistant for a weather website. "
                    "Respond to user queries exclusively using the information provided by the available tools. "
                    "Do not generate any information beyond what the tools provide. "
                    "If the initial search yields no results, broaden your search parameters and try again. "
                    "Under no circumstances should you fabricate answers; all responses must be based solely on the tool outputs. "
                    "Before using any tool, ensure that all parameters are correct and properly formatted to prevent errors."
                    "要啟動排程服務一定要使用工具"
                    "\n\nuser_id:\n<User>\n{user_id}\n</User>"
                    "\nCurrent time: {time}."
                    "一定要使用繁體中文輸出",
                ),
                ("user", "{messages}"),
            ]
        ).partial(
            time=datetime.datetime.now,
            user_id=user_id
        )

        part_1_assistant_runnable = primary_assistant_prompt | self.llm_with_tools
        response = part_1_assistant_runnable.invoke(messages)

        # We return a list, because this will get added to the existing list
        return {'messages': response}

    @staticmethod
    def route_tools(state: MessagesState):
        """
        Use in the conditional_edge to route to the ToolNode if the last message
        has tool calls. Otherwise, route to the end.
        """
        if isinstance(state, list):
            ai_message = state[-1]
        elif messages := state.get("messages", []):
            ai_message = messages[-1]
        else:
            raise ValueError(f"No messages found in input state to tool_edge: {state}")
        if hasattr(ai_message, "tool_calls"):
            tool_message = process_tool_message(ai_message.content)
            print(tool_message)
            if len(tool_message) > 0:                
                return "tools"
            else:
                return END
        
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
        response = self.llm.invoke(messages)
        # We now need to delete messages that we no longer want to show up
        # I will delete all but the last two messages, but you can change this
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]
        return {"summary": response.content, "messages": delete_messages}
        