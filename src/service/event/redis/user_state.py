"""Contains a UserDictStore class to handle user dictionary objects in Redis."""
# pylint: disable=too-few-public-methods

import json
from typing import Dict, Any, Optional
import datetime
from src.operator.redis import RedisOperator


class UserState:
    """A class to handle storing and retrieving state objects in Redis by user_id."""

    def __init__(self, operator: RedisOperator):
        """
        Initialize the UserState with a RedisOperator.
        
        Args:
            operator: RedisOperator instance for Redis operations
        """
        self.operator = operator
        self.prefix = "user_state:"  # 前綴避免與其他 Redis 鍵衝突

    def store_state(self, user_id: str, state_obj: Dict[str, Any], 
                   expiration_hours: int = 12) -> bool:
        """
        Store a dictionary object in Redis with the specified user_id as key.
        
        Args:
            user_id: User identifier
            dict_obj: Dictionary object to store
            expiration_hours: Expiration time in hours (default: 12)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            key = f"{self.prefix}{user_id}"
            # 將字典轉換為 JSON 字符串
            state_json = json.dumps(state_obj)
            # 存儲到 Redis
            self.operator.set(key, state_json)
            # 設置過期時間
            self.operator.expire(key, expiration_hours * 60 * 60)
            return True
        except Exception as e:
            print(f"Error storing dict for user {user_id}: {e}")
            return False

    def get_state(self, user_id: str) -> Dict[str, Any]:
        """
        Retrieve the dictionary object for a user_id.
        
        Args:
            user_id: User identifier
            
        Returns:
            Dict or None: The stored dictionary object, or None if not found
        """
        try:
            key = f"{self.prefix}{user_id}"
            state_json = self.operator.get(key)
            
            if state_json:
                return json.loads(state_json)
            return {}
        except Exception as e:
            print(f"Error retrieving dict for user {user_id}: {e}")
            return None

    def update_state(self, user_id: str, updated_state: Dict[str, Any], 
                    expiration_hours: int = 12) -> bool:
        """
        Update an existing dictionary for a user or create a new one if it doesn't exist.
        
        Args:
            user_id: User identifier
            updated_dict: New or updated dictionary
            expiration_hours: Expiration time in hours (default: 12)
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.store_state(user_id, updated_state, expiration_hours)

    def delete_state(self, user_id: str) -> bool:
        """
        Delete the dictionary object for a user_id.
        
        Args:
            user_id: User identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            key = f"{self.prefix}{user_id}"
            return bool(self.operator.delete(key))
        except Exception as e:
            print(f"Error deleting dict for user {user_id}: {e}")
            return False