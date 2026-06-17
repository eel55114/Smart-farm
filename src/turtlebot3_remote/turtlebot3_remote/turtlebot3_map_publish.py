import json
import os
import rclpy
import yaml
from geometry_msgs.msg import Pose
from nav_msgs.msg import OccupancyGrid, MapMetaData
from PIL import Image
from rclpy.node import Node
from std_msgs.msg import String
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy  # 🌟 QoS 설정을 위해 추가

class MapManagerNode(Node):

    def __init__(self):
        super().__init__("map_manager_node")

        # 💡 오직 이 파일관리 노드만 경로를 가집니다! (본인 계정명 확인)
        self.map_dir = "/home/kim/remote_ws/src/turtlebot3_remote/map"
"

        # 1. 대시보드에게 "현재 가지고 있는 맵 목록"을 던져줄 발행자
        self.map_list_pub = self.create_publisher(String, "/map_list", 10)

        # 2. 대시보드가 "이거 틀어줘"라고 보낸 신호를 받을 구독자
        self.map_select_sub = self.create_subscription(
            String, "/select_map", self.select_map_callback, 10
        )

        # 🌟 Nav2 및 RViz2의 내장 Map Server 호환을 위한 Transient Local QoS 설정
        map_qos_profile = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST
        )

        # 3. 묶음 처리 완료된 격자 지도를 보낼 발행자 (🌟 QoS 적용)
        self.map_pub = self.create_publisher(OccupancyGrid, "/map", map_qos_profile)

        # 5초마다 대시보드에게 파일 목록 갱신해서 보내기 (타이머)
        self.list_timer = self.create_timer(5.0, self.publish_map_list)

        self.get_logger().info("🚀 멀티 맵 관리 노드가 실행되었습니다.")

    def publish_map_list(self):
        """폴더 내부를 검사하여 맵 이름 리스트를 대시보드에 브로드캐스팅"""
        if not os.path.exists(self.map_dir):
            return

        map_names = []
        for filename in sorted(os.listdir(self.map_dir)):
            if filename.endswith(".yaml"):
                map_names.append(os.path.splitext(filename)[0])

        # 리스트 데이터를 JSON 문자열로 직렬화하여 송신
        msg = String()
        msg.data = json.dumps(map_names)
        self.map_list_pub.publish(msg)

    def select_map_callback(self, msg):
        map_id = msg.data
        self.get_logger().info(f"📥 대시보드에서 맵 요청 수신: [{map_id}]")

        yaml_path = os.path.join(self.map_dir, f"{map_id}.yaml")
        if not os.path.exists(yaml_path):
            self.get_logger().error(f"❌ 맵을 찾을 수 없음: {yaml_path}")
            return

        try:
            occupancy_grid_msg = self.load_map_and_pack(yaml_path)
            self.map_pub.publish(occupancy_grid_msg)
            self.get_logger().info(
                f"📤 [{map_id}] 맵 데이터화 완료 및 /map 토픽 발행!"
            )
        except Exception as e:
            self.get_logger().error(f"❌ 패킹 실패: {e}")

    def load_map_and_pack(self, yaml_path):
        with open(yaml_path, "r") as f:
            map_meta = yaml.safe_load(f)

        image_filename = map_meta["image"]
        image_path = os.path.join(os.path.dirname(yaml_path), image_filename)

        img = Image.open(image_path).convert("L")
        width, height = img.size

        msg = OccupancyGrid()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"

        meta = MapMetaData()
        meta.map_load_time = msg.header.stamp
        meta.resolution = map_meta["resolution"]
        meta.width = width
        meta.height = height

        origin_data = map_meta["origin"]
        origin_pose = Pose()
        origin_pose.position.x = float(origin_data[0])
        origin_pose.position.y = float(origin_data[1])
        meta.origin = origin_pose
        msg.info = meta

        occupied_thresh = map_meta.get("occupied_thresh", 0.65)
        free_thresh = map_meta.get("free_thresh", 0.196)

        grid_data = []
        for y in reversed(range(height)):
            for x in range(width):
                pixel = img.getpixel((x, y))
                occ = (255.0 - pixel) / 255.0
                if occ > occupied_thresh:
                    grid_data.append(100)
                elif occ < free_thresh:
                    grid_data.append(0)
                else:
                    grid_data.append(-1)
        msg.data = grid_data
        return msg


def main(args=None):
    rclpy.init(args=args)
    node = MapManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
