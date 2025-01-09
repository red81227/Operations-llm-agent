import json
import re
from langchain_core.messages import ToolMessage
from langchain_core.messages import ToolCall
from typing import List, Optional
import uuid

def process_tool_message(content: str) -> List[ToolCall]:
    # 使用正则表达式查找所有 <tool_call>...</tool_call> 块
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
            print("无法解析工具调用的 JSON 数据。")
    if not tool_calls:
        print("未找到工具调用信息。")
    return tool_calls
        
class BasicToolNode:
    """A node that runs the tools requested in the last AIMessage."""

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    def __call__(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No message found in input")

        tool_call_message = process_tool_message(inputs["messages"][-1].content)        
        outputs = []
        for tool_call in tool_call_message:
            tool_result = self.tools_by_name[tool_call["name"]].invoke(
                tool_call["args"]
            )
            outputs.append(
                ToolMessage(
                    content=json.dumps(tool_result),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": outputs}
