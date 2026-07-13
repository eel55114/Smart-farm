# #!/usr/bin/env python3
# import rclpy
# from rclpy.node import Node
# from sensor_msgs.msg import Image
# from cv_bridge import CvBridge
# from ultralytics import YOLO
# from yolov8_msgs.msg import HumanPosition

# import os
# import numpy as np

# class HumanPositionPublisher(Node):
#     def __init__(self):
#         super().__init__('human_position_publisher')

#         # Load YOLOv8 model
#         model_path = os.path.expanduser('~/robot_detect/src/robot_recognition/scripts/yolov8n.pt')
#         self.model = YOLO(model_path)

#         self.bridge = CvBridge()

#         # Camera subscriber
#         self.subscription = self.create_subscription(
#             Image,
#             '/camera/image_raw',
#             self.image_callback,
#             10
#         )

#         # Publisher cho HumanPosition
#         self.publisher_ = self.create_publisher(HumanPosition, '/human_position', 10)

#         self.get_logger().info("✅ Human Position Publisher started!")

#     def image_callback(self, msg):
#         # Convert ROS Image -> OpenCV
#         frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')

#         # Chạy YOLOv8
#         results = self.model(frame)

#         # Giả sử chỉ quan tâm đến person đầu tiên
#         for r in results:
#             boxes = r.boxes
#             for box in boxes:
#                 cls = int(box.cls)
#                 label = self.model.names[cls]
#                 conf = float(box.conf)

#                 if label == 'person' and conf > 0.5:
#                     xyxy = box.xyxy[0].cpu().numpy()
#                     x1, y1, x2, y2 = xyxy

#                     # Tính toán vị trí trung tâm & kích thước box
#                     x_center = (x1 + x2) / 2.0
#                     y_center = (y1 + y2) / 2.0
#                     width = x2 - x1
#                     height = y2 - y1

#                     # Gửi message
#                     human_msg = HumanPosition()
#                     human_msg.x_center = float(x_center)
#                     human_msg.y_center = float(y_center)
#                     human_msg.width = float(width)
#                     human_msg.height = float(height)
#                     human_msg.confidence = float(conf)

#                     self.publisher_.publish(human_msg)

#                     self.get_logger().info(
#                         f"👤 Person detected at x={x_center:.1f}, y={y_center:.1f}, w={width:.1f}, conf={conf:.2f}"
#                     )
#                     return  # Chỉ gửi người đầu tiên
    
# def main(args=None):
#     rclpy.init(args=args)
#     node = HumanPositionPublisher()
#     try:
#         rclpy.spin(node)
#     except KeyboardInterrupt:
#         pass
#     node.destroy_node()
#     rclpy.shutdown()

# if __name__ == '__main__':
#     main()


#!/usr/bin/env python3
import rclpy
from sensor_msgs.msg import CompressedImage 
import cv2
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from ultralytics import YOLO
from yolov8_msgs.msg import HumanPosition, HumanPositionArray
from rclpy.qos import qos_profile_sensor_data
import os
import numpy as np

class HumanPositionPublisher(Node):
    def __init__(self):
        super().__init__('human_position_publisher')

        # Load YOLOv8 model
        model_path = os.path.expanduser('~/home/kim/remote_ws/src/robot_recognition/scripts')
        self.model = YOLO(model_path)

        self.bridge = CvBridge()

        # Nhận ảnh từ camera
        self.subscription = self.create_subscription(
            CompressedImage,
            '/frontcam/image_raw/compressed',
            self.image_callback,
            qos_profile_sensor_data  # <--- 기존 10에서 변경
        )

        # Publish danh sách người
        self.publisher_ = self.create_publisher(HumanPositionArray, '/human_positions', 1)  # <--- 기존 10에서 1로 변경

        self.get_logger().info("✅ Human Position Publisher started!")

    def image_callback(self, msg):
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # ------------------ [강제 추가] 320x240으로 이미지 축소 ------------------
        if frame is not None:
            frame = cv2.resize(frame, (320, 240))
        else:
            self.get_logger().error("이미지를 디코딩할 수 없습니다.")
            return
        # ----------------------------------------------------------------------

        results = self.model(frame, verbose=False) # 이제 YOLO가 320x240으로 연산합니다.
        human_array_msg = HumanPositionArray()
        for r in results:
            boxes = r.boxes
            for box in boxes:
                cls = int(box.cls)
                label = self.model.names[cls]
                conf = float(box.conf)

                if label == 'person' and conf > 0.5:
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1, y1, x2, y2 = xyxy

                    x_center = (x1 + x2) / 2.0
                    y_center = (y1 + y2) / 2.0
                    w = x2 - x1
                    h = y2 - y1

                    person = HumanPosition()
                    person.x_center = float(x_center)
                    person.y_center = float(y_center)
                    person.width = float(w)
                    person.height = float(h)
                    person.confidence = float(conf)

                    human_array_msg.humans.append(person)

        if len(human_array_msg.humans) > 0:
            self.publisher_.publish(human_array_msg)
            #self.get_logger().info(f"👥 {len(human_array_msg.humans)} humans detected")

def main(args=None):
    rclpy.init(args=args)
    node = HumanPositionPublisher()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
