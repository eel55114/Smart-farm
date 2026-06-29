import json
import os
import queue
import threading
import time
from datetime import datetime

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
        self.mqttc.on_message = self.on_message

        self.db = DBManager(url)
        self.queue = queue.Queue()

        self._is_running = False
        self._db_thread = None
        self.on_robot_ephemeral_data = on_robot_ephemeral_data

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"Connected with result code {reason_code}")
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.

        client.subscribe("smartfarm/+/iot/telemetry/sensor/#")
        client.subscribe("smartfarm/+/iot/telemetry/actuator/#")
        client.subscribe("smartfarm/+/robot/telemetry/#")

        self.mqttc.message_callback_add(
            "smartfarm/+/iot/telemetry/sensor/#", self.on_sensor_data
        )
        self.mqttc.message_callback_add(
            "smartfarm/+/iot/telemetry/actuator/#", self.on_device_data
        )
        self.mqttc.message_callback_add(
            "smartfarm/+/robot/telemetry/#", self.on_robot_data
        )

    def on_message(self, client, userdata, msg):
        print(msg.topic + " " + str(msg))

    def on_sensor_data(self, client, userdata, msg):
        topic = msg.topic.split("/")
        # region_id = topic[1]
        sensor_id = topic[5]

        payload = json.loads(msg.payload)
        dt = datetime.fromtimestamp(payload["time"]) if "time" in payload else None

        data = datatype.Sensor(
            id=int(sensor_id),
            value=payload["value"],
            last_signal=dt,  # type: ignore
        )

        self.queue.put(data)

    def on_device_data(self, client, userdata, msg):
        topic = msg.topic.split("/")
        # region_id = topic[1]
        actuator_id = topic[5]

        payload = json.loads(msg.payload)
        dt = datetime.fromtimestamp(payload["time"]) if "time" in payload else None

        data = datatype.Actuator(
            id=int(actuator_id),
            state=payload["state"],
            last_signal=dt,  # type: ignore
        )

        self.queue.put(data)

    def on_robot_data(self, client, userdata, msg):
        topic = msg.topic.split("/")
        # region_id = topic[1]
        robot_id = int(topic[4])
        msg_type = topic[5]

        if msg_type == "state":
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                dt = (
                    datetime.fromtimestamp(payload["time"])
                    if "time" in payload
                    else None
                )

                data = datatype.Robot(
                    id=robot_id,
                    state=payload["state"],
                    last_signal=dt,  # type: ignore
                )

                self.queue.put(data)

                # RDB 저장과 동시에 소켓 실시간 피드백 릴레이 추가
                if self.on_robot_ephemeral_data:
                    self.on_robot_ephemeral_data(
                        robot_id, {"type": "state", "payload": payload}
                    )
            except Exception as e:
                print(f"State 수신 처리 오류: {e}")
        elif msg_type in ["battery_state", "amcl_pose", "robot_mode"]:
            if self.on_robot_ephemeral_data:
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    self.on_robot_ephemeral_data(
                        robot_id, {"type": msg_type, "payload": payload}
                    )
                except Exception as e:
                    print(f"텔레메트리 {msg_type} 릴레이 실패: {e}")

    def publish(self, topic: str, payload: dict, qos=1, retain=False):
        try:
            payload_str = json.dumps(payload)
            result = self.mqttc.publish(topic, payload_str, qos=qos, retain=retain)
            return result.rc == 0
        except Exception as e:
            print(f"MQTT Publish Error: {e}")
            return False

    def _db_loop(self):
        TIMEOUT = 3
        BATCH_SIZE = 10

        while self._is_running:
            batch = []
            deadline = time.time() + TIMEOUT

            while len(batch) <= BATCH_SIZE:
                limit = deadline - time.time()

                if limit <= 0:
                    break
                try:
                    data = self.queue.get(timeout=limit)
                    batch.append(data)
                except queue.Empty:
                    break

            sensors = [i for i in batch if isinstance(i, datatype.Sensor)]
            actuators = [i for i in batch if isinstance(i, datatype.Actuator)]
            robots = [i for i in batch if isinstance(i, datatype.Robot)]

            with self.db.session_scope():
                if len(sensors):
                    err = self.db.update_sensor(sensors)
                    if err:
                        print("센서 DB 업데이트 중 오류 발생:", err)
                if len(actuators):
                    err = self.db.update_actuator(actuators)
                    if err:
                        print("액추에이터 DB 업데이트 중 오류 발생:", err)
                if len(robots):
                    err = self.db.update_robot(robots)
                    if err:
                        print("로봇 DB 업데이트 중 오류 발생:", err)

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
