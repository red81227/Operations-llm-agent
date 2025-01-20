import json
import requests
from typing import Annotated, List, Union, Dict, Any
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from langchain_core.tools import tool, InjectedToolArg
from langgraph.types import interrupt
from config.logger_setting import log
from config.project_setting import llm_config, bot_config
from langchain_openai import ChatOpenAI
from src.util.function_utils import send_message_to_teams


def initialize_scheduler() -> BackgroundScheduler:
    """
    初始化並回傳一個位於 Asia/Taipei 時區的 BackgroundScheduler 實例。
    """
    scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Taipei"))
    return scheduler


def fetch_weather_data(location_names: List[str], element_names: List[str]) -> str:
    """
    根據地點清單與氣象要素清單，呼叫氣象局開放資料平台 (F-C0032-001) API。
    回傳 JSON (string) 格式的結果。
    """
    access_token = "CWA-541B25A0-2523-46AF-9087-5849D99974C0"
    base_url = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001'
    results = {}

    for loc in location_names:
        results[loc] = {}
        for elem in element_names:
            try:
                response = requests.get(
                    base_url,
                    params={
                        'Authorization': access_token,
                        'locationName': loc,
                        'elementName': elem
                    }
                )
                response.raise_for_status()
                # 取得 'records' 作為回傳主體
                results[loc][elem] = response.json().get('records', {})
            except requests.RequestException as e:
                # 若出現網路/請求異常，將錯誤訊息放入 results
                results[loc][elem] = f"Error fetching data: {e}"

    # 結果轉為 JSON 字串 (確保中文可顯示)
    return json.dumps(results, ensure_ascii=False)


def scheduled_weather_task(llm, user_id: str, location_names: List[str], element_names: List[str]) -> None:
    """
    排程任務：呼叫 fetch_weather_data() 抓取天氣資訊，
    透過 LLM 分析後再將結果傳到 Teams。
    """
    

    # 抓取氣象資料
    weather_data_str = fetch_weather_data(location_names, element_names)
    # 送入 LLM 作簡單檢查或處理
    prompt = f"请检查以下数据的完整性：{weather_data_str}"
    llm_response = llm.invoke(prompt)

    # 結果記錄與推播
    llm_message = llm_response.content.strip() + "\n" + weather_data_str
    log.info(f"[Scheduler Task] LLM response: {llm_message}, weather_data_str: {weather_data_str}")

    # 主動推播訊息到 Teams
    send_message_to_teams(bot_config.node_server_url, user_id, message=llm_message)


@tool
def get_weather_information(
    locationName: Annotated[List[str], InjectedToolArg],
    elementName: Annotated[List[str], InjectedToolArg]
) -> Union[str, Dict[str, Any]]:
    """
    獲取指定地點的特定氣象要素的天氣預報信息。

    此函數調用中央氣象局開放數據平台的 API，獲取各縣市或國際都市的今明36小時天氣預報。
    
    Args:
        locationName (list[str]): 查詢的地點名稱，請使用繁體中文，例如：["桃園縣"]。
        elementName (list[str]): 氣象要素的英文代碼，可選值：
            - "Wx"：天氣現象
            - "MaxT"：最高溫度
            - "MinT"：最低溫度
            - "CI"：舒適度
            - "PoP"：降雨機率

    Returns:
        str: 已轉為 JSON 字串格式的天氣預報信息。
             如 API 請求失敗，則回傳錯誤訊息。
    """
    try:
        # 若參數是單一字串，轉成 list
        if isinstance(locationName, str):
            locationName = [locationName]
        if isinstance(elementName, str):
            elementName = [elementName]

        return fetch_weather_data(locationName, elementName)
    except requests.RequestException as e:
        # 捕捉與 requests 相關的異常
        return f"Error fetching data: {e}"


@tool
def schedule_get_weather_information(
    locationName: Annotated[List[str], InjectedToolArg],
    elementName: Annotated[List[str], InjectedToolArg],
    start_time: Annotated[str, InjectedToolArg],
    duration: Annotated[int, InjectedToolArg],
    frequency: Annotated[int, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg],
) -> Union[str, Dict[str, Any]]:
    """
    持續獲取指定地點的特定氣象要素的天氣預報信息。此函數會啟動一個排程服務，
    在指定的 start_time (格式 "YYYY-MM-DD HH:MM:SS") 開始，
    持續 duration 分鐘，每 frequency 秒呼叫一次天氣API。
    
    Args:
        locationName (list[str]): 查詢的地點名稱（繁體中文，如 ["桃園縣"]）。
        elementName (list[str]): 氣象要素的英文代碼 ("Wx", "MaxT", "MinT", "CI", "PoP")。
        start_time (str): 排程開始時間，格式 "YYYY-MM-DD HH:MM:SS"。
        duration (int): 排程持續時間（分鐘）。
        frequency (int): 排程執行間隔（秒）。
        user_id (str): 代表當前對話使用者的 ID。請在 Prompt 中尋找以 'user_id:' 為標記的字串 (例如 "user_id: <some_value>")，並在呼叫此工具時，將該值帶入本參數，以確保正確識別並對應到使用者。

    Returns:
        str: 顯示排程啟動成功或使用者拒絕啟用排程的訊息 (JSON 字串)。
    """
    # 轉換參數為 list（以防只有單一字串）
    if isinstance(locationName, str):
        locationName = [locationName]
    if isinstance(elementName, str):
        elementName = [elementName]

    # 詢問使用者是否確定要排程
    user_approval = interrupt({
        "question": f"是否要執行對 {locationName} 的氣象要素 {elementName} 的 API 查詢？"
                    f"將在 {start_time} 執行，持續 {duration} 分鐘，每 {frequency} 秒一次？\n"
                    f"如果確定請回答[是]。"
    })
    log.info(f"[User Approval] {user_approval}")

    # 若使用者同意 ("是"/"yes"/"對"/"好")
    if user_approval.lower() in ["是", "yes", "对", "對", "好"]:
        log.info("Initialize scheduler...")

        # 初始化 LLM
        llm = ChatOpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.llm_url,
            model=llm_config.llm_model,
            temperature=llm_config.temperature,
            max_retries=llm_config.max_retries,
            top_p=llm_config.top_p,
            frequency_penalty=llm_config.frequency_penalty,
        )

        scheduler = initialize_scheduler()

        # 轉換 start_time 字串為 datetime，若失敗可考慮用例外處理
        try:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # 若格式不正確，可使用目前時間或回傳錯誤
            start_dt = datetime.now()

        end_dt = start_dt + timedelta(minutes=duration)

        # 建立排程工作
        scheduler.add_job(
            scheduled_weather_task,
            'interval',
            seconds=frequency,
            start_date=start_dt,
            end_date=end_dt,
            args=[llm, user_id, locationName, elementName]
        )

        scheduler.start()  # 非阻塞啟動 BackgroundScheduler
        log.info("Scheduler started successfully.")

        # 回覆使用者
        tool_message = {
            'message': (
                "Successfully initiated a scheduled task for weather API queries. "
                "Results will be periodically pushed to Teams. "
                f"Please do not repeat the scheduled task for the same locationName: {locationName} "
                f"and elementName: {elementName} before {end_dt}."
            )
        }
        return json.dumps(tool_message, ensure_ascii=False)

    else:
        # 使用者拒絕或希望調整參數
        tool_message = {
            'message': (
                "使用者決定不使用排程服務或希望調整參數。"
                f"這是使用者的回覆: {user_approval}，請再次確認。"
            )
        }
        return json.dumps(tool_message, ensure_ascii=False)
