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
    node_server_url: str = "http://host.docker.internal:3978/api/proactiveMessages"


service_config = ServiceConfig()
llm_config = LlmConfig()
bot_config = BotConfig()
