import json
import queue
import threading
import traceback
from typing import Annotated, Any, Dict, Union
import uuid
from config.project_setting import deepseek_llm_config, bot_config, service_config
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool, InjectedToolArg
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt
from config.logger_setting import log
from src.operator.mqtt import MQTTService
from src.util.function_utils import send_message_to_teams
from functools import partial

class DeviceMqttWatcher:
    def __init__(self):
        """
        Initialize DeviceMqttWatcher to handle messages received from MQTT and consume them via multithreading.
        """
        self._mqtt_queue = queue.Queue(maxsize=service_config.mqtt_queue_size)
        self._thread_list = []
        self._process = True
        self.deepseek_llm = ChatOpenAI(
            api_key=deepseek_llm_config.api_key,
            base_url=deepseek_llm_config.llm_url,
            model=deepseek_llm_config.llm_model,
            temperature=deepseek_llm_config.temperature,
            max_retries=deepseek_llm_config.max_retries,
            frequency_penalty=deepseek_llm_config.frequency_penalty,
        )

    def start_thread(self):
        """
        Start multiple threads to consume tasks from the MQTT message queue.
        """
        for _ in range(service_config.mqtt_thread_size):
            thread = threading.Thread(target=self.consume_mqtt_task)
            thread.daemon = True
            self._thread_list.append(thread)
            thread.start()
        log.info(f"Started {service_config.mqtt_thread_size} threads to consume MQTT tasks")

    def consume_mqtt_task(self):
        """
        Consume tasks from the MQTT message queue and process them.
        """
        while self._process:
            try:
                mqtt_task = self._mqtt_queue.get(timeout=1)  # Retry if no new data within one second
                self.llm_read_mqtt(mqtt_task)
            except queue.Empty:
                continue
            except Exception:
                log.error(traceback.format_exc())

    def produce_mqtt_task(self, message: str, topic: str, user_id: str, serial_number: str):
        """
        Add MQTT message to the queue.

        Parameters:
            message (str): MQTT message content.
            topic (str): MQTT message topic.
            user_id (str): User ID.
            serial_number (str): Device serial number.
        """
        mqtt_task = {
            'message': message,
            'topic': topic,
            'user_id': user_id,
            'serial_number': serial_number
        }

        if self._mqtt_queue.full():
            log.warning(f"Queue is full, size: {self._mqtt_queue.qsize()}")
        else:
            self._mqtt_queue.put(mqtt_task)

    def llm_read_mqtt(self, mqtt_task: dict):
        """
        Analyze MQTT message using LLM and perform actions based on the result.

        Parameters:
            mqtt_task (dict): Task containing MQTT message.
        """
        try:
            message = mqtt_task.get('message')
            topic = mqtt_task.get('topic')
            user_id = mqtt_task.get('user_id')
            serial_number = mqtt_task.get('serial_number')

            prompt = f"""你是一個專業的維運工程師，message是所有serial_number的機器的上傳訊息，幫我擷取出所有對應serial_number的訊息，
            如果不是這個serial_number的設備訊息，請回答 \"no message\"。
            serial_number: {serial_number}
            message：{message}"""

            llm_response = self.deepseek_llm.invoke(prompt)
            decision = llm_response.content.strip()

            if "no message" not in decision:
                llm_message = f"{decision}\ntopic: {topic}, message: {message}"
                send_message_to_teams(bot_config.node_server_url, user_id, message=llm_message)

        except Exception as e:
            log.error(f"LLM analysis failed: {e}")

device_mqtt_watcher = DeviceMqttWatcher()
device_mqtt_watcher.start_thread()

def custom_on_message(client, userdata, msg, user_id, serial_number):
    try:
        log_msg = msg.payload.decode('utf-8')
        topic = msg.topic

        mqtt_task = {
            'message': log_msg,
            'topic': topic,
            'user_id': user_id,
            'serial_number': serial_number
        }
        device_mqtt_watcher.produce_mqtt_task(**mqtt_task)
    except Exception as e:
        return f"Custom on_message processing failed: {e}"
    
@tool
def watch_device_status_by_mqtt(
    duration: Annotated[int, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg]
) -> Union[str, Dict[str, Any]]:
    """
    Start a tool to monitor device status via MQTT.

    Parameters:
        duration (int): Duration of monitoring in seconds.
        user_id (str): User ID for message push notifications.

    Returns:
        Union[str, Dict[str, Any]]: Success message or error description.
    """
    serial_number = interrupt({
        "question": """是否要監控設備MQTT資訊，
                    是的話請提供正確的監控設備serial_number，
                    請直接回目標serial_number，不要外加其他文字 !!!
                    不想使用監控設備MQTT請回答[否]"""
    })

    log.info(f"User provided serial number: {serial_number}")

    if serial_number == "no" or serial_number == "否":
        return {"message": "User cancelled the MQTT operation, maybe user needs to do something else, MQTT monitoring task aborted."}
    
    partial_on_message = partial(custom_on_message,
                                 user_id=user_id,
                                 serial_number=serial_number)
    
    
    try:
        mqtt_service = MQTTService(
            broker_host="mqttd.fetnet.net",
            broker_port=8883,
            topic="evcharging/v2/telemetry/statusNotification/#",
            username="evcharging_hsinchu",
            password="Eft8vhDP",
            log_queue=device_mqtt_watcher._mqtt_queue,
            on_message_callback=partial_on_message
        )
        mqtt_service.start()

        stop_timer = threading.Timer(duration, mqtt_service.stop)
        stop_timer.start()

        return f"已啟動監控設備MQTT資訊，持續時間 {duration} 秒"
    except Exception as e:
        return {"error": str(e)}
    
