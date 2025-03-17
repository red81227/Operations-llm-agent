"""Module for retrieving and scheduling weather information from CWA API."""
import json
import requests
from typing import Annotated, List, Union, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import functools
import threading

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore

from langchain_core.tools import tool, InjectedToolArg
from langgraph.types import interrupt
from config.logger_setting import log
from config.project_setting import bot_config, qwen_14b_awq_llm_config, weather_config
from langchain_openai import ChatOpenAI
from src.util.function_utils import send_message_to_teams
from langchain_core.runnables.config import RunnableConfig


# Create a global scheduler instance
_scheduler = None
_scheduler_lock = threading.Lock()

def get_scheduler() -> BackgroundScheduler:
    """
    Get or initialize the global scheduler as a singleton.
    
    Returns:
        BackgroundScheduler: A configured scheduler instance
    """
    global _scheduler
    
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(
                timezone=pytz.timezone(weather_config.taiwan_timezone),
                jobstores={'default': MemoryJobStore()},
                job_defaults={
                    'coalesce': True,
                    'max_instances': 1,
                    'misfire_grace_time': 30
                }
            )
            _scheduler.start()
            log.info("Weather API scheduler initialized and started")
    
    return _scheduler

@functools.lru_cache(maxsize=32, typed=True)
def validate_parameters(locations: Tuple[str], elements: Tuple[str]) -> Dict[str, List[str]]:
    """
    Validate the location and element parameters.
    
    Args:
        locations: Tuple of location names to validate
        elements: Tuple of element names to validate
        
    Returns:
        Dict containing lists of invalid locations and elements
    """
    invalid = {"locations": [], "elements": []}
    
    for loc in locations:
        if loc not in weather_config.valid_locations:
            invalid["locations"].append(loc)
            
    for elem in elements:
        if elem not in weather_config.valid_weather_elements:
            invalid["elements"].append(elem)
            
    return invalid

def fetch_weather_data(location_names: List[str], element_names: List[str]) -> str:
    """
    Fetch weather data from CWA API based on locations and elements.
    
    Args:
        location_names: List of location names in Traditional Chinese
        element_names: List of element codes (Wx, MaxT, etc.)
        
    Returns:
        JSON string with the weather data or error messages
    """
    # Convert lists to tuples for caching
    locations_tuple = tuple(location_names)
    elements_tuple = tuple(element_names)
    
    # Validate parameters
    invalid = validate_parameters(locations_tuple, elements_tuple)
    if invalid["locations"] or invalid["elements"]:
        error_msg = {}
        if invalid["locations"]:
            error_msg["invalid_locations"] = invalid["locations"]
        if invalid["elements"]:
            error_msg["invalid_elements"] = invalid["elements"]
        return json.dumps({"error": "Invalid parameters", "details": error_msg}, ensure_ascii=False)

    results = {}
    success = True

    for loc in location_names:
        results[loc] = {}
        for elem in element_names:
            try:
                response = requests.get(
                    weather_config.cwa_api_url,
                    params={
                        'Authorization': weather_config.cwa_api_token,
                        'locationName': loc,
                        'elementName': elem
                    },
                    timeout=10  # Add timeout for better error handling
                )
                response.raise_for_status()
                
                # Extract and sanitize the API response
                api_data = response.json()
                if "success" not in api_data or not api_data["success"]:
                    results[loc][elem] = {"error": "API returned unsuccessful status", "details": api_data.get("message", "No message")}
                    success = False
                    continue
                    
                results[loc][elem] = api_data.get('records', {})
            except requests.RequestException as e:
                log.error(f"API request failed for {loc}/{elem}: {str(e)}")
                results[loc][elem] = {"error": f"Request failed: {type(e).__name__}", "details": str(e)}
                success = False
            except (ValueError, json.JSONDecodeError) as e:
                log.error(f"Failed to parse API response for {loc}/{elem}: {str(e)}")
                results[loc][elem] = {"error": "Failed to parse response", "details": str(e)}
                success = False

    # Return JSON string with metadata
    response_data = {
        "success": success,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": results
    }
    
    return json.dumps(response_data, ensure_ascii=False)

def parse_datetime(date_str: str) -> Optional[datetime]:
    """
    Parse a datetime string in YYYY-MM-DD HH:MM:SS format.
    
    Args:
        date_str: String representation of datetime
        
    Returns:
        datetime object or None if parsing fails
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        log.error(f"Failed to parse datetime '{date_str}': {str(e)}")
        return None

def scheduled_weather_task(llm: ChatOpenAI, user_id: str, location_names: List[str], element_names: List[str]) -> None:
    """
    Task to fetch weather data and send analysis to user via Teams.
    
    Args:
        llm: LLM instance for data analysis
        user_id: User ID to receive the notification
        location_names: List of locations to query
        element_names: List of weather elements to query
    """
    try:
        # Log task execution
        log.info(f"Executing scheduled weather task for user {user_id}, locations: {location_names}, elements: {element_names}")
        
        # Fetch weather data
        weather_data_str = fetch_weather_data(location_names, element_names)
        weather_data = json.loads(weather_data_str)
        
        # Check if successful
        if not weather_data.get("success", False):
            log.warning(f"Weather API returned errors: {weather_data}")
            error_message = "天氣資料取得失敗，請稍後再試。錯誤詳情請查看系統日誌。"
            send_message_to_teams(bot_config.node_server_url, user_id, message=error_message)
            return

        # Create analysis prompt
        prompt = f"""
        請分析以下天氣資料，並以繁體中文提供簡明的天氣預報摘要。
        請特別注意以下幾點：
        1. 主要關注溫度變化趨勢、降雨機率、舒適度變化
        2. 提供合適的穿著建議
        3. 如果有異常天氣現象，請特別強調
        
        資料來源：
        {json.dumps(weather_data["data"], indent=2, ensure_ascii=False)}
        
        請以「天氣預報摘要」開頭，並組織成易於閱讀的格式。
        """
        
        # Analyze with LLM
        llm_response = llm.invoke(prompt)
        llm_message = llm_response.content.strip()
        
        # Add metadata footer
        footer = f"\n\n資料更新時間：{weather_data['timestamp']}，資料來源：中央氣象局"
        complete_message = llm_message + footer
        
        # Send to Teams
        log.info(f"Sending weather analysis to user {user_id}")
        send_message_to_teams(bot_config.node_server_url, user_id, message=complete_message)
        
    except Exception as e:
        log.error(f"Error in scheduled weather task: {str(e)}")
        error_message = f"執行天氣查詢排程時發生錯誤：{str(e)}"
        try:
            send_message_to_teams(bot_config.node_server_url, user_id, message=error_message)
        except Exception as send_error:
            log.error(f"Failed to send error message to user: {str(send_error)}")

def create_llm_instance() -> ChatOpenAI:
    """Create and configure an LLM instance for weather analysis."""
    return ChatOpenAI(
        api_key=qwen_14b_awq_llm_config.api_key,
        base_url=qwen_14b_awq_llm_config.llm_url,
        model=qwen_14b_awq_llm_config.llm_model,
        temperature=qwen_14b_awq_llm_config.temperature,
        max_retries=qwen_14b_awq_llm_config.max_retries,
        frequency_penalty=qwen_14b_awq_llm_config.frequency_penalty,
    )

@tool
def get_weather_information(
    locationName: Annotated[List[str], InjectedToolArg],
    elementName: Annotated[List[str], InjectedToolArg]
) -> str:
    """
    Get weather forecast information for specified locations and elements.

    This function calls the Central Weather Administration (CWA) open data platform API 
    to retrieve 36-hour weather forecasts for cities in Taiwan.
    
    Args:
        locationName: List of location names in Traditional Chinese, e.g., ["桃園市"]
                      Must be one of the valid Taiwan cities/counties.
        elementName: List of weather element codes:
            - "Wx": Weather phenomena
            - "MaxT": Maximum temperature
            - "MinT": Minimum temperature
            - "CI": Comfort index
            - "PoP": Probability of precipitation

    Returns:
        JSON string with weather forecast information or error details.
    """
    try:
        # Ensure parameters are lists
        locations = [locationName] if isinstance(locationName, str) else locationName
        elements = [elementName] if isinstance(elementName, str) else elementName
        
        log.info(f"Weather information request: locations={locations}, elements={elements}")
        return fetch_weather_data(locations, elements)
        
    except Exception as e:
        log.error(f"Error in get_weather_information: {str(e)}")
        return json.dumps({
            "error": f"Failed to get weather information: {type(e).__name__}",
            "details": str(e)
        }, ensure_ascii=False)

@tool
def schedule_get_weather_information(
    locationName: Annotated[List[str], InjectedToolArg],
    elementName: Annotated[List[str], InjectedToolArg],
    config: RunnableConfig,
    start_time: Annotated[str, InjectedToolArg] = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    duration: Annotated[int, InjectedToolArg] = weather_config.default_duration_minutes,
    frequency: Annotated[int, InjectedToolArg] = weather_config.default_frequency_seconds,
) -> str:
    """
    Schedule recurring weather information updates for specified locations.

    This tool sets up a scheduled task that periodically retrieves weather information
    and sends updates to the user via Teams.
    
    Args:
        locationName: required, List of location names (Traditional Chinese, e.g., ["桃園市"])
        elementName: required, List of weather element codes ("Wx", "MaxT", "MinT", "CI", "PoP")
        start_time: Schedule start time in format "YYYY-MM-DD HH:MM:SS"
        duration: Duration in minutes (default: 60)
        frequency: Update frequency in seconds (default: 60)

    Returns:
        JSON string with schedule setup status or error information
    """

    user_id =  str(config["configurable"]["user_id"])
    # Ensure parameters are lists
    locations = [locationName] if isinstance(locationName, str) else locationName
    elements = [elementName] if isinstance(elementName, str) else elementName
    
    # Validate parameters
    invalid = validate_parameters(tuple(locations), tuple(elements))
    if invalid["locations"] or invalid["elements"]:
        error_details = {}
        if invalid["locations"]:
            error_details["invalid_locations"] = invalid["locations"]
            error_details["valid_locations"] = weather_config.valid_locations
        if invalid["elements"]:
            error_details["invalid_elements"] = invalid["elements"]
            error_details["valid_elements"] = weather_config.valid_weather_elements
            
        return json.dumps({
            "error": "Invalid parameters for weather scheduling",
            "details": error_details
        }, ensure_ascii=False)
    
    # Format user confirmation message
    location_str = ", ".join(locations)
    element_str = ", ".join(elements)
    
    confirmation_message = (
        f"是否要執行對【{location_str}】的氣象要素【{element_str}】的定時天氣查詢？\n"
        f"將在【{start_time}】開始執行，持續【{duration}】分鐘，每【{frequency}】秒更新一次。\n"
        f"如果確定請回答「是」，否則請回答「否」或說明原因。"
    )
    
    # Ask for user confirmation
    user_approval = interrupt({"question": confirmation_message})

    # Check if user approved
    if user_approval.lower() in ["是", "yes", "对", "對", "好", "确定", "確定"]:
        try:
            # Parse start time
            start_dt = parse_datetime(start_time)
            if not start_dt:
                start_dt = datetime.now() + timedelta(seconds=10)
                log.warning(f"Invalid start_time '{start_time}', using current time + 10s instead")
            
            # Calculate end time
            end_dt = start_dt + timedelta(minutes=duration)
            
            # Get the scheduler
            scheduler = get_scheduler()
            
            # Create LLM instance
            llm = create_llm_instance()
            
            # Create a unique job ID
            job_id = f"weather_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Schedule the task
            scheduler.add_job(
                scheduled_weather_task,
                'interval',
                seconds=frequency,
                start_date=start_dt,
                end_date=end_dt,
                id=job_id,
                args=[llm, user_id, locations, elements],
                replace_existing=True
            )
            
            log.info(f"Scheduled weather updates for user {user_id}, job_id={job_id}")
            
            # Create success response
            success_message = {
                'status': 'success',
                'message': (
                    f"已成功設定天氣預報排程服務。結果將定期推送到Teams。\n"
                    f"排程開始時間：{start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"排程結束時間：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"更新頻率：每 {frequency} 秒\n"
                    f"查詢地點：{location_str}\n"
                    f"氣象要素：{element_str}"
                ),
                'job_id': job_id
            }
            
            return json.dumps(success_message, ensure_ascii=False)
            
        except Exception as e:
            log.error(f"Error creating weather schedule: {str(e)}")
            return json.dumps({
                'status': '執行工具失敗',
                'message': f"設定天氣預報排程時發生錯誤: {str(e)}",
            }, ensure_ascii=False)
    else:
        # User rejected the schedule
        return json.dumps({
                'status': '沒有執行工具，使用者希望對工具執行做調整',
                'human_respond': user_approval,
            }, ensure_ascii=False)

@tool
def list_weather_schedules(
    config: RunnableConfig
) -> str:
    """
    列出當前使用者的所有進行中的天氣預報排程。

    此工具會返回使用者目前啟動的所有天氣預報定時任務，包含每個任務的詳細資訊，
    如查詢地點、氣象要素、開始和結束時間、更新頻率等。

    Returns:
        包含所有進行中定時任務的 JSON 字符串
    """
    try:
        user_id = str(config["configurable"]["user_id"])
        scheduler = get_scheduler()
        
        # 獲取所有排程
        jobs = scheduler.get_jobs()
        
        # 篩選屬於當前使用者的排程
        user_jobs = []
        for job in jobs:
            job_id = job.id
            
            # 檢查 job_id 是否含有使用者 ID，或使用參數傳遞的 user_id
            if f"weather_{user_id}" in job_id or (len(job.args) >= 2 and job.args[1] == user_id):
                # 提取排程資訊
                job_args = job.args
                
                # 確保 job_args 結構正確，否則跳過
                if len(job_args) < 4:
                    continue
                    
                _, target_user_id, locations, elements = job_args
                
                # 組織排程資訊
                schedule_info = {
                    'job_id': job_id,
                    'locations': locations,
                    'elements': elements,
                    'start_time': job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "排程已暫停",
                    'end_time': job.end_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(job, 'end_date') and job.end_date else "無結束時間",
                    'interval_seconds': job.trigger.interval.seconds if hasattr(job.trigger, 'interval') else None,
                    'status': "進行中" if job.next_run_time else "已暫停"
                }
                user_jobs.append(schedule_info)
        
        if not user_jobs:
            return json.dumps({
                'status': 'info',
                'message': '您目前沒有進行中的天氣預報排程。'
            }, ensure_ascii=False)
        
        return json.dumps({
            'status': 'success',
            'message': f'找到 {len(user_jobs)} 個進行中的天氣預報排程。',
            'schedules': user_jobs
        }, ensure_ascii=False)
        
    except Exception as e:
        log.error(f"Error listing weather schedules: {str(e)}")
        return json.dumps({
            'status': 'error',
            'message': f'獲取天氣預報排程時發生錯誤: {str(e)}'
        }, ensure_ascii=False)


@tool
def stop_weather_schedule(
    job_id: Annotated[str, InjectedToolArg],
    config: RunnableConfig
) -> str:
    """
    停止指定的天氣預報排程任務。

    用戶可以通過提供排程任務的 job_id 來停止特定的天氣預報排程。
    如果用戶沒有提供 job_id，系統會請求用戶先使用 list_weather_schedules 工具
    查詢目前進行中的排程，然後選擇要停止的排程。

    Args:
        job_id: 要停止的排程任務 ID (通過 list_weather_schedules 獲取)

    Returns:
        包含操作結果的 JSON 字符串
    """
    try:
        user_id = str(config["configurable"]["user_id"])
        scheduler = get_scheduler()
        
        # 如果未提供 job_id，獲取用戶的所有排程並讓用戶選擇
        if not job_id:
            # 獲取用戶的所有排程
            jobs = scheduler.get_jobs()
            user_jobs = []
            
            for job in jobs:
                job_id_str = job.id
                
                # 檢查 job_id 是否含有使用者 ID，或使用參數傳遞的 user_id
                if f"weather_{user_id}" in job_id_str or (len(job.args) >= 2 and job.args[1] == user_id):
                    if len(job.args) >= 4:
                        _, _, locations, elements = job.args
                        location_str = ", ".join(locations)
                        element_str = ", ".join(elements)
                        
                        job_info = {
                            'job_id': job_id_str,
                            'description': f"{location_str} 的 {element_str}",
                            'next_run': job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "排程已暫停"
                        }
                        user_jobs.append(job_info)
            
            if not user_jobs:
                return json.dumps({
                    'status': 'info',
                    'message': '您目前沒有進行中的天氣預報排程。'
                }, ensure_ascii=False)
            
            # 格式化選擇清單
            options = "\n".join([f"{i+1}. ID: {j['job_id']} - {j['description']} (下次執行: {j['next_run']})" 
                               for i, j in enumerate(user_jobs)])
            
            # 請使用者選擇要停止的排程
            user_choice = interrupt({
                "question": f"請選擇要停止的天氣預報排程（輸入對應的數字）：\n{options}\n\n或輸入「取消」以放棄操作。"
            })
            
            # 處理使用者選擇
            try:
                if user_choice.lower() in ["取消", "cancel", "no", "否"]:
                    return json.dumps({
                        'status': 'cancelled',
                        'message': '已取消停止排程的操作。'
                    }, ensure_ascii=False)
                
                choice_index = int(user_choice.strip()) - 1
                if 0 <= choice_index < len(user_jobs):
                    job_id = user_jobs[choice_index]['job_id']
                else:
                    return json.dumps({
                        'status': 'error',
                        'message': f'無效的選擇：{user_choice}，請輸入 1 到 {len(user_jobs)} 之間的數字。'
                    }, ensure_ascii=False)
            except ValueError:
                return json.dumps({
                    'status': 'error',
                    'message': f'無效的輸入：{user_choice}，請輸入數字。'
                }, ensure_ascii=False)
        
        # 嘗試移除排程
        job = scheduler.get_job(job_id)
        if not job:
            return json.dumps({
                'status': 'error',
                'message': f'找不到指定的排程 ID：{job_id}'
            }, ensure_ascii=False)
        
        # 確認此排程確實屬於當前使用者
        job_args = job.args
        if len(job_args) >= 2 and job_args[1] != user_id and f"weather_{user_id}" not in job_id:
            return json.dumps({
                'status': 'error',
                'message': '您無權停止其他使用者的排程。'
            }, ensure_ascii=False)
        
        # 移除排程
        scheduler.remove_job(job_id)
        
        return json.dumps({
            'status': 'success',
            'message': f'已成功停止天氣預報排程 (ID: {job_id})。'
        }, ensure_ascii=False)
        
    except Exception as e:
        log.error(f"Error stopping weather schedule: {str(e)}")
        return json.dumps({
            'status': 'error',
            'message': f'停止天氣預報排程時發生錯誤: {str(e)}'
        }, ensure_ascii=False)