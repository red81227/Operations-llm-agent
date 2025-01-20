"""This file is for application config"""
from typing import List
from pydantic import BaseSettings, Field


class ServiceConfig(BaseSettings):
    """This file define the config that will be utilized to service"""
    log_file_path: str = 'data/logs/'
    log_file_name: str = 'service_ems_school_llm.log'
    system_name: str = "service_ems_school_llm"
    # it is hashed value from 'secret'
    default_hashed_password: str = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"

class LlmConfig(BaseSettings):
    api_key: str = ""
    llm_url: str = ""
    llm_model: str = ""
    temperature: float = 0
    max_retries: int = 2
    top_p: float = 0.9
    frequency_penalty: float = 0

class BotConfig(BaseSettings):
    node_server_url: str = "https://teams.microsoft.com/l/channel/19%3A9UodnXhzLX8Sy5nEEqzeo3WO_TNbeUzMTLNR6bDTgEw1%40thread.tacv2/%E6%8E%92%E7%A8%8B%E6%8F%90%E7%A4%BA?groupId=f68a2cc8-a443-4621-b329-ca445d7f0b13"


class RedisConfigSettings(BaseSettings):
    host: str = Field("redis", env="REDIS_HOST")
    port: int = Field(6379, env="REDIS_PORT")
    password: str = Field(None, env="REDIS_PASSWORD")
    db: int = Field(0, env="REDIS_DB")


service_config = ServiceConfig()
llm_config = LlmConfig()
bot_config = BotConfig()
redis_config = RedisConfigSettings()
