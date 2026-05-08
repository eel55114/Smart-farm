import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

class RobotWebBridge(Node):
    def __init__(self):
        super().__init__('robot_web_bridge')

        # 1. 이미지 구독 설정
        self.subscription = self.create_subscription(
            CompressedImage,
            '/image_raw/compressed',
            self.image_callback,
            10)

        self.last_image = None

    def image_callback(self, msg):
        """이미지 수신 시 인스턴스 변수에 저장"""
        self.last_image = msg
        # 수신 여부를 확인하고 싶다면 아래 주석을 해제하세요.
        # self.get_logger().info('이미지 수신 완료')

    def get_image(self):
        """최신 이미지를 반환"""
        if self.last_image is None:
            return None
        return self.last_image


def main(args=None):
    # ROS 2 파이썬 클라이언트 라이브러리 초기화
    rclpy.init(args=args)

    # 노드 생성
    node = RobotWebBridge()
    try:
        # 콜백 함수가 실행될 수 있도록 노드를 실행 상태로 유지
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('노드 종료 중...')
    finally:
        # 종료 처리
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()