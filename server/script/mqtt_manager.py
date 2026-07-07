import base64
import json
import os
import pathlib
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

        if not all([mqtt_host, mqtt_port, url]):
            raise EnvironmentError(
                "필수 환경 변수 누락 (MQTT_HOST, MQTT_PORT, DATABASE_URL)"
            )

        self.mqtt_host = mqtt_host
        self.mqtt_port = int(mqtt_port)
        self.db = DBManager(url)
        self.queue = queue.Queue()
        self._is_running = False
        self._db_thread = None
        self.on_robot_ephemeral_data = on_robot_ephemeral_data

        self.mqttc = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        print(f"MQTT 연결: {reason_code}")

        for topic, cb in {
            "smartfarm/+/iot/telemetry/sensor/#": self.on_sensor_data,
            "smartfarm/+/iot/telemetry/actuator/#": self.on_device_data,
            "smartfarm/+/robot/telemetry/#": self.on_robot_data,
        }.items():
            client.subscribe(topic)
            client.message_callback_add(topic, cb)

    def on_message(self, client, userdata, msg) -> None:
        print(f"[미처리] {msg.topic}")

    def on_sensor_data(self, client, userdata, msg) -> None:
        topic = msg.topic.split("/")
        payload = json.loads(msg.payload)
        dt = datetime.fromtimestamp(payload["time"]) if "time" in payload else None
        self.queue.put(
            datatype.Sensor(id=int(topic[5]), value=payload["value"], last_signal=dt)
        )

    def on_device_data(self, client, userdata, msg) -> None:
        topic = msg.topic.split("/")
        payload = json.loads(msg.payload)
        dt = datetime.fromtimestamp(payload["time"]) if "time" in payload else None
        self.queue.put(
            datatype.Actuator(id=int(topic[5]), state=payload["state"], last_signal=dt)
        )

    def on_robot_data(self, client, userdata, msg) -> None:
        topic = msg.topic.split("/")
        robot_id = int(topic[4])
        msg_type = topic[5]

        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"robot 데이터 파싱 오류: {e}")
            return

        if msg_type == "log":
            dt = datetime.fromtimestamp(payload["time"]) if "time" in payload else None
            self.queue.put(
                datatype.Robot(id=robot_id, state=payload["data"], last_signal=dt)
            )
        elif msg_type == "get_map":
            self._handle_get_map(robot_id, int(topic[1]))
        elif msg_type in ("state", "battery", "amcl_pose", "robot_mode"):
            if self.on_robot_ephemeral_data:
                self.on_robot_ephemeral_data(
                    robot_id, {"type": msg_type, "payload": payload}
                )

    def _handle_get_map(self, robot_id: int, region_id: int) -> None:
        """로봇의 get_map 텔레메트리 수신 시, DB에서 할당된 지도를 읽어 map_data 커맨드로 발송합니다."""
        try:
            robots, err = self.db.get_current_robot(robot_ids=[robot_id])
            if err or not robots:
                print(f"[Get Map] Robot {robot_id}: DB 조회 실패 또는 로봇 없음")
                return

            map_name = robots[0].map
            if not map_name:
                print(f"[Get Map] Robot {robot_id}: 할당된 지도 없음")
                return

            map_dir = pathlib.Path(__file__).parent / "map"
            pgm_path = map_dir / f"{map_name}.pgm"
            yaml_path = map_dir / f"{map_name}.yaml"

            if not pgm_path.exists() or not yaml_path.exists():
                print(f"[Get Map] Robot {robot_id}: 지도 파일 '{map_name}' 없음")
                return

            pgm_bytes = pgm_path.read_bytes()
            yaml_str = yaml_path.read_text(encoding="utf-8")

            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/map_data"
            payload = {
                "name": map_name,
                "img": base64.b64encode(pgm_bytes).decode("utf-8"),
                "inform": yaml_str,
            }
            self.publish(topic, payload)
            print(f"[Get Map] Robot {robot_id}: '{map_name}' → {topic}")

        except Exception as e:
            print(f"[Get Map Error] Robot {robot_id}: {e}")

    def publish(
        self, topic: str, payload: dict, qos: int = 1, retain: bool = False
    ) -> bool:
        try:
            result = self.mqttc.publish(
                topic, json.dumps(payload), qos=qos, retain=retain
            )
            return result.rc == 0
        except Exception as e:
            print(f"MQTT 발행 오류: {e}")
            return False

    def _db_loop(self) -> None:
        TIMEOUT = 3
        BATCH_SIZE = 10

        while self._is_running:
            batch, deadline = [], time.time() + TIMEOUT

            while len(batch) < BATCH_SIZE:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(self.queue.get(timeout=remaining))
                except queue.Empty:
                    break

            sensors = [i for i in batch if isinstance(i, datatype.Sensor)]
            actuators = [i for i in batch if isinstance(i, datatype.Actuator)]
            robots = [i for i in batch if isinstance(i, datatype.Robot)]

            with self.db.session_scope():
                if sensors:
                    if err := self.db.update_sensor(sensors):
                        print("센서 DB 오류:", err)
                if actuators:
                    if err := self.db.update_actuator(actuators):
                        print("액추에이터 DB 오류:", err)
                if robots:
                    if err := self.db.update_robot(robots):
                        print("로봇 DB 오류:", err)

    def run(self) -> None:
        self._is_running = True
        self._db_thread = threading.Thread(target=self._db_loop, daemon=True)
        self._db_thread.start()
        self.mqttc.connect(self.mqtt_host, self.mqtt_port)
        self.mqttc.loop_start()

    def stop(self) -> None:
        self.mqttc.loop_stop()
        self._is_running = False


if __name__ == "__main__":
    c = Connector()
    try:
        c.run()
    finally:
        c.stop()
