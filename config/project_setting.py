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

class Qwen14BAWQLlmConfig(BaseSettings):
    api_key: str = Field("EMPTY", env="QWEN_14B_AWQ_LLM_API_KEY")
    llm_url: str = Field("", env="QWEN_14B_AWQ_LLM_URL")
    llm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    temperature: float = 0.2
    max_retries: int = 2
    frequency_penalty: float = 0

class DeepSeek32BAWQLlmConfig(BaseSettings):
    api_key: str = Field("EMPTY", env="DEEPSEEK_32B_AWQ_LLM_API_KEY")
    llm_url: str = Field("", env="DEEPSEEK_32B_AWQ_LLM_URL")
    llm_model: str = "Valdemardi/DeepSeek-R1-Distill-Qwen-32B-AWQ"
    temperature: float = 0.2
    max_retries: int = 2
    frequency_penalty: float = 0

class DeepSeek14BAWQLlmConfig(BaseSettings):
    api_key: str = Field("EMPTY", env="DEEPSEEK_14B_AWQ_LLM_API_KEY")
    llm_url: str = Field("", env="DEEPSEEK_14B_AWQ_LLM_URL")
    llm_model: str = "stelterlab/DeepSeek-R1-Distill-Qwen-14B-AWQ"
    temperature: float = 0.1
    max_retries: int = 2
    frequency_penalty: float = 0

class BotConfig(BaseSettings):
    node_server_url: str = Field("", env="NODE_SERVER_URL")

class RedisConfigSettings(BaseSettings):
    host: str = Field("redis", env="REDIS_HOST")
    port: int = Field(6379, env="REDIS_PORT")
    password: str = Field(None, env="REDIS_PASSWORD")
    db: int = Field(0, env="REDIS_DB")

class  WeatherConfig(BaseSettings):
    taiwan_timezone: str = "Asia/Taipei"
    cwa_api_token: str = Field("EMPTY", env="CWA_API_TOKEN")
    cwa_api_url: str = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    default_duration_minutes: int = 60
    default_frequency_seconds: int = 60
    valid_weather_elements: List[str] = ["Wx", "MaxT", "MinT", "CI", "PoP"]
    valid_locations: List[str] = [
        '臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', 
        '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義縣', 
        '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣',
        '連江縣', '基隆市', '新竹市', '嘉義市'
    ]

class MqttConfig(BaseSettings):
    default_duration_seconds: int = 3600
    broker_host: str = Field("mqtt", env="MQTT_BROKER_HOST")
    broker_port: int = Field(1883, env="MQTT_BROKER_PORT")
    username: str = Field("", env="MQTT_USERNAME")
    password: str = Field("", env="MQTT_PASSWORD")
    topic: str = Field("", env="MQTT_TOPIC")

service_config = ServiceConfig()
qwen_14b_awq_llm_config = Qwen14BAWQLlmConfig()
deepseek_32b_awq_llm_config = DeepSeek32BAWQLlmConfig()
deepseek_14b_awq_llm_config = DeepSeek14BAWQLlmConfig()
bot_config = BotConfig()
redis_config = RedisConfigSettings()
weather_config = WeatherConfig()
mqtt_config = MqttConfig()
