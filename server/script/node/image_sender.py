import rclpy
import requests
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import numpy as np
import cv2


class ImageSender(Node):
    def __init__(self):
        super().__init__("image_sender_node")

        # 파라미터 선언 및 가져오기
        self.declare_parameter('image_src', "/usb/image_raw/compressed")
        # URL에 http:// 가 포함되어 있는지 확인하십시오.
        self.declare_parameter('image_to', "http://127.0.0.1:5000/image_refresh?dir=side")

        src_topic = self.get_parameter('image_src').get_parameter_value().string_value
        self.image_to = self.get_parameter('image_to').get_parameter_value().string_value

        my_qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE,
            depth=1
        )

        self.subscriber_ = self.create_subscription(
            CompressedImage,
            src_topic,
            self.callback,
            qos_profile=my_qos_profile
        )

        self.get_logger().info(f"Sending images from {src_topic} to {self.image_to}")

    def callback(self, msg):
        try:
            # CompressedImage의 format이 'jpeg'인 경우 별도의 변환 없이 바로 바이너리 추출
            # 만약 이미지 가공(자르기, 그리기 등)이 필요하다면 그때만 decode 하십시오.
            image_binary = msg.data.tobytes()

            # HTTP POST 전송
            files = {'image': ('frame.jpg', image_binary, 'image/jpeg')}
            response = requests.post(self.image_to, files=files, timeout=0.5)

            if response.status_code != 200:
                self.get_logger().error(f"Server returned: {response.status_code}")

        except Exception as e:
            self.get_logger().error(f"Failed to send image: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = ImageSender()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()