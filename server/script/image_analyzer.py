import base64
import json
import os
import queue
import threading

import dotenv
import paho.mqtt.client as mqtt
from db_manager import datatype
from db_manager.manager import DBManager
from paho.mqtt.enums import CallbackAPIVersion


class Connector:
    def __init__(self, on_robot_ephemeral_data=None) -> None:
        dotenv.load_dotenv()

        mqtt_host = os.getenv("MQTT_HOST")
        mqtt_port = os.getenv("MQTT_PORT")
        url = os.getenv("DATABASE_URL")

        try:
            assert mqtt_host is not None
            assert mqtt_port is not None
            assert url is not None
        except AssertionError:
            print("환경 변수 인식 실패")
            return

        self.mqtt_host = mqtt_host
        self.mqtt_port = int(mqtt_port)
        self.mqttc = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect

        self.db = DBManager(url)
        self.queue = queue.Queue()

        self._is_running = False
        self._db_thread = None
        self.on_robot_ephemeral_data = on_robot_ephemeral_data

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"Connected with result code {reason_code}")

        client.subscribe("smartfarm/+/plant/img/#")

        self.mqttc.message_callback_add(
            "smartfarm/+/plant/img/captured_img", self.on_plnat_img
        )

    def on_plnat_img(self, client, userdata, msg):
        topic = msg.topic.split("/")

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            plant_id = int(payload["id"])
            time = int(payload["time"])
            img_base64 = payload["img"]

        except json.JSONDecodeError:
            print("MQTT Payload JSON 파싱 에러")
            return
        except KeyError as e:
            print(e)
            return

        try:
            # 이미지 바이너리
            img_bytes = base64.b64decode(img_base64)
        except Exception as e:
            print(f"Base64 디코딩 실패: {e}")
            return

        # @@@ 여기에 분석 코드를 작성 @@@

        # 분석 결과 더미 데이터(코드 완성시 삭제하세요)
        maturity = 0
        is_disease = False

        data = datatype.Plant(id=plant_id, maturity=maturity, is_disease=is_disease)

        self.queue.put(data)

    def _db_loop(self):
        while self._is_running:
            plant = self.queue.get()

            with self.db.session_scope():
                err = self.db.update_plant([plant])
                if err:
                    print("작물 정보 업데이트 중 오류 발생:", err)

    def run(self):
        self._is_running = True
        self._db_thread = threading.Thread(target=self._db_loop, daemon=True)
        self._db_thread.start()

        self.mqttc.connect(self.mqtt_host, self.mqtt_port)
        self.mqttc.loop_start()

    def stop(self):
        self.mqttc.loop_stop()
        self._is_running = False


if __name__ == "__main__":
    try:
        c = Connector()
        c.run()
    finally:
        c.stop()
