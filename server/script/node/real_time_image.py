import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


class RobotWebBridge(Node):
    def __init__(self):
        super().__init__("robot_web_bridge")

        # 1. 이미지 구독 설정
        self.subscription = self.create_subscription(
            CompressedImage, "/image_raw/compressed", self.image_callback, 10
        )

        self.last_binary_image = None

        self.remote_control = self.create_publisher(String, "/remote_control", 10)
        self.robot_mode = self.create_publisher(String, "/robot_mode", 10)

    def set_mode(self, data: str):
        msg = String()
        msg.data = "data"

        self.robot_mode.publish(msg)

    def set_vel(self, direction: str):
        msg = String()
        msg.data = direction

        print(msg)
        self.remote_control.publish(msg)

    def image_callback(self, msg):
        """
        이미지 수신 시 OpenCV로 처리 후 JPG 바이너리로 저장
        """
        # self.last_binary_image = msg.data.tobytes()
        try:
            # 1. CompressedImage (byte array)를 numpy 배열로 변환
            np_arr = np.frombuffer(msg.data, np.uint8)

            # 2. OpenCV 이미지로 디코딩 (이미 압축된 데이터지만 처리를 위해 로드)
            cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if cv_image is not None:
                # 3. 필요 시 이미지 가공 (예: 리사이징, 필터 등)을 여기서 수행할 수 있습니다.
                # 예: cv_image = cv2.resize(cv_image, (640, 480))

                # 4. 다시 JPG 바이너리 데이터로 인코딩
                # .tobytes()를 통해 순수 바이너리 스트림으로 변환합니다.
                _, buffer = cv2.imencode(".jpg", cv_image)
                self.last_binary_image = buffer.tobytes()

        except Exception as e:
            self.get_logger().error(f"이미지 변환 실패: {e}")

    def get_image(self):
        """최신 JPG 바이너리 데이터를 반환"""
        return self.last_binary_image


def main(args=None):
    rclpy.init(args=args)
    node = RobotWebBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("노드 종료 중...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    rclpy.init(args=None)
    node = RobotWebBridge()
    try:
        while rclpy.ok():
            rclpy.spin_once(node)
            binary_data = node.get_image()

            if binary_data is not None:
                # 2. 메인 루프에서 바이너리를 다시 numpy 배열로 디코딩 (재변환)
                np_arr = np.frombuffer(binary_data, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if img is not None:
                    cv2.imshow("Robot View", img)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        node.get_logger().info("노드 종료 중...")
    finally:
        node.destroy_node()
        rclpy.shutdown()
