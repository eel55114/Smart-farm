#!/usr/bin/env python3

from sensor_msgs.msg import CompressedImage 
import numpy as np
import cv2
from ultralytics import YOLO
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from ament_index_python.packages import get_package_share_directory
import os

from yolov8_msgs.msg import InferenceResult
from yolov8_msgs.msg import Yolov8Inference

bridge = CvBridge()

class Camera_subscriber(Node):

    def __init__(self):
        super().__init__('camera_subscriber')
        
        # Load YOLOv8 model
        package_share = get_package_share_directory('robot_recognition')
        model_path = os.path.join(package_share, 'models', 'yolov8n.pt')
        self.model = YOLO(model_path)
        self.get_logger().info(f"Model loaded from {model_path}")

        self.yolov8_inference = Yolov8Inference()
        self.subscription = self.create_subscription(
            CompressedImage,
            '/frontcam/image_raw/compressed',
            self.camera_callback,
            20)
        self.subscription 

        self.yolov8_pub = self.create_publisher(Yolov8Inference, "/Yolov8_Inference", 1)
        self.img_pub = self.create_publisher(Image, "/inference_result", 1)

    def camera_callback(self, data):
        np_arr = np.frombuffer(data.data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if img is None:
            self.get_logger().error("이미지를 디코딩할 수 없습니다.")
            return
            
        # ------------------ [강제 추가] 320x240으로 이미지 축소 ------------------
        img = cv2.resize(img, (320, 240))
        # ----------------------------------------------------------------------

        results = self.model(img)

        # 4. 헤더 설정 (self.get_clock() 사용 권장)
        self.yolov8_inference.header.frame_id = "inference"
        self.yolov8_inference.header.stamp = self.get_clock().now().to_msg()

        # 5. 결과 파싱 및 퍼블리시 로직 (동일)
        for r in results:
            boxes = r.boxes
            for box in boxes:
                self.inference_result = InferenceResult()
                b = box.xyxy[0].to('cpu').detach().numpy().copy()
                c = box.cls
                self.inference_result.class_name = self.model.names[int(c)]
                self.inference_result.top = int(b[1])    # y1
                self.inference_result.left = int(b[0])   # x1
                self.inference_result.bottom = int(b[3]) # y2
                self.inference_result.right = int(b[2])  # x2
                self.yolov8_inference.yolov8_inference.append(self.inference_result)

        annotated_frame = results[0].plot()
        
        # [중요] annotated_frame은 numpy 배열이므로 다시 bridge를 사용해 변환
        img_msg = bridge.cv2_to_imgmsg(annotated_frame, encoding="bgr8")  

        self.img_pub.publish(img_msg)
        self.yolov8_pub.publish(self.yolov8_inference)
        self.yolov8_inference.yolov8_inference.clear()

if __name__ == '__main__':
    rclpy.init(args=None)
    camera_subscriber = Camera_subscriber()
    rclpy.spin(camera_subscriber)
    rclpy.shutdown()
