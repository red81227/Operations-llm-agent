"""Contains a tool log class."""
# pylint: disable=too-few-public-methods

import json
from src.operator.redis import RedisOperator
import datetime


class ToolLogs:
    """A tool logs class to handle tool usage logs in Redis."""

    def __init__(self, operator: RedisOperator):
        self.operator = operator

    def add_log(self, user_id: str, tool_message: str):
        """Add a tool log with a 12-hour expiration using user_id as key."""
        log_entry = {
            "tool_message": tool_message,
            "execution_time": datetime.datetime.now().isoformat()
        }
        unique_field = datetime.datetime.now().isoformat()
        log_entry_json = json.dumps(log_entry)
        self.operator.hset(user_id, unique_field, log_entry_json)
        self.operator.expire(user_id, 12 * 60 * 60)  # Expire in 12 hours

    def get_logs(self, user_id: str):
        """Retrieve all tool logs for a user_id."""
        logs = self.operator.hgetall(user_id)
        return {key.decode(): json.loads(value) for key, value in logs.items()}
