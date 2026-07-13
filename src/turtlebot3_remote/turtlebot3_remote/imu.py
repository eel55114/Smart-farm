import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import String
import math
from scipy.spatial.transform import Rotation as R

class TurtleBot3TiltDetector(Node):

    def __init__(self):
        super().__init__('turtlebot3_tilt_detector')

        self.subscription = self.create_subscription(
            Imu,
            '/imu',
            self.imu_callback,
            10
        )
        self.tilt_publisher = self.create_publisher(String, 'robot_log', 10)

        # --- [핵심 수정] 히스테리시스 임계값 설정 ---
        self.tilt_danger_threshold = 40.0   # 이 각도를 넘으면 '전복'으로 판단
        self.tilt_safe_threshold = 10.0     # 이 각도 밑으로 내려와야 '해제'로 판단
        # ------------------------------------------
        
        self.is_tilted = False

    def imu_callback(self, msg):
        q_x = msg.orientation.x
        q_y = msg.orientation.y
        q_z = msg.orientation.z
        q_w = msg.orientation.w

        r = R.from_quat([q_x, q_y, q_z, q_w])
        roll_rad, pitch_rad, _ = r.as_euler('xyz')

        roll_deg = abs(math.degrees(roll_rad))
        pitch_deg = abs(math.degrees(pitch_rad))

        # 현재 상태(정상 vs 전복)에 따라 다른 임계값을 적용합니다.
        if not self.is_tilted:
            # 1. 현재 정상 상태일 때 -> 40도를 넘어야 전복으로 판단
            if roll_deg > self.tilt_danger_threshold or pitch_deg > self.tilt_danger_threshold:
                tilt_msg = String()
                tilt_msg.data = f'전복 감지 (Roll: {roll_deg:.1f}°, Pitch: {pitch_deg:.1f}°)'
                self.tilt_publisher.publish(tilt_msg)
                
                # 터미널에서도 보고 싶다면 아래 주석을 해제하세요
                # self.get_logger().warn(tilt_msg.data)
                
                self.is_tilted = True
        else:
            # 2. 현재 전복 상태일 때 -> Roll과 Pitch '둘 다' 10도 이하로 내려와야 안전 구역(해제)
            if roll_deg <= self.tilt_safe_threshold and pitch_deg <= self.tilt_safe_threshold:
                tilt_msg = String()
                tilt_msg.data = f'전복 해제 (Roll: {roll_deg:.1f}°, Pitch: {pitch_deg:.1f}°)'
                self.tilt_publisher.publish(tilt_msg)
                
                # 터미널에서도 보고 싶다면 아래 주석을 해제하세요
                # self.get_logger().info(tilt_msg.data)
                
                self.is_tilted = False

def main(args=None):
    rclpy.init(args=args)
    node = TurtleBot3TiltDetector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
