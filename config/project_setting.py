"""This file is for application config"""
from typing import List
from pydantic import BaseSettings, Field


class ServiceConfig(BaseSettings):
    """This file define the config that will be utilized to service"""
    log_file_path: str = 'data/logs/'
    log_file_name: str = 'service_ems_school_llm.log'
    system_name: str = "service_ems_school_llm"
    default_hashed_password: str = ""

    mqtt_queue_size: int = 10000
    mqtt_thread_size: int = 3

class QwenLlmConfig(BaseSettings):
    api_key: str = Field("EMPTY", env="QWEN_LLM_API_KEY")
    llm_url: str = Field("", env="QWEN_LLM_URL")
    llm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    temperature: float = 0.6
    max_retries: int = 2
    frequency_penalty: float = 0

class DeepSeekLlmConfig(BaseSettings):
    api_key: str = Field("EMPTY", env="DEEPSEEK_LLM_API_KEY")
    llm_url: str = Field("", env="DEEPSEEK_LLM_URL")
    llm_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"
    temperature: float = 0.6
    max_retries: int = 2
    frequency_penalty: float = 0

class BotConfig(BaseSettings):
    node_server_url: str = Field("", env="NODE_SERVER_URL")


class RedisConfigSettings(BaseSettings):
    host: str = Field("redis", env="REDIS_HOST")
    port: int = Field(6379, env="REDIS_PORT")
    password: str = Field(None, env="REDIS_PASSWORD")
    db: int = Field(0, env="REDIS_DB")

class mqttConfig(BaseSettings):
    broker_hos: str = Field("", env="MQTT_BROKER_HOST")
    broker_port: int = Field(8883, env="MQTT_BROKER_PORT")
    topic: str = Field("", env="MQTT_TOPIC")
    username: str = Field("", env="MQTT_USERNAME")
    password: str = Field("", env="MQTT_PASSWORD")



service_config = ServiceConfig()
qwen_llm_config = QwenLlmConfig()
deepseek_llm_config = DeepSeekLlmConfig()
bot_config = BotConfig()
redis_config = RedisConfigSettings()
