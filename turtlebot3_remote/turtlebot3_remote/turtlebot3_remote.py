import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, DurabilityPolicy
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped, Twist
from sensor_msgs.msg import CompressedImage, BatteryState
from std_msgs.msg import String

import cv2
import numpy as np
import math
import time
import threading

class IntegratedRobotControl(Node):
    def __init__(self):
        super().__init__('integrated_robot_control')

        # 1. ArUco 및 이미지 처리 설정 (중복 제거 및 최적화)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        self.parameters = cv2.aruco.DetectorParameters()
        
        # 조명 대응을 위한 이진화 윈도우 조절 (인식률 향상)
        self.parameters.adaptiveThreshWinSizeMin = 3
        self.parameters.adaptiveThreshWinSizeMax = 23
        self.parameters.adaptiveThreshWinSizeStep = 10
        
        # 🌟 추가: 빛 번짐 대응을 위해 이진화 임계값 상향 (기본값 7 -> 12)
        # 값이 높을수록 어중간한 빛 번짐(회색)을 테두리로 착각하지 않고 무시합니다.
        self.parameters.adaptiveThreshConstant = 12
        
        # 코너 정밀도 향상
        self.parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        
        # 디텍터와 CLAHE 객체 미리 생성 (매 프레임 생성 방지)
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.parameters)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # 2. 상태 관리 변수 (기존 유지)
        self.current_mode = "manual"
        self.auto_step = "NAV"
        self.current_wp_idx = 0
        self.align_done = False
        self.latest_msg = None
        self.goal_handle = None
        self.is_battery_low = False
        self.is_returning_home = False 

        # 3. 자율주행 스레드 관리 변수 (기존 유지)
        self.auto_thread = None
        self.is_auto_running = False

        # 4. 수동 조종 속도 누적 변수 (기존 유지)
        self.target_linear_vel = 0.0
        self.target_angular_vel = 0.0

        # 5. 정밀 정렬 상태 머신 (기존 유지)
        self.align_state = 1
        self.current_z_before_turn = 0.0

        # 6. Waypoints 및 목표 거리 (기존 유지)
        self.waypoints = [
            (1.74, -2.6, math.pi, 4),
            (1.31, -2.6, math.pi, 3),
            (1.31, -0.91, 0.0, 2),
            (1.74, -0.91, 0.0, 1),
        ]
        self.start_pose = (0.0, 0.0, 0.0)
        self.target_dist_z = 0.55

        # 7. QoS 및 통신 (기존 유지)
        qos_profile = QoSProfile(depth=1)
        qos_profile.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.capture_pub = self.create_publisher(CompressedImage, '/captured_image/compressed', 10)
        self.state_pub = self.create_publisher(String, 'robot_state', 10)
        self.ctrl_pub = self.create_publisher(String, 'controller_selector', qos_profile)

        self.sub_image = self.create_subscription(CompressedImage, '/sidecam/image_raw/compressed', self.image_callback, 10)
        self.sub_mode = self.create_subscription(String, 'robot_mode', self.mode_callback, 10)
        self.sub_remote = self.create_subscription(String, 'remote_control', self.remote_callback, 10)
        self.sub_battery = self.create_subscription(BatteryState, '/battery_state', self.battery_callback, 10)
        self.sub_select_ctrl = self.create_subscription(String, 'select_controller', self.select_controller_callback, 10)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # 8. 카메라 캘리브레이션 및 오프셋 변수 (기존 유지)
        self.camera_matrix = np.array([[600.0, 0, 320.0], [0, 600.0, 240.0], [0, 0, 1]], dtype=np.float32)
        self.dist_coeffs = np.zeros((5, 1))
        
        self.distortion_k = 0.0006 
        self.offset_bias = 0.17
        self.tilt_tolerance = 0.1
        self.x_err_tolerance = 20.0

        self.get_logger().info("농작물 관리 시스템 실행 (조명 빛번짐 억제 패치 완료)")
        
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
        """Nav2 목표를 전역적으로 가로채어 취소하고 즉시 정지합니다."""
        # 1. 파이썬 스크립트가 직접 관리하는 목표가 있는 경우 (자율주행 모드 등)
        if self.goal_handle is not None:
            try:
                self.get_logger().info("파이썬 제어 Nav2 목표 취소 중...")
                self.goal_handle.cancel_goal_async()
            except Exception as e:
                self.get_logger().warn(f"Goal cancel 중 오류 발생: {e}")
            finally:
                self.goal_handle = None
                
        # 2. 파이썬이 관리하는 목표가 없을 때 (RViz 등 외부에서 보낸 목표가 있을 때)
        else:
            self.get_logger().info("외부(RViz) Nav2 목표 가로채기 및 강제 종료 실행")
            # 현재 위치(로봇 중심)를 새로운 목표로 쏴서 기존 목표를 무효화(Preempt) 시킴
            dummy_goal = NavigateToPose.Goal()
            dummy_goal.pose.header.frame_id = 'base_footprint' 
            dummy_goal.pose.pose.position.x = 0.0
            dummy_goal.pose.pose.position.y = 0.0
            dummy_goal.pose.pose.orientation.w = 1.0
            
            # 새 목표 전역 전송
            future = self.nav_client.send_goal_async(dummy_goal)
            
            # 새 목표가 접수되자마자 즉시 취소시켜서 로봇을 그 자리에 고정
            def cancel_callback(f):
                handle = f.result()
                if handle.accepted:
                    handle.cancel_goal_async()
            future.add_done_callback(cancel_callback)

        # 3. 물리적 제동 명령 (cmd_vel 0 전송)
        stop_msg = Twist()
        # 속도를 0으로 만들어 확실히 멈춤
        for _ in range(5):
            self.cmd_pub.publish(stop_msg)
            time.sleep(0.01)
            
        self.get_logger().info("로봇 제동 완료")

    def stop_robot(self, force=False):
        """🌟 강제 정지 기능 추가 (Nav2 잔여 속도 덮어쓰기)"""
        cmd = Twist()
        if force:
            for _ in range(5): # Nav2가 감속하는 동안 강제로 0 속도 주입
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
            self.log_state("긴급 복귀 시작")
            self.is_auto_running = False
            self.current_mode = "manual"
            self.cancel_active_goal()
            self.stop_robot(force=True)
            threading.Thread(target=self._navigate_home_thread, daemon=True).start()

    def mode_callback(self, msg):
        if self.is_battery_low: return
        mode = msg.data.lower().strip()
        if mode != self.current_mode:
            self.is_returning_home = False 
            if mode == "auto":
                self.log_state("자율주행모드 전환")
                self.current_mode = mode
                if not self.is_auto_running:
                    self.is_auto_running = True
                    self.auto_thread = threading.Thread(target=self.run_auto_process)
                    self.auto_thread.daemon = True
                    self.auto_thread.start()
            else:
                self.log_state("수동모드 전환")
                self.current_mode = mode
                self.is_auto_running = False 
                self.cancel_active_goal()
                self.stop_robot(force=True)

    def remote_callback(self, msg):
        data = msg.data.lower()
        
        # 🌟 정지 명령('s') 수신 시 처리
        if data == 's':
            # 1. 모든 주행 플래그를 꺼서 다른 스레드(send_nav_goal 등)도 멈추게 함
            self.is_auto_running = False  
            self.is_returning_home = False
            self.current_mode = "manual"
            
            # 2. 로그 출력 (send_nav_goal 스타일과 통일)
            self.log_state("즉각 정지 명령 수신: 목표 취소 및 제동 실행")
            
            # 3. Nav2 액션 목표 취소 (이것이 호출되면 send_nav_goal의 루프가 종료됨)
            self.cancel_active_goal()
            
            # 4. 물리적 강제 제동 및 속도 변수 초기화
            self.target_linear_vel = 0.0
            self.target_angular_vel = 0.0
            self.stop_robot(force=True)
            
            # 명령 처리가 끝났으므로 리턴
            return

        # 수동 모드가 아니거나 배터리가 낮으면 아래의 조종 로직은 무시
        if self.current_mode != "manual" or self.is_battery_low: 
            return

        # --- 수동 조종 로직 (f, b, l, r) ---
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
        
        # Blind States (2, 3, 4) - 기존 로직 유지
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

        # --- 이미지 처리 및 인식 부분 수정 ---
        target_id = self.waypoints[self.current_wp_idx][3]
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # 1. 그레이스케일 변환
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 🌟 2. 감마 교정 (빛 번짐 해결의 핵심)
        # 픽셀값을 비선형적으로 깎아내어 하얗게 날아간(Overexposed) 테두리를 선명하게 복원합니다.
        gamma = 1.5 # 값이 1.0보다 클수록 어두워집니다. 빛번짐이 심하다면 2.0까지 올려보세요.
        lut = np.array(255 * (np.arange(256) / 255.0) ** gamma, dtype=np.uint8)
        gray = cv2.LUT(gray, lut)
        
        # 🌟 3. 가우시안 블러 (노이즈 필터링)
        # 빛 번짐 경계면에 생긴 픽셀 노이즈를 부드럽게 뭉개서 오작동을 막습니다.
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        
        # 4. CLAHE 조명 보정 적용
        gray = self.clahe.apply(gray)
        
        # 5. 마커 검출
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

        # 1. Goal 전송 대기
        while rclpy.ok() and not future.done():
            if not self.is_auto_running and not self.is_returning_home:
                return False
            time.sleep(0.1)

        self.goal_handle = future.result()
        if not self.goal_handle.accepted: return False

        result_future = self.goal_handle.get_result_async()

        # 2. 이동 중 정지 명령 지속적 감시
        while rclpy.ok() and not result_future.done():
            if not self.is_auto_running and not self.is_returning_home:
                self.log_state("주행 중 중단: 즉각 제동 실행")
                self.cancel_active_goal() 
                self.stop_robot(force=True)
                return False
            time.sleep(0.1)

        result = result_future.result()
        return result.status == 4 # SUCCEEDED

    def run_auto_process(self):
        self.log_state("자율주행 프로세스 가동")
        for i in range(self.current_wp_idx, len(self.waypoints)):
            if not self.is_auto_running: break
            
            self.current_wp_idx = i
            x, y, yaw, marker_id = self.waypoints[i]

            # (1) NAV Step
            self.auto_step = "NAV"
            if not self.send_nav_goal(x, y, yaw):
                if not self.is_auto_running: break
                continue

            # (2) ALIGN Step
            self.auto_step = "ALIGN"
            self.align_done = False
            self.align_state = 1
            align_start_time = time.time()
            
            while rclpy.ok() and not self.align_done:
                if not self.is_auto_running: break
                
                # 🌟 [개선] 정렬 과정에서 60초 넘게 마커를 못 찾으면 다음 WP로 스킵 (무한 정지 방지)
                if time.time() - align_start_time > 20.0:
                    self.log_state(f"WP {i+1} 정렬 타임아웃! 다음 지점으로 이동합니다.")
                    self.stop_robot()
                    break 
                
                time.sleep(0.1)

            if not self.is_auto_running: break

            # (3) DONE Step (촬영)
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
        # 🌟 메인 함수에서는 깨끗하게 rclpy.spin만 수행하여 모든 토픽/액션 콜백을 원활하게 처리합니다.
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()
