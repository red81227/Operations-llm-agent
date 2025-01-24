import paho.mqtt.client as mqtt
import threading
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
        self.client = mqtt.Client()
        self.client.username_pw_set(username=username, password=password)
        self.on_message_callback = on_message_callback

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
                print(f"Received message: {log_msg}")
                self.log_queue.put(log_msg)
            except Exception as e:
                print(f"Failed to process message: {e}")

    def start(self):
        """
        開始 MQTT 服務，包括連接和訂閱主題。
        """
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker_host, self.broker_port, 60)

        thread = threading.Thread(target=self.client.loop_forever, daemon=True)
        thread.start()
        print("MQTTService started and listening...")

    def stop(self):
        """
        停止 MQTT 服務，包括斷開連接。
        """
        self.client.disconnect()
        print("MQTTService stopped.")