import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import BatteryState, CompressedImage
from std_msgs.msg import String, Float32

class RobotDataPreprocessor(Node):
    def __init__(self):
        super().__init__('robot_data_preprocessor')

        # 🌟 QoS 설정 (센서 데이터 수신을 위한 필수 설정)
        self.qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # 1. 상태 관리 변수
        self.latest_pose = None
        self.last_robot_state = ""
        self.battery_buffer = []

        # 2. 원본 데이터 구독 (모든 토픽에 QoS 적용)
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.pose_callback, self.qos_profile)
        self.create_subscription(String, '/robot_state', self.state_callback, 10)
        self.create_subscription(BatteryState, '/battery_state', self.battery_callback, self.qos_profile)
        # 이미지 중복 구독 제거 (한 번만 구독하도록 수정)
        self.create_subscription(CompressedImage, '/captured_image/compressed', self.image_callback, self.qos_profile)

        # 3. 가공된 데이터 발행
        self.pose_pub = self.create_publisher(PoseWithCovarianceStamped, '/web_bridge/pose', 10)
        self.state_pub = self.create_publisher(String, '/web_bridge/state', 10)
        self.battery_pub = self.create_publisher(Float32, '/web_bridge/battery', 10)
        self.image_pub = self.create_publisher(CompressedImage, '/web_bridge/captured_image', 10)

        # 4. 발행 주기 제어용 타이머
        self.create_timer(0.1, self.publish_pose_throttled) 
        self.create_timer(1.0, self.publish_battery_averaged)

        self.get_logger().info("✅ 웹 통신용 데이터 전처리 중계 노드가 완벽하게 준비되었습니다.")

    # [콜백 및 발행 로직]
    def pose_callback(self, msg):
        self.latest_pose = msg

    def publish_pose_throttled(self):
        if self.latest_pose:
            self.pose_pub.publish(self.latest_pose)
            self.latest_pose = None

    def state_callback(self, msg):
        current_state = msg.data
        if current_state != self.last_robot_state:
            self.last_robot_state = current_state
            new_msg = String()
            new_msg.data = current_state
            self.state_pub.publish(new_msg)

    def battery_callback(self, msg):
        self.battery_buffer.append(msg.percentage)

    def publish_battery_averaged(self):
        if self.battery_buffer:
            avg_battery = sum(self.battery_buffer) / len(self.battery_buffer)
            new_msg = Float32()
            new_msg.data = float(avg_battery)
            self.battery_pub.publish(new_msg)
            self.battery_buffer.clear()

    def image_callback(self, msg):
        self.image_pub.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = RobotDataPreprocessor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
