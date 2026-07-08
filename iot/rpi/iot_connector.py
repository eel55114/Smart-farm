import json
import os
import socket
import time

import dotenv
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


def msg_packer(**kwargs):
    return json.dumps(kwargs)


class Connector:
    def __init__(self) -> None:
        dotenv.load_dotenv()

        mqtt_host = os.getenv("MQTT_HOST")
        mqtt_port = os.getenv("MQTT_PORT")
        bt_addr = os.getenv("BT_ADDR")
        bt_port = os.getenv("BT_PORT")
        region_id = os.getenv("REGION_ID")

        try:
            assert mqtt_host is not None
            assert mqtt_port is not None
            assert bt_addr is not None
            assert bt_port is not None
            assert region_id is not None
        except AssertionError:
            raise ValueError("환경 변수 인식 실패")

        self.MQTT_HOST = mqtt_host
        self.MQTT_PORT = int(mqtt_port)

        self.BT_ADDR = bt_addr
        self.BT_PORT = int(bt_port)

        self.REGION_ID = int(region_id)

        self.TOPIC_PREFIX = {
            "sensor_telemetry": f"smartfarm/{self.REGION_ID}/iot/telemetry/sensor/",
            "actuator_command": f"smartfarm/{self.REGION_ID}/iot/command/actuator/",
            "actuator_telemetry": f"smartfarm/{self.REGION_ID}/iot/telemetry/actuator/",
        }

        self.bt_sock = self.init_bluetooth_socket()

        self.client = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def init_bluetooth_socket(self):
        while True:
            try:
                print("블루투스 연결 시도 중")
                sock = socket.socket(
                    socket.AF_BLUETOOTH,  # type: ignore
                    socket.SOCK_STREAM,
                    socket.BTPROTO_RFCOMM,  # type: ignore
                )
                sock.connect((self.BT_ADDR, self.BT_PORT))
                sock.setblocking(False)
                print("블루투스 연결 성공")
                return sock
            except Exception as e:
                print(f"블루투스 연결 실패 ({e})")
                time.sleep(5)

    def run(self):

        self.client.connect(self.MQTT_HOST, self.MQTT_PORT, 60)
        self.client.loop_start()

        buffer = ""
        try:
            while True:
                if self.bt_sock is None:
                    self.bt_sock = self.init_bluetooth_socket()
                    continue

                try:
                    data = self.bt_sock.recv(1024).decode("utf-8")
                    if data:
                        buffer += data
                        if "\n" in buffer:
                            lines = buffer.split("\n")
                            for line in lines[:-1]:
                                self.send_message(line)

                            buffer = lines[-1]
                    else:
                        self.bt_sock = None

                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"에러 발생: {e}")
                    if self.bt_sock:
                        self.bt_sock.close()
                        self.bt_sock = None

                time.sleep(0.05)
        finally:
            if self.bt_sock:
                self.bt_sock.close()
            self.client.loop_stop()
            self.client.disconnect()

    def send_message(self, msg):
        device_id, device_type, *value = msg.split("+")
        payload = ""
        topic = ""

        # 센서
        if device_type == "0":
            topic = f"{self.TOPIC_PREFIX['sensor_telemetry']}{device_id}"

            payload = msg_packer(time=time.time(), value=value[0])

        # 디바이스
        # elif device_type == "1":
        #     topic = f"{self.TOPIC_PREFIX['actuator_telemetry']}{device_id}"

        #     payload = msg_packer(time=time.time(), state=value[0])

        if payload:
            self.client.publish(topic, payload, 1, True)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(self.TOPIC_PREFIX["actuator_command"] + "#")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = json.loads(msg.payload.decode("utf-8"))

        actuator_id = topic.split("/")[-1]

        try:
            [float(value) for value in payload["data"].split("+")]
        except:
            print(f"유효하지 않은 형식: {payload}")

        try:
            if payload and self.bt_sock:
                msg = f"{actuator_id}+1+{payload}".encode("utf-8")
                self.bt_sock.send(msg)
        except Exception as e:
            print(f"블루투스 데이터 전송 실패: {e}")


if __name__ == "__main__":
    c = Connector()
    c.run()
