#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, CameraInfo
import cv2
import numpy as np
import math

class ArucoAlignmentTestNode(Node):
    def __init__(self):
        super().__init__('aruco_alignment_test_node')
        
        # 1. 기존 파라미터 및 변수 유지
        self.camera_matrix = None
        self.dist_coeffs = None
        
        self.distortion_k = 0.0006 
        self.offset_bias = 0.17
        self.tilt_tolerance = 0.08
        self.x_err_tolerance = 15.0
        self.target_dist_z = 0.55
        
        # 테스트를 위한 가상의 고정 타겟 마커 ID 설정 (필요시 변경 가능)
        # 기존 코드의 self.locked_target_id 역할을 합니다.
        self.locked_target_id = 1 
        
        # 2. ArUco 디텍터 설정 (기존 코드와 동일)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        self.parameters = cv2.aruco.DetectorParameters()
        self.parameters.adaptiveThreshWinSizeMin = 3
        self.parameters.adaptiveThreshWinSizeMax = 23
        self.parameters.adaptiveThreshWinSizeStep = 10
        self.parameters.adaptiveThreshConstant = 12
        self.parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.parameters)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        
        # 3. Subscriber 설정 (기존 토픽 유지)
        self.info_sub = self.create_subscription(
            CameraInfo, 
            '/sidecam/camera_info', 
            self.camera_info_callback, 
            10
        )
        self.sub_image = self.create_subscription(
            CompressedImage, 
            '/sidecam/image_raw/compressed', 
            self.image_callback, 
            10
        )
        
        self.get_logger().info(f"🔍 ArUco 마커 인식 및 정렬 오차 테스트 노드 가동 (타겟 마커 ID: {self.locked_target_id})")

    def camera_info_callback(self, msg):
        if self.camera_matrix is None:
            self.camera_matrix = np.array(msg.k, dtype=np.float32).reshape((3, 3))
            self.dist_coeffs = np.array(msg.d, dtype=np.float32)
            self.get_logger().info("✅ 카메라 캘리브레이션 정보(/sidecam/camera_info) 수신 완료!")

    def image_callback(self, msg):
        if self.camera_matrix is None or self.dist_coeffs is None:
            self.get_logger().warning("⏳ 카메라 캘리브레이션 정보 대기 중...", throttle_duration_sec=2.0)
            return
        
        # 이미지 디코딩 및 전처리
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 감마 보정 및 CLAHE 적용 (기존 로직 동일)
        gamma_lut = np.array(255 * (np.arange(256) / 255.0) ** 1.5, dtype=np.uint8)
        gray = cv2.LUT(gray, gamma_lut)
        gray = self.clahe.apply(cv2.GaussianBlur(gray, (3, 3), 0))
        
        # 마커 검출
        corners, ids, _ = self.detector.detectMarkers(gray)
        
        target_idx_in_detection = -1
        
        # 다중 마커 중 locked_target_id만 필터링
        if ids is not None:
            flattened_ids = ids.flatten()
            for i, marker_id in enumerate(flattened_ids):
                if int(marker_id) == self.locked_target_id:
                    target_idx_in_detection = i
                    break
        
        # 타겟 마커를 찾은 경우 오차 계산 및 로봇 행동 판단
        if target_idx_in_detection != -1:
            c = corners[target_idx_in_detection][0]
            success, rvec, tvec = cv2.solvePnP(
                np.array([[-0.04, 0.04, 0], [0.04, 0.04, 0], [0.04, -0.04, 0], [-0.04, -0.04, 0]], dtype=np.float32),
                c, self.camera_matrix, self.dist_coeffs
            )
            
            if success:
                rmat, _ = cv2.Rodrigues(rvec)
                raw_tilt = -rmat[0, 2]
                if rmat[2, 2] < 0: 
                    raw_tilt = -raw_tilt
                    
                pixel_x_err = (int(np.mean(c[:, 0])) - 320)
                calibrated_tilt = raw_tilt + (pixel_x_err * self.distortion_k) - self.offset_bias
                dist_z = tvec[2][0]
                
                # --- 오차값 로그 출력 ---
                log_msg = (
                    f"\n🎯 [마커 ID {self.locked_target_id} 감지됨]\n"
                    f"  - Pixel X Error : {pixel_x_err:6.2f} (기준 오차범위: ±{self.x_err_tolerance})\n"
                    f"  - Calibrated Tilt: {calibrated_tilt:6.4f} (기준 오차범위: ±{self.tilt_tolerance})\n"
                    f"  - Distance Z     : {dist_z:6.4f} m (목표 거리: {self.target_dist_z} m)"
                )
                self.get_logger().info(log_msg)
                
                # --- 기존 제어 로직(align_state 1 및 거리비교) 기반 행동 판단 ---
                # 1단계 격차 판별 (기울기 및 중심선 맞추기)
                if abs(calibrated_tilt) < self.tilt_tolerance and abs(pixel_x_err) < self.x_err_tolerance:
                    # 정면 정렬은 완벽한 상태인 경우 -> 거리 판별
                    dist_diff = dist_z - self.target_dist_z
                    if abs(dist_diff) <= 0.05:
                        self.get_logger().info("🤖 [로봇 행동] ★ 정렬 완료 (State 5 조건 만족) ★ 촬영 가능 상태입니다.")
                    else:
                        direction = "전진" if dist_diff > 0 else "후진"
                        self.get_logger().info(f"🤖 [로봇 행동] 정면 정렬 완료. 거리 조정을 위해 180도 회전 후 {direction}해야 합니다. (State 2 진입 조건)")
                else:
                    # 정면 정렬 보정이 필요한 상태
                    target_ang_vel = calibrated_tilt * 0.4
                    target_lin_vel = np.clip(-pixel_x_err * 0.0005, -0.05, 0.05)
                    
                    ang_dir = "좌회전(CCW)" if target_ang_vel > 0 else "우회전(CW)"
                    lin_dir = "전진(Forward)" if target_lin_vel > 0 else "후진(Backward)"
                    
                    self.get_logger().info(
                        f"🤖 [로봇 행동] 미세 정렬 중 (State 1) -> 예상 제어 속도:\n"
                        f"  └─ 선속도: {target_lin_vel:6.4f} m/s ({lin_dir})\n"
                        f"  └─ 각속도: {target_ang_vel:6.4f} rad/s ({ang_dir})"
                    )
        else:
            self.get_logger().warn(f"❌ 시야 내에 타겟 마커(ID: {self.locked_target_id})가 보이지 않습니다. 제자리 정지 유지.", throttle_duration_sec=2.0)

def main():
    rclpy.init()
    node = ArucoAlignmentTestNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()
