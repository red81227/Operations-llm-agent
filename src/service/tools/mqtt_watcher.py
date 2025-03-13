"""
Module for monitoring device status through MQTT messages.

This module provides functionality to watch device status via MQTT protocol,
analyze received messages using LLM, and send notifications to users.
"""
import json
import queue
import threading
import traceback
from typing import Annotated, Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
import functools

from langchain_core.tools import tool, InjectedToolArg
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI
from langchain_core.runnables.config import RunnableConfig
from config.project_setting import qwen_14b_awq_llm_config, bot_config, service_config, mqtt_config
from config.logger_setting import log
from src.operator.mqtt import MQTTService
from src.util.function_utils import send_message_to_teams, extract_direct_answer

# Message templates
LLM_PROMPT_TEMPLATE = """
你是一位專業的維運工程師，請從以下上傳訊息中擷取出與指定 serial_number 相關的訊息內容。
請僅針對該 serial_number 對應的訊息，完成使用者需求。
若訊息中無此 serial_number 的相關資訊，請直接回應「no message」。

使用者需求: {required}
serial_number: {serial_number}
訊息: {message}
"""

class DeviceMqttWatcher:
    """
    Watches device status via MQTT and processes messages with LLM analysis.
    
    This class manages a thread pool that consumes MQTT messages from a queue,
    processes them using LLM analysis, and sends notifications to users.
    """

    def __init__(self):
        """Initialize the DeviceMqttWatcher with a message queue and threading setup."""
        self._mqtt_queue = queue.Queue(maxsize=service_config.mqtt_queue_size)
        self._thread_list: List[threading.Thread] = []
        self._process = True
        self._shutdown_event = threading.Event()
        self._active_services: Dict[str, Any] = {}  # Track active MQTT services
        self._services_lock = threading.Lock()
        
        # Initialize LLM
        self._init_llm()

    def _init_llm(self) -> None:
        """Initialize the LLM model for message analysis."""
        self.llm = ChatOpenAI(
            api_key=qwen_14b_awq_llm_config.api_key,
            base_url=qwen_14b_awq_llm_config.llm_url,
            model=qwen_14b_awq_llm_config.llm_model,
            temperature=qwen_14b_awq_llm_config.temperature,
            max_retries=qwen_14b_awq_llm_config.max_retries,
            frequency_penalty=qwen_14b_awq_llm_config.frequency_penalty,
        )

    def start_thread(self) -> None:
        """
        Start multiple worker threads to consume tasks from the MQTT message queue.
        
        Each thread runs until shutdown is requested.
        """
        if self._thread_list:
            log.warning("Worker threads already started")
            return
            
        thread_count = max(1, service_config.mqtt_thread_size)
        
        for i in range(thread_count):
            thread = threading.Thread(
                target=self.consume_mqtt_task,
                name=f"MQTTConsumer-{i}",
                daemon=True
            )
            self._thread_list.append(thread)
            thread.start()
            
        log.info(f"Started {thread_count} threads to consume MQTT tasks")

    def shutdown(self) -> None:
        """
        Safely shutdown all worker threads and MQTT connections.
        
        This ensures clean termination of all resources.
        """
        log.info("Shutting down MQTT watcher...")
        self._process = False
        self._shutdown_event.set()
        
        # Stop all active MQTT services
        with self._services_lock:
            for service_id, service_info in self._active_services.items():
                service = service_info.get('service')
                if service:
                    log.info(f"Stopping MQTT service {service_id}")
                    service.stop()
            self._active_services.clear()
        
        # Wait for all threads to complete
        for thread in self._thread_list:
            if thread.is_alive():
                thread.join(timeout=5.0)
                
        log.info("MQTT watcher shutdown complete")

    def consume_mqtt_task(self) -> None:
        """
        Continuously consume and process tasks from the MQTT message queue.
        
        This method runs in a dedicated thread and processes messages until shutdown.
        """
        while self._process and not self._shutdown_event.is_set():
            try:
                # Use timeout to allow checking shutdown flag periodically
                mqtt_task = self._mqtt_queue.get(timeout=1.0)
                self._process_mqtt_task(mqtt_task)
                self._mqtt_queue.task_done()
                
            except queue.Empty:
                continue  # Just retry if queue is empty
                
            except Exception as e:
                log.error(f"Error processing MQTT task: {str(e)}")
                log.error(traceback.format_exc())

    def _process_mqtt_task(self, mqtt_task: Dict[str, Any]) -> None:
        """
        Process a single MQTT task with LLM analysis.
        
        Args:
            mqtt_task: Dictionary containing MQTT message and metadata
        """
        try:
            message = mqtt_task.get('message')
            topic = mqtt_task.get('topic')
            user_id = mqtt_task.get('user_id')
            serial_number = mqtt_task.get('serial_number')
            required = mqtt_task.get('required')
            
            # Skip processing if any key fields are missing
            if not all([message, user_id, serial_number, required]):
                log.warning(f"Incomplete MQTT task: {mqtt_task}")
                return

            # Create LLM prompt with the task information
            prompt = LLM_PROMPT_TEMPLATE.format(
                required=required,
                serial_number=serial_number,
                message=message
            )

            # Invoke LLM analysis
            log.debug(f"Analyzing MQTT message for serial_number={serial_number}")
            llm_response = self.llm.invoke(prompt)
            direct_answer = extract_direct_answer(llm_response.content)
            
            # Only send notifications if there's relevant content
            if direct_answer and "no message" not in direct_answer.lower():
                # Format message with metadata
                formatted_message = self._format_notification_message(
                    direct_answer, topic, message, serial_number
                )
                
                # Send notification
                log.info(f"Sending MQTT notification to user {user_id}")
                send_message_to_teams(bot_config.node_server_url, user_id, message=formatted_message)
            else:
                log.debug(f"No relevant information for serial_number={serial_number}")
                
        except Exception as e:
            log.error(f"LLM analysis failed: {str(e)}")
            log.error(traceback.format_exc())

    def _format_notification_message(self, analysis: str, topic: str, 
                                    raw_message: str, serial_number: str) -> str:
        """
        Format notification message with analysis results and metadata.
        
        Args:
            analysis: LLM analysis result
            topic: MQTT topic
            raw_message: Original MQTT message
            serial_number: Device serial number
            
        Returns:
            Formatted notification message
        """
        # Try to parse raw message as JSON for better formatting
        try:
            message_data = json.loads(raw_message)
            formatted_raw = json.dumps(message_data, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            formatted_raw = raw_message
            
        return (
            f"📡 設備監測通知 - {serial_number}\n\n"
            f"📊 分析結果:\n{analysis}\n\n"
            f"📋 詳細資訊:\n"
            f"- 主題: {topic}\n"
            f"- 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"📝 原始訊息:\n```\n{formatted_raw}\n"
        )

    def produce_mqtt_task(self, message: str, topic: str, user_id: str, serial_number: str, required: str) -> None:
        """
        Add MQTT message to the queue.

        Parameters:
            message (str): MQTT message content.
            topic (str): MQTT message topic.
            user_id (str): User ID.
            serial_number (str): Device serial number.
            required (str): User requirement.
        """
        mqtt_task = {
            'message': message,
            'topic': topic,
            'user_id': user_id,
            'serial_number': serial_number,
            'required': required
        }

        if self._mqtt_queue.full():
            log.warning(f"Queue is full, size: {self._mqtt_queue.qsize()}")
        else:
            self._mqtt_queue.put(mqtt_task)

device_mqtt_watcher = DeviceMqttWatcher()
device_mqtt_watcher.start_thread()

def custom_on_message(client, userdata, msg, required, user_id, serial_number):
    try:
        log.info("Received message: %s", msg.payload)
        log_msg = msg.payload.decode('utf-8')
        topic = msg.topic

        mqtt_task = {
            'message': log_msg,
            'topic': topic,
            'user_id': user_id,
            'serial_number': serial_number,
            'required': required
        }
        device_mqtt_watcher.produce_mqtt_task(**mqtt_task)
    except Exception as e:
        return f"Custom on_message processing failed: {e}"


@tool
def watch_device_status_by_mqtt(
    required: Annotated[str, InjectedToolArg],
    config: RunnableConfig,
    duration: Annotated[int, InjectedToolArg]=mqtt_config.default_duration_seconds
) -> str:
    """
    此函數啟動一個排程服務，持續監聽指定設備的 MQTT 訊息。服務的運行時間由 duration 參數決定，單位為秒，預設值為 3600 秒（即 1 小時）。在監聽期間，服務會根據接收到的訊息內容，向指定的 user_id 發送推播通知。

        參數說明：
        required (str):必填，使用者的需求
        duration (int)：監聽服務的持續時間，單位為秒。預設值為 3600 秒。
        回傳值：

        成功時，回傳操作成功的訊息字串。
        失敗時，回傳包含錯誤描述的字串。
        此函數適用於需要在特定時間段內監控設備狀態，並根據設備的 MQTT 訊息即時向使用者推送通知的情境。
    """
    user_id =  str(config["configurable"]["user_id"])
    serial_number = interrupt({
        "question": (
            f"是否要監控設備MQTT資訊，並完成下面需求: **{required}**\n"
            f"是的話請提供正確的監控設備serial_number，\n"
            f"**請直接回目標serial_number，不要外加其他文字** !!!\n"
            f"不想使用監控設備MQTT請回答[否]"
        )
    })

    log.info(f"User provided serial number: {serial_number}")

    if serial_number == "no" or serial_number == "否":
        return json.dumps({
                'status': '沒有執行工具，使用者希望對工具執行做調整',
                'human_respond': serial_number,
            }, ensure_ascii=False)
    
    partial_on_message = functools.partial(custom_on_message,
                                 required=required,
                                 user_id=user_id,
                                 serial_number=serial_number)
    
    
    try:
        mqtt_service = MQTTService(
            broker_host=mqtt_config.broker_host,
            broker_port=mqtt_config.broker_port,
            topic=mqtt_config.topic,
            username=mqtt_config.username,
            password=mqtt_config.password,
            log_queue=device_mqtt_watcher._mqtt_queue,
            on_message_callback=partial_on_message
        )
        mqtt_service.start()

        stop_timer = threading.Timer(duration, mqtt_service.stop)
        stop_timer.start()
        log.info(f"已啟動監控設備MQTT資訊，持續時間 {duration} 秒")
        #用當下時間加上持續時間，轉換成時間格式
        end_time = (datetime.now() + timedelta(seconds=duration)).strftime('%Y-%m-%d %H:%M:%S')
        return json.dumps({
                'status': 'success',
                'message': f"使用者: {user_id} 已對設備 {serial_number} 啟動監控設備MQTT資訊，持續時間 {duration} 秒，{end_time}前不要重複執行",
            }, ensure_ascii=False)
    except Exception as e:
        log.info(f"Error: {e}")
        return f"error: {e}"

