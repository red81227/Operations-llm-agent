import json
import re
from langchain_core.messages import ToolMessage, ToolCall, HumanMessage
from typing import List
import uuid
from src.operator.redis import RedisOperator
from src.service.event.redis.tool_logs import ToolLogs
from config.logger_setting import log

redis_operator = RedisOperator()
tool_logs = ToolLogs(operator=redis_operator)

def process_tool_message(content: str) -> List[ToolCall]:

    matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content, re.DOTALL)
    tool_calls = []
    for match in matches:
        try:
            tool_call_data = json.loads(match)
            tool_call = ToolCall(
                name=tool_call_data.get("name"),
                args=tool_call_data.get("arguments", {}),
                id=str(uuid.uuid4()),
                type=tool_call_data.get("type", "tool_call")
            )
            tool_calls.append(tool_call)
        except json.JSONDecodeError:
            log.error(f"Unable to parse tool call JSON data. {match}")
    return tool_calls

class BasicToolNode:
    """A node that runs the tools requested in the last AIMessage."""

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    def __call__(self, inputs: dict):
        messages = inputs.get("messages", [])
        if not messages:
            raise ValueError("No message found in input")
        
        message = messages[-1]
        log.info("Input: %s", inputs)
        log.info("Message: %s", message)
        
        user_id = messages[0].additional_kwargs.get("user_id")
        log.info("User ID: %s", user_id)
        if not user_id:
            raise ValueError("User ID is required in inputs.")

        tool_call_messages = process_tool_message(message.content)
        outputs = []
        for tool_call in tool_call_messages:
            log.info("Tool call: %s", tool_call)
            log.info("Tool call keys: %s", tool_call.keys())
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args")
            tool_id = tool_call.get("id")

            if tool_name not in self.tools_by_name:
                raise ValueError(f"Tool {tool_name} not found.")
            log.info("Tool %s found.", tool_name)
            tool_result = self.tools_by_name[tool_name].invoke(tool_args)

            if "human_respond" in tool_result:
                outputs.append(HumanMessage(
                    content=tool_result,
                    name=tool_name,
                    tool_call_id=tool_id,
                ))
            else:
                outputs.append(ToolMessage(
                    content=json.dumps(tool_result),
                    name=tool_name,
                    tool_call_id=tool_id,
                ))

                tool_message_dict = {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_result": tool_result,
                }
                tool_logs.add_log(
                    user_id=user_id,
                    tool_message=json.dumps(tool_message_dict)
                )
        
        return {"messages": outputs}
