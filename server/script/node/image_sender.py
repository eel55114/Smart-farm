import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import socketio


class ImageSender(Node):
    def __init__(self):
        super().__init__("image_sender_node")

        # 파라미터 선언 및 가져오기
        self.declare_parameter('image_src', "/usb/image_raw/compressed")
        self.declare_parameter('image_dir', "side")   # "front" 또는 "side"
        self.declare_parameter('robot_id', 1)          # 로봇 ID (int)
        self.declare_parameter('server_url', "http://127.0.0.1:5000")

        src_topic = self.get_parameter('image_src').get_parameter_value().string_value
        self.image_dir = self.get_parameter('image_dir').get_parameter_value().string_value
        self.robot_id = self.get_parameter('robot_id').get_parameter_value().integer_value
        server_url = self.get_parameter('server_url').get_parameter_value().string_value

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

        # Socket.IO 클라이언트 연결
        self.sio = socketio.Client()
        self.sio.connect(server_url)

        self.get_logger().info(
            f"Streaming images from {src_topic} to {server_url} "
            f"[robot_id={self.robot_id}, dir={self.image_dir}]"
        )

    def callback(self, msg):
        try:
            # CompressedImage의 format이 'jpeg'인 경우 별도의 변환 없이 바로 바이너리 추출
            image_binary = msg.data.tobytes()

            # Socket.IO 'stream_image' 이벤트로 로봇 ID와 카메라 방향을 함께 송신
            self.sio.emit("stream_image", {
                "robot_id": self.robot_id,
                "dir": self.image_dir,
                "frame": image_binary,
            })

        except Exception as e:
            self.get_logger().error(f"Failed to send image: {e}")

    def destroy_node(self):
        self.sio.disconnect()
        super().destroy_node()


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