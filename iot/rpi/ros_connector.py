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
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from paho.mqtt.enums import CallbackAPIVersion
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile
from rosidl_runtime_py.set_message import set_message_fields
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


class Connector(Node):
    """MQTT ↔ ROS 2 브릿지 노드."""

    def __init__(self, map_dir_path: str = "") -> None:
        super().__init__("mqtt_ros_bridge_node")
        dotenv.load_dotenv()

        def _env(key: str) -> str:
            val = os.getenv(key)
            if val is None:
                self.get_logger().error(f"환경 변수 누락: {key}")
                raise ValueError(f"환경 변수 누락: {key}")
            return val

        self.MQTT_HOST: Final = _env("MQTT_HOST")
        self.MQTT_PORT: Final = int(_env("MQTT_PORT"))
        self.REGION_ID: Final = int(_env("REGION_ID"))
        self.ROBOT_ID: Final = int(_env("ROBOT_ID"))

        base = f"smartfarm/{self.REGION_ID}/robot"
        self.TOPIC_PREFIX: Final = {
            "telemetry": f"{base}/telemetry/{self.ROBOT_ID}/",
            "command": f"{base}/command/{self.ROBOT_ID}/",
            "plant_img": f"smartfarm/{self.REGION_ID}/plant/img/",
        }

        if map_dir_path:
            p = Path(map_dir_path)
        else:
            p = Path(__file__).parent / "map"
            if not p.is_dir():
                p = p.parent.parent / "map"
        if not p.is_dir():
            raise ValueError(f"유효하지 않은 지도 디렉토리: {p}")
        self.map_dir_path = p

        self.mqtt = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self.on_connect
        map_qos_profile = QoSProfile(
            depth=1,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,  # 👈 이 부분이 핵심입니다!
        )
        # ROS Publishers
        self.robot_mode_pub = self.create_publisher(String, "/robot_mode", 10)
        self.remote_control_pub = self.create_publisher(String, "/remote_control", 10)
        self.map_pub = self.create_publisher(OccupancyGrid, "/map", map_qos_profile)
        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )
        self.goal_pose_pub = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.publish_param_pub = self.create_publisher(String, "/publish_param", 10)
        self.schedule_pub = self.create_publisher(String, "/json_schedule", 10)
        self.sequence_pub = self.create_publisher(String, "/json_sequence", 10)

        self._subs = [
            self.create_subscription(String, "/robot_state", self._on_robot_state, 1),
            self.create_subscription(String, "/robot_mode", self._on_robot_mode, 10),
            self.create_subscription(
                String, "/web_bridge/battery", self._on_battery, 1
            ),
            self.create_subscription(String, "/robot_log", self._on_robot_log, 10),
            self.create_subscription(
                CompressedImage, "/captured_image/compressed", self._on_plant_img, 1
            ),
            self.create_subscription(
                PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl_pose, 10
            ),
        ]

    # ── ROS → MQTT ──────────────────────────────────────────────────────────

    def _on_robot_state(self, msg: String) -> None:
        """ROS /robot_state → MQTT .../state"""
        self.mqtt.publish(
            self.TOPIC_PREFIX["telemetry"] + "state",
            json.dumps({"state": msg.data}),
        )
        self.get_logger().info(f"로봇 상태: {msg.data}")

    def _on_robot_mode(self, msg: String) -> None:
        """ROS /robot_mode → MQTT .../robot_mode"""
        self.mqtt.publish(
            self.TOPIC_PREFIX["telemetry"] + "robot_mode",
            json.dumps({"data": msg.data}),
        )
        self.get_logger().info(f"로봇 모드: {msg.data}")

    def _on_battery(self, msg: String) -> None:
        """ROS /battery → MQTT .../battery"""
        try:
            pct = int(float(msg.data))
        except (ValueError, TypeError):
            pct = 0
        self.mqtt.publish(
            self.TOPIC_PREFIX["telemetry"] + "battery",
            json.dumps({"data": pct}),
        )

    def _on_robot_log(self, msg: String) -> None:
        """ROS /robot_log → MQTT .../log"""
        self.mqtt.publish(
            self.TOPIC_PREFIX["telemetry"] + "log",
            json.dumps({"time": time.time(), "data": msg.data}),
        )
        self.get_logger().info(f"로봇 로그: {msg.data}")

    def _on_plant_img(self, msg: CompressedImage) -> None:
        """ROS /captured_image/compressed → MQTT .../captured_img"""
        match = re.search(r"Marker ID:\s*(\d+)", msg.header.frame_id)
        marker_id = int(match.group(1)) if match else 1
        self.mqtt.publish(
            self.TOPIC_PREFIX["plant_img"] + "captured_img",
            json.dumps(
                {
                    "id": marker_id,
                    "time": time.time(),
                    "img": base64.b64encode(msg.data).decode(),
                }
            ),
        )
        self.get_logger().info(f"Marker {marker_id} 이미지 송신")

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        """ROS /amcl_pose → MQTT .../amcl_pose"""
        p = msg.pose.pose
        self.mqtt.publish(
            self.TOPIC_PREFIX["telemetry"] + "amcl_pose",
            json.dumps(
                {
                    "pose": {
                        "pose": {
                            "position": {
                                "x": p.position.x,
                                "y": p.position.y,
                                "z": p.position.z,
                            },
                            "orientation": {
                                "x": p.orientation.x,
                                "y": p.orientation.y,
                                "z": p.orientation.z,
                                "w": p.orientation.w,
                            },
                        }
                    }
                }
            ),
        )
        self.get_logger().debug("amcl_pose 전송")

    # ── MQTT → ROS ──────────────────────────────────────────────────────────

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            self.get_logger().error(f"MQTT 연결 실패: {reason_code}")
            return

        self.get_logger().info("MQTT 연결 성공")
        cmd = self.TOPIC_PREFIX["command"]
        client.subscribe(cmd + "#")

        for suffix, cb in {
            "set_map": self._on_set_map,
            "map_data": self._on_map_data,
            "initial_pose": self._on_initial_pose,
            "goal_pose": self._on_goal_pose,
            "publish_param": self._on_publish_param,
            "waypoint": self._on_sequence,
            "set_schedule": self._on_schedule,
        }.items():
            client.message_callback_add(cmd + suffix, cb)

        # 위에서 등록되지 않은 커맨드의 fallback
        client.message_callback_add(cmd + "#", self._on_robot_command)

    def _on_schedule(self, client, userdata, msg) -> None:
        ros_msg = String()
        ros_msg.data = msg.payload.decode("utf-8")
        self.schedule_pub.publish(ros_msg)

    def _on_sequence(self, client, userdata, msg) -> None:
        ros_msg = String()
        ros_msg.data = msg.payload.decode("utf-8")
        self.sequence_pub.publish(ros_msg)

    def _on_set_map(self, client, userdata, msg) -> None:
        """set_map: 로컬 파일 해시 비교 후 지도 발행 또는 서버에 요청."""
        try:
            p = json.loads(msg.payload)
            map_name = p["name"]
            img_hash = p["img_hash"]
            inform_hash = p["inform_hash"]
        except (json.JSONDecodeError, KeyError) as e:
            self.get_logger().error(f"set_map 파싱 오류: {e}")
            return

        self.get_logger().info(f"맵 설정 명령: {map_name}")

        img_file = (self.map_dir_path / map_name).with_suffix(".pgm")
        inform_file = (self.map_dir_path / map_name).with_suffix(".yaml")
        req_img = req_inform = True

        if img_file.is_file() and inform_file.is_file():
            img_data = img_file.read_bytes()
            inform_data = inform_file.read_bytes()
            local_img_h = hashlib.sha256(img_data).hexdigest()
            local_inform_h = hashlib.sha256(inform_data).hexdigest()

            if img_hash == local_img_h and inform_hash == local_inform_h:
                mtime = int(max(img_file.stat().st_mtime, inform_file.stat().st_mtime))
                self._publish_map(map_name, mtime, img_data, inform_data)
                self.get_logger().info(f"맵 설정 완료: {map_name}")
                return

            req_img = img_hash != local_img_h
            req_inform = inform_hash != local_inform_h

        client.publish(
            self.TOPIC_PREFIX["telemetry"] + "get_map",
            json.dumps({"name": map_name, "img": req_img, "inform": req_inform}),
        )
        self.get_logger().info(f"맵 데이터 요청: {map_name}")

    def _on_map_data(self, client, userdata, msg) -> None:
        """map_data: Base64 이미지 디코딩 후 로컬 저장 및 지도 발행."""
        try:
            p = json.loads(msg.payload)
            map_name = p["name"]
            img_bytes = base64.b64decode(p["img"])
            inform_str = p["inform"]
        except (json.JSONDecodeError, KeyError, Exception) as e:
            self.get_logger().error(f"map_data 처리 오류: {e}")
            return

        (self.map_dir_path / map_name).with_suffix(".pgm").write_bytes(img_bytes)
        (self.map_dir_path / map_name).with_suffix(".yaml").write_text(inform_str)
        self._publish_map(map_name, int(time.time()), img_bytes, inform_str)

    def _publish_map(
        self, name: str, mtime: int, img: bytes, inform: str | bytes
    ) -> None:
        """PGM + YAML → OccupancyGrid 변환 후 ROS 발행."""
        ros_msg = OccupancyGrid()
        set_message_fields(
            ros_msg, map_converter.tuple_to_msg(name, mtime, img, inform)
        )
        self.map_pub.publish(ros_msg)

    def _on_initial_pose(self, client, userdata, msg) -> None:
        """initial_pose: ROS /initialpose 발행."""
        try:
            p = json.loads(msg.payload)
            x, y = float(p["x"]), float(p["y"])
            z = float(p.get("z", 0.0))
            qx, qy = float(p.get("qx", 0.0)), float(p.get("qy", 0.0))
            qz, qw = float(p["qz"]), float(p["qw"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.get_logger().error(f"initial_pose 파싱 오류: {e}")
            return

        ros_msg = PoseWithCovarianceStamped()
        ros_msg.header.frame_id = "map"
        ros_msg.header.stamp = self.get_clock().now().to_msg()
        ros_msg.pose.pose.position.x = x
        ros_msg.pose.pose.position.y = y
        ros_msg.pose.pose.position.z = z
        ros_msg.pose.pose.orientation.x = qx
        ros_msg.pose.pose.orientation.y = qy
        ros_msg.pose.pose.orientation.z = qz
        ros_msg.pose.pose.orientation.w = qw
        self.initial_pose_pub.publish(ros_msg)
        self.get_logger().info(
            f"초기 위치: x={x:.3f}, y={y:.3f}, qz={qz:.3f}, qw={qw:.3f}"
        )

    def _on_goal_pose(self, client, userdata, msg) -> None:
        """goal_pose: ROS /goal_pose 발행."""
        try:
            p = json.loads(msg.payload)
            x, y = float(p["x"]), float(p["y"])
            z = float(p.get("z", 0.0))
            qx, qy = float(p.get("qx", 0.0)), float(p.get("qy", 0.0))
            qz, qw = float(p.get("qz", 0.0)), float(p.get("qw", 1.0))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.get_logger().error(f"goal_pose 파싱 오류: {e}")
            return

        ros_msg = PoseStamped()
        ros_msg.header.frame_id = "map"
        ros_msg.header.stamp = self.get_clock().now().to_msg()
        ros_msg.pose.position.x = x
        ros_msg.pose.position.y = y
        ros_msg.pose.position.z = z
        ros_msg.pose.orientation.x = qx
        ros_msg.pose.orientation.y = qy
        ros_msg.pose.orientation.z = qz
        ros_msg.pose.orientation.w = qw
        self.goal_pose_pub.publish(ros_msg)
        self.get_logger().info(f"목표 지점: x={x:.3f}, y={y:.3f}")

    def _on_publish_param(self, client, userdata, msg) -> None:
        """publish_param: ROS /publish_param 발행."""
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as e:
            self.get_logger().error(f"publish_param 파싱 오류: {e}")
            return
        ros_msg = String()
        ros_msg.data = json.dumps(payload, ensure_ascii=False)
        self.publish_param_pub.publish(ros_msg)
        self.get_logger().info(
            f"파라미터 전송: {payload.get('current_controller', '?')}"
        )

    def _on_robot_command(self, client, userdata, msg) -> None:
        """robot_mode / remote_control 명령 처리 (fallback)."""
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            self.get_logger().error("robot command JSON 파싱 오류")
            return

        command = msg.topic.split("/")[-1]
        pub = {
            "robot_mode": self.robot_mode_pub,
            "remote_control": self.remote_control_pub,
        }.get(command)
        if pub:
            ros_msg = String()
            ros_msg.data = str(payload.get("data", ""))
            pub.publish(ros_msg)

    # ── 실행 ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """MQTT 연결 후 ROS 스핀."""
        self.get_logger().info(
            f"MQTT 브로커 연결 중: {self.MQTT_HOST}:{self.MQTT_PORT}"
        )
        self.mqtt.connect(self.MQTT_HOST, self.MQTT_PORT, 60)
        self.mqtt.loop_start()
        try:
            rclpy.spin(self)
        except KeyboardInterrupt:
            self.get_logger().info("종료 신호 수신")
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
