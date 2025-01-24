"""This file is for application config"""
from typing import List
from pydantic import BaseSettings, Field


class ServiceConfig(BaseSettings):
    """This file define the config that will be utilized to service"""
    log_file_path: str = 'data/logs/'
    log_file_name: str = 'service_ems_school_llm.log'
    system_name: str = "service_ems_school_llm"

    mqtt_queue_size: int = 10000
    mqtt_thread_size: int = 3

class LlmConfig(BaseSettings):
    api_key: str = Field("", env="API_KEY")
    llm_url: str = Field("", env="LLM_URL")
    llm_model: str = Field("", env="LLM_MODEL")
    temperature: float = 0
    max_retries: int = 2
    top_p: float = 0.9
    frequency_penalty: float = 0

class BotConfig(BaseSettings):
    node_server_url: str =  Field("", env="NODE_SERVER_URL")

class RedisConfigSettings(BaseSettings):
    host: str = Field("redis", env="REDIS_HOST")
    port: int = Field(6379, env="REDIS_PORT")
    password: str = Field(None, env="REDIS_PASSWORD")
    db: int = Field(0, env="REDIS_DB")

class TavilyConfig(BaseSettings):
    api_key: str = Field("", env="TAVILY_API_KEY")

service_config = ServiceConfig()
llm_config = LlmConfig()
bot_config = BotConfig()
redis_config = RedisConfigSettings()
tavily_config = TavilyConfig()

