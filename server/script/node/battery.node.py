import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from collections import deque

class BatteryMonitor(Node):
    def __init__(self):
        super().__init__('battery_monitor')
        self.battery_buffer = deque(maxlen=100)
        self.filtered_percent = 0.0

        self.subscription = self.create_subscription(
            BatteryState,
            '/battery_state',
            self._battery_callback,
            10)

    def _battery_callback(self, msg):
        # 데이터 필터링 (충전 여부 로직 삭제)
        raw_percent = msg.percentage
        self.battery_buffer.append(raw_percent)
        self.filtered_percent = sum(self.battery_buffer) / len(self.battery_buffer)

    def get_battery_state(self):
        """필터링된 배터리 잔량 반환"""
        return {
            "percent": int(self.filtered_percent)
        }

def main(args=None):
    rclpy.init(args=args)
    node = BatteryMonitor()

    # 노드의 로거를 사용해 시작 알림
    node.get_logger().info('배터리 모니터링 노드가 시작되었습니다.')

    try:
        # spin() 대신 루프를 돌며 직접 출력해보기
        while rclpy.ok():
            # 토픽 데이터를 수신하기 위해 0.1초 동안 대기 및 처리
            rclpy.spin_once(node, timeout_sec=0.1)

            # 우리가 만든 함수 호출
            state = node.get_battery_state()

            # 터미널에 결과 출력 (잔량만 출력하도록 수정)
            if state['percent'] > 0:
                print(f"필터링된 잔량: {state['percent']}%")

    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()