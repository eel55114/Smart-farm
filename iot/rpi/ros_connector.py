import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Final

import dotenv
import map_converter
import paho.mqtt.client as mqtt
import rclpy
from nav_msgs.msg import OccupancyGrid
from paho.mqtt.enums import CallbackAPIVersion
from rclpy.node import Node
from rosidl_runtime_py.set_message import set_message_fields
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


def msg_packer(**kwargs) -> str:
    return json.dumps(kwargs)


class Connector(Node):
    """MQTT-ROS 브릿지 노드 클래스.

    이 클래스는 MQTT 브로커(스마트 팜 서버)와 ROS 2 노드 그래프(로봇 센서/컨트롤러)
    사이에서 메시지를 중계하는 브릿지 역할을 수행합니다.

    Attributes:
        MQTT_HOST (str): MQTT 브로커의 호스트명 또는 IP 주소.
        MQTT_PORT (int): MQTT 브로커의 포트 번호.
        REGION_ID (int): 스마트 팜 구역(Region) 식별자.
        ROBOT_ID (int): 로봇 식별자.
        TOPIC_PREFIX (dict): 로봇 텔레메트리 및 제어 명령 토픽의 접두사 사전.
        map_dir_path (Path): 지도 파일들이 저장되는 로컬 디렉토리 경로.
        mqtt (mqtt.Client): Paho MQTT 클라이언트 인스턴스.
        robot_mode_pub (Publisher): 로봇 모드 제어를 위한 ROS 2 퍼블리셔.
        remote_control_pub (Publisher): 로봇 수동 조작을 위한 ROS 2 퍼블리셔.
        map_pub (Publisher): OccupancyGrid 지도 발행을 위한 ROS 2 퍼블리셔.
        state_sub (Subscription): 로봇 상태 수신을 위한 ROS 2 서브스크립션.
    """

    def __init__(self, map_dir_path: str = "") -> None:
        """
        Args:
            map_dir_path: 지도를 저장하고 불러올 커스텀 디렉토리 경로.
                비어 있는 경우, 프로젝트 경로 내의 기본 'map' 디렉토리를 탐색

        Raises:
            ValueError: 필수 환경 변수가 누락되었거나,
                지도 디렉토리를 찾을 수 없거나 유효하지 않은 경우 발생
        """
        super().__init__("mqtt_ros_bridge_node")

        dotenv.load_dotenv()

        mqtt_host = os.getenv("MQTT_HOST")
        mqtt_port = os.getenv("MQTT_PORT")
        region_id = os.getenv("REGION_ID")
        robot_id = os.getenv("ROBOT_ID")

        try:
            assert mqtt_host is not None
            assert mqtt_port is not None
            assert region_id is not None
            assert robot_id is not None
        except AssertionError:
            self.get_logger().error("환경 변수 인식 실패")
            raise ValueError("환경 변수 인식 실패")

        self.MQTT_HOST: Final = mqtt_host
        self.MQTT_PORT: Final = int(mqtt_port)
        self.REGION_ID: Final = int(region_id)
        self.ROBOT_ID: Final = int(robot_id)

        self.TOPIC_PREFIX: Final = {
            "robot_telemetry": f"smartfarm/{self.REGION_ID}/robot/telemetry/{robot_id}/",
            "robot_command": f"smartfarm/{self.REGION_ID}/robot/command/{robot_id}/",
            "plant_img": f"smartfarm/{self.REGION_ID}/plant/img/",
        }

        if map_dir_path == "":
            self.map_dir_path = Path(__file__).parent / "map"
            if not self.map_dir_path.is_dir():
                self.map_dir_path = self.map_dir_path.parent.parent / "map"
                if not self.map_dir_path.is_dir():
                    raise ValueError("Cannot find directory 'map'")
        else:
            self.map_dir_path = Path(map_dir_path)
            if not self.map_dir_path.is_dir():
                raise ValueError(f"Invalid directory path: {map_dir_path}")

        self.mqtt = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self.on_connect

        self.robot_mode_pub = self.create_publisher(String, "/robot_mode", 10)
        self.remote_control_pub = self.create_publisher(String, "/remote_control", 10)
        self.map_pub = self.create_publisher(OccupancyGrid, "/map", 10)

        self.state_sub = self.create_subscription(
            String, "/robot_state", self.robot_state_callback, 10
        )

        self.captured_sub = self.create_subscription(
            CompressedImage, "/captured_image/compressed", self.plant_img_callback, 1
        )

    def plant_img_callback(self, msg: CompressedImage) -> None:
        """ROS로부터 촬영한 작물 이미지를

        수신된 상태 데이터를 MQTT 브로커의 'state' 토픽으로 발행

        Args:
            msg: 로봇의 현재 상태 정보를 담고 있는 ROS CompressedImage 메시지 객체.
        """

        frame_id_str = msg.header.frame_id
        match = re.search(r"Marker ID:\s*(\d+)", frame_id_str)
        marker_id = int(match.group(1)) if match else 1

        now = time.time()

        topic = self.TOPIC_PREFIX["plant_img"]
        self.mqtt.publish(topic, msg.data)

        self.get_logger().info(f"Marker {marker_id} 이미지 송신")

    def robot_state_callback(self, msg: String) -> None:
        """ROS로부터 로봇 상태 텔레메트리를 수신했을 때 호출되는 콜백 메서드

        수신된 상태 데이터를 MQTT 브로커의 'state' 토픽으로 발행

        Args:
            msg: 로봇의 현재 상태 정보를 담고 있는 ROS String 메시지 객체.
        """
        topic = self.TOPIC_PREFIX["robot_telemetry"] + "state"
        self.mqtt.publish(topic, msg.data)
        self.get_logger().info(f"로봇 상태 전송: {msg.data}")

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        """MQTT 클라이언트가 브로커에 연결되었을 때 호출되는 콜백 메서드.

        로봇 제어 명령 토픽을 구독하고, 특정 토픽용 콜백 함수들을 등록.

        Args:
            client: MQTT 클라이언트 인스턴스.
            userdata: 콜백에 전달되는 사용자 정의 데이터.
            flags: 브로커가 보낸 연결 응답 플래그.
            reason_code: 연결 결과 코드.
            properties: MQTT 속성 정보.
        """
        if reason_code == 0:
            self.get_logger().info("MQTT Connected successfully.")

            client.subscribe(self.TOPIC_PREFIX["robot_command"] + "#")

            client.message_callback_add(
                self.TOPIC_PREFIX["robot_command"] + "set_map", self.on_set_map_message
            )
            client.message_callback_add(
                self.TOPIC_PREFIX["robot_command"] + "map_data",
                self.on_map_data_message,
            )
            client.message_callback_add(
                self.TOPIC_PREFIX["robot_command"] + "#", self.on_robot_message
            )
        else:
            self.get_logger().error(f"MQTT Connection failed: {reason_code}")

    def on_set_map_message(self, client, userdata, msg) -> None:
        """'set_map' MQTT 명령을 처리

        로컬 지도 파일이 요청된 지도 이름 및 해시값과 일치하는지 확인.
        일치하는 경우 ROS로 지도를 발행하고, 일치하지 않는 경우 서버에 지도 파일을 요청

        Args:
            client: MQTT client 인스턴스.
            userdata: 콜백에 전달되는 사용자 정의 데이터.
            msg: 지도 명령 페이로드를 포함하는 MQTT 메시지 객체.
        """
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            map_name = payload["name"]
            img_hash = payload["img_hash"]
            inform_hash = payload["inform_hash"]

        except json.JSONDecodeError:
            self.get_logger().error("MQTT Payload JSON 파싱 에러")
            return
        except KeyError as e:
            self.get_logger().error(e)
            return

        self.get_logger().info(f"맵 설정 명령 수신: {map_name}")

        img_file = (self.map_dir_path / map_name).with_suffix(".pgm")
        inform_file = (self.map_dir_path / map_name).with_suffix(".yaml")

        request_img = True
        request_inform = True

        if img_file.is_file() and inform_file.is_file():
            img_file_data = img_file.read_bytes()
            inform_file_data = inform_file.read_bytes()

            img_file_hash = hashlib.sha256(img_file_data).hexdigest()
            inform_file_hash = hashlib.sha256(inform_file_data).hexdigest()

            if img_hash == img_file_hash and inform_hash == inform_file_hash:
                mtime = int(max(img_file.stat().st_mtime, inform_file.stat().st_mtime))
                self.publish_map(map_name, mtime, img_file_data, inform_file_data)
                self.get_logger().info(f"맵 설정 완료: {map_name}")
                return

            else:
                request_img = True if img_hash != img_file_hash else False
                request_inform = True if inform_hash != inform_file_hash else False

        msg = msg_packer(name=map_name, img=request_img, inform=request_inform)

        client.publish(self.TOPIC_PREFIX["robot_telemetry"] + "get_map", msg)

        self.get_logger().info(f"맵 데이터 전송 요청: {map_name}")

    def publish_map(
        self, name: str, mtime: int, img: bytes, inform: str | bytes
    ) -> None:
        """지도 파일들을 ROS OccupancyGrid 메시지로 변환하여 발행

        Args:
            name: 지도의 이름.
            mtime: 지도 파일의 최종 수정 시간 타임스탬프.
            img: PGM 이미지 파일의 바이너리 데이터.
            inform: YAML 형식의 지도 메타데이터 문자열 또는 바이트 데이터.
        """
        values = map_converter.tuple_to_msg(name, mtime, img, inform)

        ros_msg = OccupancyGrid()
        set_message_fields(ros_msg, values)

        self.map_pub.publish(ros_msg)

    def on_map_data_message(self, client, userdata, msg) -> None:
        """'map_data' MQTT 명령을 처리.

        Base64로 인코딩된 이미지 데이터를 디코딩하고, 이미지 및 YAML 파일을 로컬에 저장한 뒤
        새로운 지도를 ROS로 발행.

        Args:
            client: MQTT 클라이언트 인스턴스.
            userdata: 콜백에 전달되는 사용자 정의 데이터.
            msg: 지도 파일 페이로드를 포함하는 MQTT 메시지 객체.
        """
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            map_name = payload["name"]
            img_base64 = payload["img"]
            inform_string = payload["inform"]

        except json.JSONDecodeError:
            self.get_logger().error("MQTT Payload JSON 파싱 에러")
            return
        except KeyError as e:
            self.get_logger().error(e)
            return

        try:
            img_bytes = base64.b64decode(img_base64)
        except Exception as e:
            self.get_logger().error(f"Base64 디코딩 실패: {e}")
            return

        map_file = (self.map_dir_path / map_name).with_suffix(".pgm")
        inform_file = (self.map_dir_path / map_name).with_suffix(".yaml")

        map_file.write_bytes(img_bytes)
        inform_file.write_text(inform_string)

        mtime = int(time.time())
        self.publish_map(map_name, mtime, img_bytes, inform_string)

    def on_robot_message(self, client, userdata, msg) -> None:
        """일반적인 로봇 제어 MQTT 메시지를 처리.

        모드 변경 명령 및 수동 조작 명령을 수신하여 ROS로 전달.

        Args:
            client: MQTT 클라이언트 인스턴스.
            userdata: 사용자 정의 데이터.
            msg: 제어 명령 페이로드를 포함하는 MQTT 메시지 객체.
        """
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            self.get_logger().error("MQTT Payload JSON 파싱 에러")
            return

        command = topic.split("/")[-1]

        ros_msg = String()
        ros_msg.data = str(payload.get("data", ""))

        if command == "robot_mode":
            self.robot_mode_pub.publish(ros_msg)
        elif command == "remote_control":
            self.remote_control_pub.publish(ros_msg)

    def run(self) -> None:
        """MQTT 연결 루프를 시작하고 ROS 2 노드를 구동"""
        self.get_logger().info(
            f"Connecting to MQTT Broker {self.MQTT_HOST}:{self.MQTT_PORT}..."
        )
        self.mqtt.connect(self.MQTT_HOST, self.MQTT_PORT, 60)

        self.mqtt.loop_start()

        try:
            self.get_logger().info("MQTT bridge 시작")
            rclpy.spin(self)
        except KeyboardInterrupt:
            self.get_logger().info("종료 신호 수신됨")
        finally:
            self.mqtt.loop_stop()
            self.mqtt.disconnect()


def main(args=None) -> None:
    rclpy.init(args=args)
    connector = Connector()

    try:
        connector.run()
    finally:
        connector.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
