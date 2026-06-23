#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped, Twist
from sensor_msgs.msg import CompressedImage, BatteryState, LaserScan
from std_msgs.msg import String
from yolov8_msgs.msg import HumanPositionArray
from sensor_msgs.msg import CameraInfo

import cv2
import numpy as np
import math
import time
import threading

class IntegratedRobotControl(Node):
    def __init__(self):
        super().__init__('integrated_robot_control')

        # ====================================================================
        # 1. 자율주행 & ArUco 이미지 처리 설정 (기존)
        # ====================================================================
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        self.parameters = cv2.aruco.DetectorParameters()
        self.parameters.adaptiveThreshWinSizeMin = 3
        self.parameters.adaptiveThreshWinSizeMax = 23
        self.parameters.adaptiveThreshWinSizeStep = 10
        self.parameters.adaptiveThreshConstant = 12
        self.parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.parameters)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # ====================================================================
        # 2. 전역 상태 관리 변수
        # ====================================================================
        self.current_mode = "manual"  # "manual", "auto", "follow"
        self.auto_step = "NAV"
        self.current_wp_idx = 0
        self.align_done = False
        self.latest_msg = None
        self.goal_handle = None
        self.is_battery_low = False
        self.is_returning_home = False 

        # 자율주행 스레드 관리 변수
        self.auto_thread = None
        self.is_auto_running = False

        # 수동 조종 속도 누적 변수
        self.target_linear_vel = 0.0
        self.target_angular_vel = 0.0

        # 정밀 정렬 상태 머신 & 카메라 캘리브레이션
        self.align_state = 1
        self.current_z_before_turn = 0.0
    
        self.camera_matrix = None
        self.dist_coeffs = None
        self.distortion_k = 0.0006 
        self.offset_bias = 0.17
        self.tilt_tolerance = 0.1
        self.x_err_tolerance = 20.0

        # Waypoints
        self.waypoints = [
            (1.74, -2.6, math.pi, 4),
            (1.31, -2.6, math.pi, 3),
            (1.31, -0.91, 0.0, 2),
            (1.74, -0.91, 0.0, 1),
        ]
        self.start_pose = (0.0, 0.0, 0.0)
        self.target_dist_z = 0.55

        # ====================================================================
        # 3. 사람 추종 (Follow) 변수 설정
        # ====================================================================
        self.center_x = 160.0
        self.front_dist = float('inf')
        self.left_dist = float('inf')
        self.right_dist = float('inf')
        
        self.safe_dist = 0.40  
        self.target_area = 0.45 

        self.camera_hfov = 60.81        
        self.human_angle_range = None  

        self.target_human = None
        self.last_human_time = self.get_clock().now()

        # 회전(좌우) 및 직진(앞뒤) 오차 필터링
        self.filtered_error_x = 0.0
        self.filter_alpha = 0.50  
        self.filtered_error_area = 0.0
        self.filter_alpha_area = 0.20  

        # ====================================================================
        # 4. QoS 및 Publisher / Subscriber
        # ====================================================================
        qos_profile = QoSProfile(depth=1)
        qos_profile.durability = DurabilityPolicy.TRANSIENT_LOCAL

        # Publisher
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.capture_pub = self.create_publisher(CompressedImage, '/captured_image/compressed', 10)
        self.state_pub = self.create_publisher(String, 'robot_state', 10)
        self.ctrl_pub = self.create_publisher(String, 'controller_selector', qos_profile)

        # Subscriber (기존)
        self.sub_image = self.create_subscription(CompressedImage, '/sidecam/image_raw/compressed', self.image_callback, 10)
        self.sub_mode = self.create_subscription(String, 'robot_mode', self.mode_callback, 10)
        self.sub_remote = self.create_subscription(String, 'remote_control', self.remote_callback, 10)
        self.sub_battery = self.create_subscription(BatteryState, '/battery_state', self.battery_callback, 10)
        self.sub_select_ctrl = self.create_subscription(String, 'select_controller', self.select_controller_callback, 10)
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # Subscriber (Follow용 추가)
        self.scan_sub = self.create_subscription(LaserScan, '/scan', self.scan_callback, qos_profile_sensor_data)
        self.human_sub = self.create_subscription(HumanPositionArray, '/human_positions', self.human_callback, 1)
        self.info_sub = self.create_subscription(CameraInfo, '/sidecam/camera_info', self.camera_info_callback, 10)

        # 사람 추종 제어용 10Hz 타이머 (모드가 follow일 때만 구동)
        self.control_timer = self.create_timer(0.1, self.follow_timer_callback)

        self.get_logger().info("🤖 통합 로봇 제어 시스템 실행 완료 (수동 / 자율 / 추종 모드 대기 중)")
    
    def camera_info_callback(self, msg):
        if self.camera_matrix is None:
            self.camera_matrix = np.array(msg.k, dtype=np.float32).reshape((3, 3))
            self.dist_coeffs = np.array(msg.d, dtype=np.float32)
            self.get_logger().info("✅ SideCam 캘리브레이션 정보(/sidecam/camera_info) 수신 완료!")
        
    # ====================================================================
    # 공통 및 유틸리티 함수
    # ====================================================================
    def log_state(self, info_text):
        msg = String()
        msg.data = info_text
        self.state_pub.publish(msg)
        self.get_logger().info(f"[STATE] {info_text}")

    def select_controller_callback(self, msg):
        data = msg.data.strip().lower()
        ctrl_msg = String()
        if data in ['1', 'rpp', 'followpathfast']: ctrl_msg.data = "FollowPathFast"
        elif data in ['2', 'safe', 'followpathsafe']: ctrl_msg.data = "FollowPathSafe"
        elif data in ['3', 'ack', 'followpathack']: ctrl_msg.data = "FollowPathAck"
        else: ctrl_msg.data = msg.data
        self.ctrl_pub.publish(ctrl_msg)

    def cancel_active_goal(self):
        if self.goal_handle is not None:
            try:
                self.get_logger().info("파이썬 제어 Nav2 목표 취소 중...")
                self.goal_handle.cancel_goal_async()
            except Exception as e:
                self.get_logger().warn(f"Goal cancel 중 오류 발생: {e}")
            finally:
                self.goal_handle = None
        else:
            self.get_logger().info("외부(RViz) Nav2 목표 가로채기 및 강제 종료 실행")
            dummy_goal = NavigateToPose.Goal()
            dummy_goal.pose.header.frame_id = 'base_footprint' 
            dummy_goal.pose.pose.position.x = 0.0
            dummy_goal.pose.pose.position.y = 0.0
            dummy_goal.pose.pose.orientation.w = 1.0
            
            future = self.nav_client.send_goal_async(dummy_goal)
            def cancel_callback(f):
                handle = f.result()
                if handle.accepted:
                    handle.cancel_goal_async()
            future.add_done_callback(cancel_callback)

        stop_msg = Twist()
        for _ in range(5):
            self.cmd_pub.publish(stop_msg)
            time.sleep(0.01)
        self.get_logger().info("로봇 제동 완료")

    def stop_robot(self, force=False):
        cmd = Twist()
        if force:
            for _ in range(5): 
                self.cmd_pub.publish(cmd)
                time.sleep(0.05)
        else:
            self.cmd_pub.publish(cmd)

    def _navigate_home_thread(self):
        self.is_returning_home = True
        if self.send_nav_goal(*self.start_pose):
            self.log_state("home 도착 및 대기")
        self.is_returning_home = False

    def battery_callback(self, msg):
        if msg.percentage <= 20.0 and not self.is_battery_low:
            self.is_battery_low = True
            self.log_state("긴급 복귀 시작 (배터리 부족)")
            self.is_auto_running = False
            self.current_mode = "manual"
            self.cancel_active_goal()
            self.stop_robot(force=True)
            threading.Thread(target=self._navigate_home_thread, daemon=True).start()

    # ====================================================================
    # 모드 관리 및 리모컨 제어 (★ Follow 모드 병합)
    # ====================================================================
    def mode_callback(self, msg):
        if self.is_battery_low: return
        mode = msg.data.lower().strip()
        
        if mode != self.current_mode:
            self.is_returning_home = False 
            
            # 기존 모드 정리
            if self.current_mode == "auto":
                self.is_auto_running = False 
                self.cancel_active_goal()
                self.stop_robot(force=True)
            elif self.current_mode == "follow":
                self.stop_robot(force=True)
            
            # 새 모드 진입
            if mode == "auto":
                self.log_state("자율주행모드 전환")
                self.current_mode = mode
                if not self.is_auto_running:
                    self.is_auto_running = True
                    self.auto_thread = threading.Thread(target=self.run_auto_process)
                    self.auto_thread.daemon = True
                    self.auto_thread.start()
            
            elif mode == "follow":
                self.log_state("사람 추종(Follow) 모드 전환")
                self.current_mode = mode
                # Follow 모드 초기화
                self.target_human = None
                self.filtered_error_x = 0.0
                self.filtered_error_area = 0.0
                self.cancel_active_goal() # Nav2가 잡고있는 제어권 회수
                
            else: # manual
                self.log_state("수동모드 전환")
                self.current_mode = "manual"
                self.cancel_active_goal()
                self.stop_robot(force=True)

    def remote_callback(self, msg):
        data = msg.data.lower()
        
        if data == 's':
            self.is_auto_running = False  
            self.is_returning_home = False
            self.current_mode = "manual"
            self.log_state("즉각 정지 명령 수신: 목표 취소 및 제동 실행")
            self.cancel_active_goal()
            self.target_linear_vel = 0.0
            self.target_angular_vel = 0.0
            self.stop_robot(force=True)
            return

        if self.current_mode != "manual" or self.is_battery_low: 
            return

        LIN_STEP = 0.05
        ANG_STEP = 0.4
        
        if data == 'h':
            threading.Thread(target=self._navigate_home_thread, daemon=True).start()
            return
        
        if data.startswith('f'): self.target_linear_vel += LIN_STEP
        elif data.startswith('b'): self.target_linear_vel -= LIN_STEP
        elif data.startswith('l'): self.target_angular_vel += ANG_STEP
        elif data.startswith('r'): self.target_angular_vel -= ANG_STEP

        cmd = Twist()
        self.target_linear_vel = np.clip(self.target_linear_vel, -0.1, 0.1)
        self.target_angular_vel = np.clip(self.target_angular_vel, -0.8, 0.8)
        cmd.linear.x = self.target_linear_vel
        cmd.angular.z = self.target_angular_vel
        self.cmd_pub.publish(cmd)

    # ====================================================================
    # Follow Mode (사람 추종) 전용 콜백 모음
    # ====================================================================
    def get_min_valid_dist(self, ranges):
        valid_ranges = [r for r in ranges if 0.05 < r < 10.0]
        return min(valid_ranges) if valid_ranges else float('inf')

    def scan_callback(self, msg: LaserScan):
        total_samples = len(msg.ranges)
        if total_samples == 0: return
        
        idx_per_deg = total_samples / 360.0
        cleaned_ranges = list(msg.ranges)
        
        if self.human_angle_range is not None:
            min_h, max_h = self.human_angle_range
            for i in range(total_samples):
                deg = i / idx_per_deg
                if deg > 180.0: deg -= 360.0
                if min_h <= deg <= max_h:
                    cleaned_ranges[i] = float('inf')

        idx_30, idx_90 = int(30 * idx_per_deg), int(90 * idx_per_deg)
        idx_270, idx_330 = int(270 * idx_per_deg), int(330 * idx_per_deg)

        self.front_dist = self.get_min_valid_dist(cleaned_ranges[idx_330:total_samples] + cleaned_ranges[0:idx_30])
        self.left_dist = self.get_min_valid_dist(cleaned_ranges[idx_30:idx_90])
        self.right_dist = self.get_min_valid_dist(cleaned_ranges[idx_270:idx_330])

    def human_callback(self, msg: HumanPositionArray):
        if msg.humans:
            self.target_human = max(msg.humans, key=lambda h: h.width * h.height)
            self.last_human_time = self.get_clock().now()

    def follow_timer_callback(self):
        # ★ 현재 모드가 follow가 아니면 즉시 리턴 (다른 모드에 간섭 금지)
        if self.current_mode != "follow":
            return
            
        twist = Twist()
        now = self.get_clock().now()
        
        time_diff = (now - self.last_human_time).nanoseconds / 1e9 
        
        if self.target_human is None or time_diff > 0.5:
            self.target_human = None  
            self.human_angle_range = None 
            self.filtered_error_x = 0.0  
            self.filtered_error_area = 0.0  
            twist.linear.x = 0.0
            twist.angular.z = 0.0
            self.cmd_pub.publish(twist)  
            return

        target = self.target_human
        area = (target.width * target.height) / (320 * 240)
        error_x = target.x_center - self.center_x

        left_x = target.x_center - (target.width / 2.0)
        right_x = target.x_center + (target.width / 2.0)
        angle_left = - (left_x - self.center_x) / self.center_x * (self.camera_hfov / 2.0)
        angle_right = - (right_x - self.center_x) / self.center_x * (self.camera_hfov / 2.0)
        self.human_angle_range = (min(angle_left, angle_right) - 5.0, max(angle_left, angle_right) + 5.0)

        # 1. 회전(Z) 제어
        normalized_error_x = error_x / 160.0
        self.filtered_error_x = (self.filter_alpha * normalized_error_x) + ((1.0 - self.filter_alpha) * self.filtered_error_x)
        v_human_z = -1.4 * self.filtered_error_x if abs(self.filtered_error_x) > 0.05 else 0.0

        # 2. 직진(X) 제어
        error_area = self.target_area - area
        self.filtered_error_area = (self.filter_alpha_area * error_area) + ((1.0 - self.filter_alpha_area) * self.filtered_error_area)
        v_human_x = 1.5 * self.filtered_error_area 
        if abs(self.filtered_error_area) < 0.04: 
            v_human_x = 0.0

        if abs(self.filtered_error_x) > 0.4:
            v_human_x *= 0.2 

        # 3. 장애물 회피 제어
        v_avoid_x, v_avoid_z = 0.0, 0.0
        if self.front_dist < self.safe_dist:
            v_avoid_x = -1.2 * (self.safe_dist - self.front_dist)  
        if self.left_dist < self.safe_dist:
            v_avoid_z -= 1.5 * (self.safe_dist - self.left_dist)   
        if self.right_dist < self.safe_dist:
            v_avoid_z += 1.5 * (self.safe_dist - self.right_dist)

        # 4. 최종 결합 및 출력
        if v_human_z * v_avoid_z < 0:
            final_z = v_avoid_z + (v_human_z * 0.7) 
        else:
            final_z = v_human_z + v_avoid_z

        twist.linear.x = max(min(v_human_x + v_avoid_x, 0.18), -0.15)
        twist.angular.z = max(min(final_z, 1.82), -1.82)
        self.cmd_pub.publish(twist)

    # ====================================================================
    # Auto Mode (자율주행 & ArUco) 전용 콜백 모음
    # ====================================================================
    def image_callback(self, msg):
        self.latest_msg = msg
        if self.current_mode == "auto" and self.auto_step == "ALIGN" and self.is_auto_running:
            self.process_aruco_alignment(msg)

    def execute_move(self, linear, angular, duration):
        cmd = Twist()
        cmd.linear.x = float(linear)
        cmd.angular.z = float(angular)
        end_time = time.time() + duration
        while time.time() < end_time and rclpy.ok():
            if not self.is_auto_running or self.current_mode != "auto":
                self.stop_robot(force=True)
                return False 
            self.cmd_pub.publish(cmd)
            time.sleep(0.01)
        self.stop_robot()
        time.sleep(0.5)
        return True

    def process_aruco_alignment(self, msg):
        if self.current_wp_idx >= len(self.waypoints): return
        
        if self.camera_matrix is None or self.dist_coeffs is None:
            self.get_logger().warning("⏳ 카메라 캘리브레이션 정보 대기 중...")
            time.sleep(0.5)
            return
        
        if self.align_state == 2:
            self.log_state("거리 조절: 우회전(90도)")
            if self.execute_move(0.0, -0.5, 3.14):
                self.align_state = 3
            return
        elif self.align_state == 3:
            move_dist = self.current_z_before_turn - self.target_dist_z
            move_speed = 0.05 if move_dist > 0 else -0.05
            move_duration = abs(move_dist / move_speed)
            self.log_state(f"거리 조절: 전/후진 ({move_dist:.2f}m)")
            if self.execute_move(move_speed, 0.0, move_duration):
                self.align_state = 4
            return
        elif self.align_state == 4:
            self.log_state("거리 조절: 좌회전(90도)하여 복귀")
            if self.execute_move(0.0, 0.5, 3.14):
                self.align_state = 1 
            return

        target_id = self.waypoints[self.current_wp_idx][3]
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gamma = 1.5 
        lut = np.array(255 * (np.arange(256) / 255.0) ** gamma, dtype=np.uint8)
        gray = cv2.LUT(gray, lut)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = self.clahe.apply(gray)
        
        corners, ids, _ = self.detector.detectMarkers(gray)

        if ids is not None and target_id in ids:
            idx = np.where(ids == target_id)[0][0]
            c = corners[idx][0]
            success, rvec, tvec = cv2.solvePnP(
                np.array([[-0.04, 0.04, 0], [0.04, 0.04, 0], [0.04, -0.04, 0], [-0.04, -0.04, 0]], dtype=np.float32),
                c, self.camera_matrix, self.dist_coeffs
            )
            if success:
                rmat, _ = cv2.Rodrigues(rvec)
                raw_tilt = -rmat[0, 2]
                if rmat[2, 2] < 0: raw_tilt = -raw_tilt
                pixel_x_err = (int(np.mean(c[:, 0])) - 320)
                calibrated_tilt = raw_tilt + (pixel_x_err * self.distortion_k) - self.offset_bias
                dist_z = tvec[2][0]

                if self.align_state == 1:
                    if abs(calibrated_tilt) < self.tilt_tolerance and abs(pixel_x_err) < self.x_err_tolerance:
                        self.stop_robot()
                        if abs(dist_z - self.target_dist_z) <= 0.05:
                            self.align_state = 5
                        else:
                            self.current_z_before_turn = dist_z
                            self.align_state = 2
                    else:
                        cmd = Twist()
                        cmd.angular.z = calibrated_tilt * 0.4
                        cmd.linear.x = np.clip(-pixel_x_err * 0.0005, -0.05, 0.05)
                        self.cmd_pub.publish(cmd)
                elif self.align_state == 5:
                    self.stop_robot()
                    self.align_done = True
        else:
            if self.align_state == 1:
                self.stop_robot()

    def send_nav_goal(self, x, y, yaw):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        siny_cosp = math.sin(yaw * 0.5)
        cosy_cosp = math.cos(yaw * 0.5)
        goal.pose.pose.orientation.z = siny_cosp
        goal.pose.pose.orientation.w = cosy_cosp

        if not self.nav_client.wait_for_server(timeout_sec=5.0): return False
        future = self.nav_client.send_goal_async(goal)

        while rclpy.ok() and not future.done():
            if not self.is_auto_running and not self.is_returning_home:
                return False
            time.sleep(0.1)

        self.goal_handle = future.result()
        if not self.goal_handle.accepted: return False

        result_future = self.goal_handle.get_result_async()

        while rclpy.ok() and not result_future.done():
            if not self.is_auto_running and not self.is_returning_home:
                self.log_state("주행 중 중단: 즉각 제동 실행")
                self.cancel_active_goal() 
                self.stop_robot(force=True)
                return False
            time.sleep(0.1)

        result = result_future.result()
        return result.status == 4 

    def run_auto_process(self):
        self.log_state("자율주행 프로세스 가동")
        for i in range(self.current_wp_idx, len(self.waypoints)):
            if not self.is_auto_running: break
            
            self.current_wp_idx = i
            x, y, yaw, marker_id = self.waypoints[i]

            self.auto_step = "NAV"
            if not self.send_nav_goal(x, y, yaw):
                if not self.is_auto_running: break
                continue

            self.auto_step = "ALIGN"
            self.align_done = False
            self.align_state = 1
            align_start_time = time.time()
            
            while rclpy.ok() and not self.align_done:
                if not self.is_auto_running: break
                
                if time.time() - align_start_time > 20.0:
                    self.log_state(f"WP {i+1} 정렬 타임아웃! 다음 지점으로 이동합니다.")
                    self.stop_robot()
                    break 
                time.sleep(0.1)

            if not self.is_auto_running: break

            self.auto_step = "DONE"
            self.log_state(f"WP {i+1} 사진 촬영 중...")
            self.publish_capture_image()
            
            for _ in range(50): 
                if not self.is_auto_running: break
                time.sleep(0.1)
                
            self.log_state(f"WP {i+1} 촬영 종료, 다음 WP 확인 중...") 
            
            if not self.is_auto_running: 
                self.log_state("촬영 후 주행 중단됨")
                break

        if self.is_auto_running and self.current_wp_idx >= len(self.waypoints) - 1:
            self.log_state("모든 임무 완료: Home으로 복귀")
            self.is_returning_home = True
            self.current_wp_idx = 0
            self.send_nav_goal(*self.start_pose)
            self.is_returning_home = False
            self.current_mode = "manual"
            
        self.is_auto_running = False
        self.stop_robot()

    def publish_capture_image(self):
        if self.latest_msg is None: return
        np_arr = np.frombuffer(self.latest_msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        info_text = f"WP: {self.current_wp_idx + 1} DONE"
        cv2.putText(frame, info_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
        _, buffer = cv2.imencode('.jpg', frame)
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.format = "jpeg"
        msg.data = buffer.tobytes()
        self.capture_pub.publish(msg)

def main():
    rclpy.init()
    node = IntegratedRobotControl()
    
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
