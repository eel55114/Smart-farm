import json
import os
from typing import Final

import dotenv
import paho.mqtt.client as mqtt
import rclpy
from paho.mqtt.enums import CallbackAPIVersion
from rclpy.node import Node
from std_msgs.msg import String


def msg_packer(**kwargs):
    return json.dumps(kwargs)


class Connector(Node):
    def __init__(self) -> None:
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
        }

        self.mqtt = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message

        self.robot_mode_pub = self.create_publisher(String, "/robot_mode", 10)

        self.state_sub = self.create_subscription(
            String, "/robot_state", self.robot_state_callback, 10
        )

    def robot_state_callback(self, msg: String):
        topic = self.TOPIC_PREFIX["robot_telemetry"] + "robot_state"
        self.mqtt.publish(topic, msg.data)
        # self.get_logger().info(f"ROS -> MQTT: {msg.data}")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.get_logger().info("MQTT Connected successfully.")
            client.subscribe(self.TOPIC_PREFIX["robot_command"] + "#")
        else:
            self.get_logger().error(f"MQTT Connection failed: {reason_code}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            self.get_logger().error("MQTT Payload JSON 파싱 에러")
            return

        command = topic.split("/")[-1]

        ros_msg = String()

        if command == "robot_mode" or command == "remote_control":
            ros_msg.data = str(payload.get("data", ""))
            self.robot_mode_pub.publish(ros_msg)

    def run(self):
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


def main(args=None):
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
