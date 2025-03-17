"""This file is for utility function"""
import json
import os
from config.logger_setting import log
import re
from typing import List
import time
from functools import lru_cache
from datetime import datetime, timedelta, date
import uuid
import tzlocal
import requests

LOCAL_TIMEZONE = tzlocal.get_localzone()

@lru_cache(maxsize=128, typed=False)
def health_check_parsing() -> str:
    """This function is for parsing version information
    Return:
        version_str: str, return the project_version of the setup.py ex: 0.0.1
    """
    with open('setup.py', 'r') as f:
        setup_str = f.read()
    match_str = 'project_version='
    start_pos = setup_str.find(match_str) + len(match_str)
    end_pos = setup_str.find(',', start_pos)
    version_str = setup_str[start_pos:end_pos].replace("'", '')
    return version_str

def get_today_timestamp() -> int:
    """Get today UNIX timestamp in `int` type."""
    date_str = date.today().strftime('%Y-%m-%d')
    return time.mktime(datetime.strptime(date_str, "%Y-%m-%d").timetuple())

def get_current_timestamp() -> int:
    """Get current UNIX timestamp in `int` type."""
    return int(datetime.now().timestamp())

def get_yesterday_current_timestamp() -> int:
    """Get yesterday current UNIX timestamp in `int` type."""
    return int((datetime.now() - timedelta(days=1)).timestamp())

def get_month_first_timestamp() -> int:
    current_date = date.today()
    start_at  = date(current_date.year, current_date.month, 1)
    start_at_datetime = datetime(start_at.year, start_at.month, start_at.day)
    return int(start_at_datetime.timestamp())

def get_year_ago_timestamp() -> int:
    current_date = date.today()
    start_at  = date(current_date.year-1, current_date.month, 1)
    start_at_datetime = datetime(start_at.year, start_at.month, start_at.day)
    return int(start_at_datetime.timestamp())

def get_week_ago_timestamp() -> int:
    current_date = date.today()
    start_at  = current_date - timedelta(days=7)
    start_at_datetime = datetime(start_at.year, start_at.month, start_at.day)
    return int(start_at_datetime.timestamp())

def list_to_str(target_list: List[str])-> str:
    """List object to str without []
    Arguments:
    - target_list: target list object
    Return
    - str without []
    """
    return str(target_list).replace("[", "(").replace("]", ")")

def create_folder_if_not_exist(path: str)-> None:
    """create folder if not exist"""
    if not os.path.exists(path):
        os.makedirs(path)

def convert_timestamp_to_datetime(timestamp: int, time_format="%Y-%m-%d %H:%M:%S") -> str:
    """This function will convert timestamp to datetime with "%Y-%m-%d %H:%M:%S" format
    Example:
            convert_timestamp_to_datetime(1645895393) -> 2022-02-27 01:09:53
    """
    local_time = datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    return local_time.strftime(time_format)

def convert_datetime_to_timestamp(dt: datetime)-> int:
    """Convert a datetime object to a timestamp"""
    return int(dt.timestamp())

def generate_id():
    """Generate and return an id."""
    return uuid.uuid1()

def send_message_to_teams(node_server_url: str, user_id: str, message: str):
    """Send a message to the Teams user using the Node server"""

    try:
        data = {
            'title': '標題 天氣資料排程服務',
            'text': message
        }
        headers = {'Content-Type': 'application/json'}
        requests.post(url=node_server_url, headers=headers, data=json.dumps(data), verify=False)
        
    except Exception as err:
        print('Other error occurred %s' % {err})

def extract_direct_answer(content: str) -> str:
    """
    從模型的輸出中移除所有 <think>...</think> 區塊，
    """
    # 移除所有 <think>...</think> 區塊（DOTALL 表示換行也能匹配）
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

def extract_thinking(content: str) -> str:
    """
    從模型的輸出中擷取所有 <think>...</think> 區塊，
    並回傳其中的內容。
    """
    # 擷取所有 <think>...</think> 區塊
    return re.findall(r"<think>(.*?)</think>", content, flags=re.DOTALL)
