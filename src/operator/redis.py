"""Contains a Redis Operator class."""
# pylint: disable=no-member
import redis
import datetime
import json
from config.project_setting import redis_config

class RedisOperator:
    # pylint: disable=too-many-public-methods
    """Operator with Redis backend."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        # pylint: disable=unused-argument
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._set_conn_pool()

    def _set_conn_pool(self):
        connection_info = redis_config.dict()
        self._redis_conn_pool = redis.ConnectionPool(**connection_info)

    @property
    def redis_conn(self):
        """Return a redis connection object."""
        return redis.Redis(connection_pool=self._redis_conn_pool)

    def hset(self, name: str, key: str, value):
        """Set a field in a hash in Redis."""
        return self.redis_conn.hset(name, key, value)

    def hgetall(self, name: str):
        """Get all fields and values in a hash."""
        return self.redis_conn.hgetall(name)

    def expire(self, name: str, time):
        """Set an expiration time on a key."""
        return self.redis_conn.expire(name, time)
