import os

import rclpy
import socketio
from dotenv import load_dotenv
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from socketio.exceptions import BadNamespaceError

# 현재 파일이 위치한 디렉토리의 .env 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))


class DualImageStreamer(Node):
    def __init__(self):
        super().__init__("dual_image_streamer")

        # .env 파일에서 리전 및 로봇 ID 정보 획득
        region_id = os.getenv("REGION_ID", "1")
        robot_id = os.getenv("ROBOT_ID", "1")
        server_url = os.getenv("SERVER_URL", "http://localhost:5000")

        self.get_logger().info(
            f"Connecting to {server_url} with region_id={region_id}, robot_id={robot_id}"
        )

        self.sio = socketio.Client()
        # 소켓 연결 시 쿼리 파라미터로 region_id 및 robot_id 인계
        connect_url = f"{server_url}?region_id={region_id}&robot_id={robot_id}"
        self.sio.connect(connect_url)

        self.sub_cam_front = self.create_subscription(
            CompressedImage,
            "/frontcam/image_raw/compressed",
            lambda m: self.image_callback(m, "front"),
            1,
        )

        self.sub_cam_side = self.create_subscription(
            CompressedImage,
            "/sidecam/image_raw/compressed",
            lambda m: self.image_callback(m, "side"),
            1,
        )

    def image_callback(self, msg, name):
        if not self.sio.connected:
            return
        try:
            self.sio.emit(f"stream_{name}", bytes(msg.data))
        except BadNamespaceError:
            pass


def main(args=None):
    rclpy.init(args=args)
    node = DualImageStreamer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.sio.disconnect()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
