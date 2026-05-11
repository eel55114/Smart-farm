import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import numpy as np


class RobotWebBridge(Node):
    def __init__(self):
        super().__init__('robot_web_bridge')

        # 1. 이미지 구독 설정
        self.subscription = self.create_subscription(
            CompressedImage,
            '/image_raw/compressed',
            self.image_callback,
            10)

        self.last_binary_image = None

    def image_callback(self, msg):
        """
        이미지 수신 시 OpenCV로 처리 후 JPG 바이너리로 저장
        """
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
                _, buffer = cv2.imencode('.jpg', cv_image)
                self.last_binary_image = buffer.tobytes()

        except Exception as e:
            self.get_logger().error(f'이미지 변환 실패: {e}')

    def get_image(self):
        """최신 JPG 바이너리 데이터를 반환"""
        return self.last_binary_image


def main(args=None):
    rclpy.init(args=args)
    node = RobotWebBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('노드 종료 중...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()