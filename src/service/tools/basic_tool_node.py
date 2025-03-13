"""Module for processing tool calls in agent conversations."""
import json
import re
from typing import List, Dict, Any, Callable, Optional, Tuple
import uuid
from functools import lru_cache

from langchain_core.messages import ToolMessage, ToolCall, HumanMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command
from src.operator.redis import RedisOperator
from src.service.event.redis.tool_logs import ToolLogs
from config.logger_setting import log


def process_tool_message(content: str) -> List[ToolCall]:
    """
    Extract and parse tool calls from message content.
    
    Args:
        content: String containing tool call markup in the format <tool_call>{...}</tool_call>
        
    Returns:
        List of ToolCall objects extracted from the content
    """
    if not content:
        return []
        
    tool_calls = []
    try:
        # More efficient regex that captures JSON objects with balanced braces
        matches = re.findall(r'<tool_call>\s*(\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\})\s*</tool_call>', 
                            content, re.DOTALL)
        
        for match in matches:
            try:
                tool_call_data = json.loads(match)
                # Validate required fields
                if not tool_call_data.get("name"):
                    log.warning(f"Tool call missing required 'name' field: {match}")
                    continue
                    
                tool_call = ToolCall(
                    name=tool_call_data.get("name"),
                    args=tool_call_data.get("arguments", {}),
                    id=str(uuid.uuid4()),
                    type=tool_call_data.get("type", "tool_call")
                )
                tool_calls.append(tool_call)
            except json.JSONDecodeError:
                log.error(f"Unable to parse tool call JSON data: {match[:100]}...")
    except Exception as e:
        log.error(f"Error processing tool message: {str(e)}")
        
    return tool_calls


class BasicToolNode:
    """
    A node that executes tools requested in messages and logs their usage.
    
    This class processes messages containing tool calls, executes the requested tools
    with provided arguments, and returns the results as appropriate message types.
    """

    def __init__(self, tools: list) -> None:
        """
        Initialize the BasicToolNode with a list of available tools.
        
        Args:
            tools: List of tool objects that can be invoked
        """
        self.tools_by_name = {tool.name: tool for tool in tools}
        self._redis_operator = RedisOperator()
        self._tool_logs = ToolLogs(operator=self._redis_operator)

    def __call__(self, inputs: Dict[str, Any], config: RunnableConfig) -> Dict[str, List]:
        """
        Process incoming messages and execute any tool calls found.
        
        Args:
            inputs: Dictionary containing messages and other input data
            
        Returns:
            Dictionary with resulting messages from tool executions
            
        Raises:
            ValueError: If required inputs are missing or invalid
        """
        messages = inputs.get("messages", [])
        
        user_id =  str(config["configurable"]["user_id"])
        if not messages:
            log.error("No messages found in input")
            return {"messages": [ToolMessage(content="Error: No messages to process", name="error")]}
        
        message = messages[-1]
        log.info(f"Processing message: {message.content[:100]}...")

        # Process and execute tool calls
        self._execute_tools(message.content, user_id)
    
    @lru_cache(maxsize=10)
    def get_tool_by_name(self, name: str) -> Optional[Callable]:
        """Get a tool by name with caching for performance."""
        return self.tools_by_name.get(name)
    
    def _execute_tools(self, content: str, user_id: int) -> Dict[str, List]:
        """
        Execute tools based on tool calls found in the message content.
        
        Args:
            content: Message content containing tool calls
            user_id: User ID for logging tool usage
            
        Returns:
            Dictionary with resulting messages from tool executions
        """
        tool_call_items = process_tool_message(content)
        if not tool_call_items:
            log.warning("No valid tool calls found in message")
            return {"messages": [ToolMessage(content="No valid tool calls found", name="system")]}
            
        outputs = []
        for tool_call in tool_call_items:
            tool_result, is_human_respond = self._process_single_tool_call(tool_call, user_id)
            if tool_result and is_human_respond:
                outputs.append(tool_result)
        if len(outputs) > 0:
            return {"messages": outputs}
    
    def _process_single_tool_call(self, tool_call: ToolCall, user_id: int) -> Tuple[Any, bool]:
        """Process a single tool call and return the result as a message."""
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args")
        tool_id = tool_call.get("id")

        if not tool_name:
            log.error("Tool call missing name")
            return ToolMessage(content="Error: Tool call missing name", name="error", tool_call_id=tool_id)

        tool = self.get_tool_by_name(tool_name)
        if not tool:
            log.error(f"Tool '{tool_name}' not found")
            return ToolMessage(
                content=f"Error: Tool '{tool_name}' not found or not available", 
                name="error",
                tool_call_id=tool_id
            )
        
        
        log.info(f"Invoking tool '{tool_name}' with args: {tool_args}")
        tool_result = tool.invoke(tool_args)
        log.info(f"Tool '{tool_name}' result: {str(tool_result)[:100]}...")
        
        # Log successful tool execution
        self._log_tool_execution(user_id, tool_name, tool_args, tool_result)
        
        # Return appropriate message type based on result
        if isinstance(tool_result, str) and "human_respond" in tool_result:
            return HumanMessage(
                content=tool_result,
                name=tool_name,
                tool_call_id=tool_id,
            ), True
        else:
            return ToolMessage(
                content=tool_result,
                name=tool_name,
                tool_call_id=tool_id,
            ), False
                

    
    def _log_tool_execution(self, user_id: int, tool_name: str, tool_args: Dict, tool_result: Any) -> None:
        """Log tool execution details for future reference."""
        try:
            tool_message_dict = {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_result": str(tool_result)[:1000]  # Limit result size for logging
            }
            self._tool_logs.add_log(
                user_id=user_id,
                tool_message=json.dumps(tool_message_dict, ensure_ascii=False)
            )
        except Exception as e:
            log.error(f"Failed to log tool execution: {str(e)}")

