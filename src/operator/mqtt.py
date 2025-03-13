import paho.mqtt.client as mqtt
import threading
from config.logger_setting import log

import queue


class MQTTService:
    def __init__(self, broker_host, broker_port, topic, username, password, log_queue, on_message_callback=None):
        """
        初始化 MQTTService。

        Parameters:
            broker_host (str): MQTT broker 的主機地址。
            broker_port (int): MQTT broker 的端口號。
            topic (str): 要訂閱的主題。
            username (str): MQTT broker 的用戶名。
            password (str): MQTT broker 的密碼。
            log_queue (queue.Queue): 用於存放接收到的消息的隊列。
            on_message_callback (callable, optional): 自定義的 on_message 回調函數。
        """
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = topic
        self.log_queue = log_queue
        self.on_message_callback = on_message_callback
        self.client = mqtt.Client()
        self.client.username_pw_set(username, password)
        self.client.tls_set()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self._loop_thread_started = False
        self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        """
        當成功連接到 MQTT broker 時的回調函數。

        Parameters:
            client: MQTT 客戶端實例。
            userdata: 用戶自定義數據（未使用）。
            flags: 連接標誌。
            rc: 連接結果代碼。
        """
        print(f"MQTT Connected with result code {rc}")
        if rc == 0:
            client.subscribe(self.topic)
        else:
            print("Failed to connect to MQTT broker")


    def on_message(self, client, userdata, msg):
        """
        當接收到消息時的回調函數。

        Parameters:
            client: MQTT 客戶端實例。
            userdata: 用戶自定義數據（未使用）。
            msg: 接收到的 MQTT 消息對象。
        """
        if self.on_message_callback:
            self.on_message_callback(client, userdata, msg)
        else:
            try:
                log_msg = msg.payload.decode('utf-8')
                self.log_queue.put(log_msg)
            except Exception as e:
                log.info(f"Failed to process message: {e}")

    def start(self):
        if not self._loop_thread_started:
            self.client.connect(self.broker_host, self.broker_port, 60)
            # 啟動 MQTT 網路執行線，開始監聽
            self.client.loop_start()  # 背景執行線處理 MQTT
            self._loop_thread_started = True
            log.info("MQTT 監聽服務已啟動")

    def stop(self):
        if self._loop_thread_started:
            self.client.loop_stop()   # 停止背景執行線
            self.client.disconnect()
            self._loop_thread_started = False
            self.connected = False
            log.info("MQTT 監聽服務已停止")

    def is_running(self):
        return self._loop_thread_started