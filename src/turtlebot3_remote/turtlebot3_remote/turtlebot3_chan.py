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
from std_srvs.srv import Trigger
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue

import cv2
import numpy as np
import math
import time
import threading
import yaml
import os
import json


class IntegratedRobotControl(Node):
    def __init__(self):
        super().__init__('integrated_robot_control')
        
        self.is_first_callback = True
        self.publish_param_pub = self.create_publisher(String, '/publish_param', 10)
        self.current_active_controller = "RPP"
        
        self.config_path = os.path.expanduser('~/remote_ws/src/turtlebot3_remote/yaml/param_config.yaml')
        self.create_subscription(String, '/save_params', self.save_topic_callback, 10)
        # 파일 저장 서비스 생성
        self.srv_save = self.create_service(Trigger, '/save_params', self.save_params_callback)
        
        self.cli_controller = self.create_client(SetParameters, '/controller_server/set_parameters')
        self.cli_costmap = self.create_client(SetParameters, '/local_costmap/local_costmap/set_parameters')
        
        # ====================================================================
        # [신규 추가] JSON 동적 시퀀스 및 웨이포인트 관리 변수
        # ====================================================================
        self.sequence_list = []      # JSON에서 파싱한 주행 순서 리스트 (예: [1, 2, 3, 4, 8, 5, 6, 7])
        self.waypoint_dict = {}      # ID를 Key로 가지는 웨이포인트 딕셔너리 구조
        self.current_seq_idx = 0     # 현재 sequence_list의 몇 번째 인덱스를 수행 중인지 추적
        self.current_detected_marker_id = None # 정렬 과정에서 최종 인식된 마커 ID 저장용
        
        # ====================================================================
        # [신규 추가] JSON 스케줄 예약 제어 변수 및 구독자
        # ====================================================================
        self.schedule_plans = []          # 수신된 전체 스케줄 플랜 리스트 저장
        self.last_triggered_time = (None, None) # 동일 시간(시, 분) 중복 실행 방지용
        
        # /json_schedule 토픽 구독자 등록
        self.sub_json_schedule = self.create_subscription(String, 'json_schedule', self.json_schedule_callback, 10)
        
        # 10초마다 현재 시간을 확인하여 예약 작업을 감시하는 타이머 생성
        self.schedule_timer = self.create_timer(10.0, self.check_schedule_timer_callback)        
        
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
        self.is_manual_moving = False

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
        self.tilt_tolerance = 0.08
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
        self.filter_alpha = 0.40  
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
        self.log_pub = self.create_publisher(String, 'robot_log', 10) # [추가] DB 저장용 로그 토픽
        self.ctrl_pub = self.create_publisher(String, 'controller_selector', qos_profile)

        # [추가] GUI의 단일 목표 지점 이동(수동 모드)을 감지하기 위한 구독자
        from geometry_msgs.msg import PoseStamped
        self.goal_sub = self.create_subscription(PoseStamped, '/goal_pose', self.manual_goal_callback, 10)

        # 상태 및 로그 도배 방지용 변수
        self.last_state = ""
        self.last_log = ""
        
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
        self.sub_json_sequence = self.create_subscription(String, 'json_sequence', self.json_sequence_callback, 10)

        # 사람 추종 제어용 10Hz 타이머 (모드가 follow일 때만 구동)
        self.control_timer = self.create_timer(0.1, self.follow_timer_callback)

        self.get_logger().info("🤖 통합 로봇 제어 시스템 실행 완료 (수동 / 자율 / 추종 모드 대기 중)")
        
        threading.Thread(target=self._initial_param_loader, daemon=True).start()
    
    def json_schedule_callback(self, msg):
        try:
            data = json.loads(msg.data)
            # 수신된 전체 플랜 리스트를 멤버 변수에 저장
            self.schedule_plans = data
            self.get_logger().info(f"📅 새 스케줄 데이터 수신 완료! 총 {len(self.schedule_plans)}개의 플랜 관리 시작")
            
            # 디버깅용 로그 출력
            for plan in self.schedule_plans:
                name = plan.get("name", "무명 플랜")
                schedules = plan.get("schedule", [])
                if schedules:
                    times_str = ", ".join([f"{s['hour']:02d}:{s['minute']:02d}" for s in schedules])
                    self.get_logger().info(f" └─ [{name}] 예약 시간: {times_str}")
                else:
                    self.get_logger().info(f" └─ [{name}] 예약 스케줄 없음 (자동 실행 제외)")
                    
        except Exception as e:
            self.get_logger().error(f"❌ JSON 스케줄 파싱 중 에러 발생: {e}")
            
    def check_schedule_timer_callback(self):
        # 🚨 [신규 추가] 현재 모드가 auto가 아니면 시간이 되어도 스케줄을 완전히 무시함
        if self.current_mode != "auto":
            return
            
        # 로봇이 이미 무언가(자율주행, 수동 이동, 복귀 등)를 하고 있다면 안전을 위해 스킵
        if self.is_auto_running or self.is_manual_moving or self.is_returning_home:
            return
            
        # 현재 시스템 시간 가져오기
        from datetime import datetime
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        
        # 1분 안에 타이머가 여러 번(10초 주기이므로 6번) 돌 때 중복 실행되는 것을 절대 방지
        if self.last_triggered_time == (current_hour, current_minute):
            return
            
        # 등록된 플랜들을 순회하며 검사
        for plan in self.schedule_plans:
            schedules = plan.get("schedule", [])
            if not schedules: # schedule 리스트가 비어있으면 (예: 장애물 회피) 무시하고 넘어감
                continue
                
            for s in schedules:
                # 현재 시각과 예약 시각이 일치하는지 확인
                if s.get("hour") == current_hour and s.get("minute") == current_minute:
                    self.get_logger().info(f"⏰ [스케줄 알람] '{plan['name']}' 작업 시작 시간 도달! ({current_hour:02d}:{current_minute:02d})")
                    
                    # 중복 실행 방지 마킹
                    self.last_triggered_time = (current_hour, current_minute)
                    
                    # 1. 해당 플랜의 시퀀스 및 웨이포인트 데이터를 핵심 동적 변수에 주입
                    self.sequence_list = plan.get("sequence", [])
                    waypoints_raw = plan.get("waypoint", [])
                    self.waypoint_dict = {wp["id"]: wp for wp in waypoints_raw}
                    self.current_seq_idx = 0
                    
                    # 2. 모드를 auto(자율주행)로 강제 변환 후 기존 자율주행 프로세스 구동
                    self.current_mode = "auto"
                    self.write_log(f"스케줄 구동: {plan['name']}")
                    self.set_state("대기")
                    
                    self.is_auto_running = True
                    self.auto_thread = threading.Thread(target=self.run_auto_process)
                    self.auto_thread.daemon = True
                    self.auto_thread.start()
                    
                    return # 하나의 정해진 시간에는 하나의 플랜만 실행하고 콜백 종료
            
    def _initial_param_loader(self):
        """Nav2 서버가 완전히 켜질 때까지 기다렸다가 YAML 초기값을 쏴주는 함수"""
        self.get_logger().info("⏳ Nav2 파라미터 서버가 켜질 때까지 대기합니다...")
        
        # Nav2 서비스가 준비될 때까지 무한 대기 (백그라운드이므로 메인 로봇 제어는 멈추지 않음)
        self.cli_controller.wait_for_service()
        self.cli_costmap.wait_for_service()
        
        # 서비스가 켜졌더라도 내부 초기화 세팅이 끝날 때까지 3초 정도 안전하게 더 기다립니다.
        time.sleep(3.0) 
        
        self.get_logger().info("✅ Nav2 서버 준비 완료! 저장된 YAML 파라미터를 강제 주입합니다.")
        self.apply_stored_params("RPP")
    
    def json_sequence_callback(self, msg):
        try:
            data = json.loads(msg.data)
            self.sequence_list = data.get("sequence", [])
            waypoints_raw = data.get("waypoint", [])
            
            self.waypoint_dict = {wp["id"]: wp for wp in waypoints_raw}
            self.current_seq_idx = 0
            self.get_logger().info(f"✅ 새 시퀀스 수신 완료! 총 {len(self.sequence_list)}개의 목표 지점 순차 주행 대기")
            
            # 🚨 [수정] auto 모드이고 대기 중일 때만 즉시 실행
            if self.current_mode == "auto":
                if not self.is_auto_running:
                    self.is_auto_running = True
                    # (아래 4번에서 함수 이름을 변경합니다)
                    threading.Thread(target=self._immediate_sequence_process, daemon=True).start()
                else:
                    self.get_logger().warn("⚠️ 이미 자율주행 작업이 실행 중입니다. 시퀀스를 무시합니다.")
            else:
                self.get_logger().warn("⚠️ 현재 auto 모드가 아닙니다. 시퀀스 명령을 무시합니다.")
                
        except Exception as e:
            self.get_logger().error(f"❌ JSON 시퀀스 파싱 중 에러 발생: {e}")
    
    def _immediate_sequence_process(self):
        """auto 모드에서 수신된 JSON 시퀀스 좌표들로 즉시 이동 (홈 복귀 없음)"""
        self.set_state("이동")
        self.write_log("시퀀스 목표 이동 시작")

        for i in range(len(self.sequence_list)):
            # 🚨 모드가 auto에서 바뀌거나 리모컨 정지(s)가 들어오면 즉시 중단
            if self.current_mode != "auto" or not self.is_auto_running:
                break
                
            wp_id = self.sequence_list[i]
            wp = self.waypoint_dict.get(wp_id)
            if wp is None: continue

            x = wp['x']
            y = wp['y']
            wp_type = wp['type']
            yaw = wp['theta'] if wp_type in ['d', 'ms'] else 0.0

            self.auto_step = "NAV"
            self.set_state("wp 이동")
            self.write_log(f"📍 [시퀀스 즉시 실행] {i+1}/{len(self.sequence_list)} 번째 지점 이동 중 (ID: {wp_id})")
            
            if not self.send_nav_goal(x, y, yaw):
                self.get_logger().warn(f"❌ ID {wp_id} 이동 실패 또는 취소됨")
                break
                
            if wp_type == "ud":
                self.write_log(f"ID {wp_id} (ud) 도착 완료")
                time.sleep(0.5)
            elif wp_type == "d":
                self.write_log(f"ID {wp_id} (d) 방향 정렬 완료")
                time.sleep(0.5)
            elif wp_type == "ms":
                self.auto_step = "ALIGN"
                self.set_state("마커 정렬")
                self.write_log(f"🔍 ID {wp_id} (ms) 카메라 기반 마커 정렬 시작")
                
                self.align_done = False
                self.align_state = 1
                align_start_time = time.time()
                
                while rclpy.ok() and not self.align_done:
                    if self.current_mode != "auto" or not self.is_auto_running: 
                        break
                    if time.time() - align_start_time > 30.0:
                        self.write_log(f"⚠️ ID {wp_id} 정렬 시간 초과 (30s)")
                        self.stop_robot()
                        break 
                    time.sleep(0.1)

                if self.current_mode != "auto" or not self.is_auto_running: 
                    break

                self.auto_step = "DONE"
                self.set_state("마커 촬영")
                
                detected_id = self.current_detected_marker_id if self.current_detected_marker_id is not None else wp_id
                self.write_log(f"📸 마커 {detected_id}번 ID 기반 촬영 데이터 전송 시작")
                
                for capture_idx in range(10):
                    if self.current_mode != "auto" or not self.is_auto_running: 
                        break
                    self.publish_capture_image(detected_id)
                    time.sleep(0.3) 
                
                self.write_log(f"✅ ID {wp_id} 촬영 완료 및 종료")
                time.sleep(0.5)

        # 루프를 무사히 다 마쳤거나 끊기지 않았을 때 대기 상태로 전환
        if self.is_auto_running:
            self.set_state("대기")
            self.write_log("모든 시퀀스 완료 및 대기")
            self.is_auto_running = False
                   
    def save_topic_callback(self, msg):
        self.write_log("파라미터 변경") # [추가] 파라미터 변경 로그
        data = json.loads(msg.data)       
        self.current_active_controller = data['controller']
        
        # YAML 업데이트 및 전체 상태 발행
        self.update_yaml_and_publish_all(
            data['controller'], 
            data['speed'], 
            data['inflation'], 
            data['tolerance']
        )
        
    def save_params_callback(self, request, response):
        """GUI에서 보낸 JSON 문자열 데이터를 받아 YAML에 저장"""
        try:
            # request.request는 Trigger 서비스이므로 사실 데이터 전달이 어렵습니다.
            # 가장 깔끔한 방법은 별도 토픽으로 데이터를 받는 것입니다.
            # 여기서는 편의상 로직만 보여드립니다. (데이터 전달은 3단계 참고)
            response.success = True
            response.message = "Saved"
        except Exception as e:
            response.success = False
            response.message = str(e)
        return response
    
    def update_yaml_file(self, controller, speed, inflation, tolerance):
        """실제 파일 I/O 담당"""
        if not os.path.exists(self.config_path):
            data = {'controllers': {}}
        else:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f) or {'controllers': {}}

        data['controllers'][controller] = {
            'speed': float(speed),
            'inflation': float(inflation),
            'tolerance': float(tolerance)
        }
        with open(self.config_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        self.get_logger().info(f"💾 YAML 저장 완료: {controller}")
            
    def apply_stored_params(self, controller_key):
        """YAML 파일에서 특정 컨트롤러 설정을 읽어와 Nav2 서비스로 실시간 주입합니다."""
        if not os.path.exists(self.config_path):
            self.get_logger().warn("⚠️ 저장된 YAML 파라미터 파일이 존재하지 않아 기본값을 유지합니다.")
            return
            
        try:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f)
                
            if not data or 'controllers' not in data or controller_key not in data['controllers']:
                return
                
            params = data['controllers'][controller_key]
            speed = float(params.get('speed', 0.24))
            inflation = float(params.get('inflation', 0.55))
            tolerance = float(params.get('tolerance', 0.25))
            
            self.get_logger().info(f"🔄 [YAML 로드] {controller_key} 설정을 Nav2에 동적 적용합니다. (속도: {speed}, 회피: {inflation}, 오차: {tolerance})")
            
            # 컨트롤러 플러그인 접두사 매핑
            plugin_prefix = "FollowPathFast"
            if controller_key == "SAFE": plugin_prefix = "FollowPathSafe"
            elif controller_key == "ACK": plugin_prefix = "FollowPathAck"
            
            # 1. Controller Server 파라미터 설정 요청
            req_ctrl = SetParameters.Request()
            req_ctrl.parameters = [
                Parameter(name=f"{plugin_prefix}.desired_linear_vel", value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=speed)),
                Parameter(name="general_goal_checker.xy_goal_tolerance", value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=tolerance))
            ]
            if self.cli_controller.wait_for_service(timeout_sec=1.0):
                self.cli_controller.call_async(req_ctrl)
                
            # 2. Local Costmap 파라미터 설정 요청
            req_costmap = SetParameters.Request()
            req_costmap.parameters = [
                Parameter(name="inflation_layer.inflation_radius", value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=inflation))
            ]
            if self.cli_costmap.wait_for_service(timeout_sec=1.0):
                self.cli_costmap.call_async(req_costmap)
                
        except Exception as e:
            self.get_logger().error(f"⚠️ YAML 파라미터 초기화 적용 중 오류 발생: {e}")
    
    def camera_info_callback(self, msg):
        if self.camera_matrix is None:
            self.camera_matrix = np.array(msg.k, dtype=np.float32).reshape((3, 3))
            self.dist_coeffs = np.array(msg.d, dtype=np.float32)
            self.get_logger().info("✅ SideCam 캘리브레이션 정보(/sidecam/camera_info) 수신 완료!")
        
    # ====================================================================
    # 공통 및 유틸리티 함수
    # ====================================================================
    def set_state(self, state_str):
        """실시간 대시보드 표출용 (상태가 바뀔 때만 발행)"""
        if self.last_state != state_str:
            msg = String()
            msg.data = state_str
            self.state_pub.publish(msg)
            self.last_state = state_str
            self.get_logger().info(f"[STATE] {state_str}")

    def write_log(self, log_str):
        """DB 저장용 로그 (연속 도배 방지되나, 파라미터 변경 등은 예외 허용 가능)"""
        if self.last_log != log_str or log_str == "파라미터 변경":
            msg = String()
            msg.data = log_str
            self.log_pub.publish(msg)
            self.last_log = log_str
            self.get_logger().info(f"[LOG] {log_str}")

    def manual_goal_callback(self, msg):
        """수동 모드에서 GUI로 목표 지점을 보냈을 때 감지 및 도착 확인"""
        # 아래 코드가 위 def 라인보다 4칸 더 들여쓰기 되어야 합니다.
        if self.current_mode == "manual":
            # 도착 상태를 기다리기 위해 스레드 실행
            threading.Thread(target=self._manual_goal_process, args=(msg,), daemon=True).start()
    
    
    def _manual_goal_process(self, msg):
        # 아래 코드들도 마찬가지로 들여쓰기를 맞춰주세요.
        self.is_manual_moving = True
        self.set_state("이동")
        self.write_log("목표 이동")
        
        x = msg.pose.position.x
        y = msg.pose.position.y
        z = msg.pose.orientation.z
        w = msg.pose.orientation.w
        yaw = math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)

        if self.send_nav_goal(x, y, yaw):
            self.set_state("대기")
            self.write_log("도착 및 대기")
            
        #self.is_manual_moving = False
            
    def select_controller_callback(self, msg):
        data = msg.data.strip().lower()
        ctrl_msg = String()
        
        # [수정된 부분] 변수를 미리 초기화해야 에러가 나지 않습니다.
        selected_ctrl_key = None 
        
        if data in ['1', 'rpp', 'followpathfast']:
            ctrl_msg.data = "FollowPathFast"
            selected_ctrl_key = "RPP"
            
        elif data in ['2', 'safe', 'followpathsafe']: 
            ctrl_msg.data = "FollowPathSafe"
            selected_ctrl_key = "SAFE" # [추가된 부분]
            
        elif data in ['3', 'ack', 'followpathack']: 
            ctrl_msg.data = "FollowPathAck"
            selected_ctrl_key = "ACK"  # [추가된 부분]
            
        else: 
            ctrl_msg.data = msg.data
            
        self.ctrl_pub.publish(ctrl_msg)
        
        if selected_ctrl_key:
            # [수정] 컨트롤러 로그 단순화 매핑
            if selected_ctrl_key == "RPP": self.write_log("fast 컨트롤러")
            elif selected_ctrl_key == "SAFE": self.write_log("safe 컨트롤러")
            elif selected_ctrl_key == "ACK": self.write_log("stable 컨트롤러")
            
            # 1. 내부 변수 업데이트
            self.current_active_controller = selected_ctrl_key
            # 2. YAML에서 파라미터 가져와서 Nav2에 적용
            self.apply_stored_params(selected_ctrl_key)
            # 3. 컨트롤러가 바뀌었으므로 YAML에 'current_controller' 기록 후 전체 상태 발행
            self.update_yaml_and_publish_all(None, None, None, None) # 파라미터 변경 없이 컨트롤러만 갱신

    def update_yaml_and_publish_all(self, controller, speed, inflation, tolerance):
        """YAML 파일을 갱신하고(선택적), 갱신된 전체 데이터를 /publish_param 으로 발행합니다."""
        # 1. 파일 읽기 (없으면 빈 구조 생성)
        if not os.path.exists(self.config_path):
            data = {'current_controller': self.current_active_controller, 'controllers': {}}
        else:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f) or {'current_controller': self.current_active_controller, 'controllers': {}}

        # 2. 파라미터 업데이트 (controller 인자가 전달된 경우에만)
        if controller is not None:
            if 'controllers' not in data:
                data['controllers'] = {}
            data['controllers'][controller] = {
                'speed': float(speed),
                'inflation': float(inflation),
                'tolerance': float(tolerance)
            }
            
        # 3. 현재 컨트롤러 상태 업데이트
        data['current_controller'] = self.current_active_controller

        # 4. 파일 쓰기
        with open(self.config_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        self.get_logger().info(f"💾 YAML 갱신 완료 (현재 모드: {self.current_active_controller})")

        # 5. [핵심] 전체 데이터를 JSON으로 변환하여 /publish_param 토픽 발행
        msg = String()
        msg.data = json.dumps(data)
        self.publish_param_pub.publish(msg)
        self.get_logger().info("📡 전체 설정 데이터를 /publish_param 으로 발행했습니다.")

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
        self.set_state("이동") # [추가] 수동 복귀 중 이동 상태
        if self.send_nav_goal(*self.start_pose):
            self.set_state("대기")
            self.write_log("home 도착 및 대기")
        self.is_returning_home = False

    def battery_callback(self, msg):
        if msg.percentage <= 20.0 and not self.is_battery_low:
            self.is_battery_low = True
            self.write_state("비상 복귀")
            self.is_auto_running = False
            self.current_mode = "manual"
            self.cancel_active_goal()
            self.stop_robot(force=True)
            threading.Thread(target=self._navigate_home_thread, daemon=True).start()

    # ====================================================================
    # 모드 관리 및 리모컨 제어 (★ Follow 모드 병합)
    # ====================================================================
    def mode_callback(self, msg):
        if self.is_first_callback:
            self.is_first_callback = False
            return

        mode = msg.data
        
        if self.current_mode == mode:
            return
    
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
            # 새 모드 진입
            if mode == "auto":
                self.write_log("자율 모드 전환")
                self.set_state("대기")
                self.current_mode = mode

            
            elif mode == "follow":
                self.write_log("추종 모드 전환")
                self.set_state("대기")
                self.current_mode = mode
                # Follow 모드 초기화
                self.target_human = None
                self.is_human_detected = False # 추가: 사람 발견 상태 초기화
                self.filtered_error_x = 0.0
                self.filtered_error_area = 0.0
                self.cancel_active_goal() # Nav2가 잡고있는 제어권 회수
                
            else: # manual
                self.write_log("수동 모드 전환")
                self.set_state("대기")
                self.current_mode = "manual"
                self.last_manual_cmd = "" # 추가: 수동 조작 상태 초기화
                self.cancel_active_goal()
                self.stop_robot(force=True)

    def remote_callback(self, msg):
        data = msg.data.lower()
        
        if data == 's':
            self.is_auto_running = False  
            self.is_returning_home = False
            self.is_manual_moving = False  # 이동 플래그 초기화
            self.current_mode = "manual"
            self.set_state("정지")
            self.write_log("정지")         # 누락되었던 정지 로그 추가
            self.cancel_active_goal()
            self.target_linear_vel = 0.0
            self.target_angular_vel = 0.0
            self.stop_robot(force=True)
            return
        
        if data == 'h':
            threading.Thread(target=self._navigate_home_thread, daemon=True).start()
            return
            
        if data.startswith('f') or data.startswith('b') or data.startswith('l') or data.startswith('r'):
            self.set_state("이동")
            self.write_log("목표 이동")

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
            self.set_state("사람 손실") # [추가] 상태 업데이트
            
            self.target_human = None  
            self.human_angle_range = None 
            self.filtered_error_x = 0.0  
            self.filtered_error_area = 0.0  
            twist = Twist()
            self.cmd_pub.publish(twist)  
            return
        else:
            # [추가] 사람 발견 및 추종 시의 로직
            if self.last_state != "사람 추종":
                self.write_log("작업자 발견")
                self.write_log("작업자 추종")
            self.set_state("사람 추종")

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
        v_human_z = -1.0 * self.filtered_error_x if abs(self.filtered_error_x) > 0.05 else 0.0

        # 2. 직진(X) 제어
        error_area = self.target_area - area
        self.filtered_error_area = (self.filter_alpha_area * error_area) + ((1.0 - self.filter_alpha_area) * self.filtered_error_area)
        v_human_x = 1.0 * self.filtered_error_area 
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
        if self.current_mode == "manual" or not self.is_auto_running:
            return
        self.latest_msg = msg
        # 자율주행(auto) 중이거나 수동(manual) 시퀀스 이동 중일 때 모두 허용
        is_align_executable = (self.current_mode == "auto" and self.is_auto_running) or (self.current_mode == "manual" and self.is_manual_moving)
        
        if is_align_executable and self.auto_step == "ALIGN":
            self.process_aruco_alignment(msg)

    def execute_move(self, linear, angular, duration):
        if self.current_mode == "manual":
            return False
        cmd = Twist()
        cmd.linear.x = float(linear)
        cmd.angular.z = float(angular)
        end_time = time.time() + duration
        while time.time() < end_time and rclpy.ok():
            # 자율주행 중도 아니고, 수동 시퀀스 이동 중도 아니라면 (정상적인 정지 명령 등) 그때만 멈춤
            if not self.is_auto_running and not self.is_manual_moving:
                self.stop_robot(force=True)
                return False 
            self.cmd_pub.publish(cmd)
            time.sleep(0.01)
            
        # ✅ 정상적으로 주행을 마쳤으므로 True 반환
        return True

    def process_aruco_alignment(self, msg):
        # 안전 변수 체크 수정
        if self.current_seq_idx >= len(self.sequence_list): return
        
        if self.camera_matrix is None or self.dist_coeffs is None:
            self.get_logger().warning("⏳ 카메라 캘리브레이션 정보 대기 중...")
            time.sleep(0.5)
            return
        
        # State 2, 3, 4 제어 로직 생략 (기존 코드 그대로 유지)
        if self.align_state == 2:
            if self.execute_move(0.0, -0.5, 3.14): self.align_state = 3
            return
        elif self.align_state == 3:
            move_dist = self.current_z_before_turn - self.target_dist_z
            move_speed = 0.05 if move_dist > 0 else -0.05
            move_duration = abs(move_dist / move_speed)
            if self.execute_move(move_speed, 0.0, move_duration): self.align_state = 4
            return
        elif self.align_state == 4:
            if self.execute_move(0.0, 0.5, 3.14): self.align_state = 1 
            return

        # 이미지 전처리
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = self.clahe.apply(cv2.GaussianBlur(cv2.LUT(gray, np.array(255 * (np.arange(256) / 255.0) ** 1.5, dtype=np.uint8)), (3, 3), 0))
        
        corners, ids, _ = self.detector.detectMarkers(gray)

        target_id = None
        target_idx_in_detection = -1

        # 💡 [마커 추적 핵심 변경] 화면 중앙(픽셀 오차 최소)에 위치한 마커를 동적으로 타겟팅
        if ids is not None:
            flattened_ids = ids.flatten()
            min_center_error = float('inf')
            
            for i, marker_id in enumerate(flattened_ids):
                c = corners[i][0]
                pixel_x_err = abs(int(np.mean(c[:, 0])) - 320) # 640 해상도 가로 중심 기준 오차 계산

                if pixel_x_err < min_center_error:
                    min_center_error = pixel_x_err
                    target_id = marker_id
                    target_idx_in_detection = i

        # [정렬 및 구동] 선정된 target_id 정보를 사용하여 정렬 수행 (기존 로직 유지)
        if target_id is not None and target_idx_in_detection != -1:
            c = corners[target_idx_in_detection][0]
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
                        cmd.angular.z = calibrated_tilt * 0.37
                        cmd.linear.x = np.clip(-pixel_x_err * 0.0005, -0.05, 0.05)
                        self.cmd_pub.publish(cmd)
                elif self.align_state == 5:
                    self.stop_robot()
                    self.align_done = True
                    # 💡 정렬 완료 시점에 검출된 ID를 멤버 변수에 저장하여 촬영 함수에서 쓸 수 있도록 함
                    self.current_detected_marker_id = target_id
        else:
            if self.align_state == 1:
                self.stop_robot()

    def send_nav_goal(self, x, y, yaw):
        # ====================================================================
        # [추가 권장] 정수 데이터(예: 0, 1) 수신 시 ROS2 float 형식 충돌 방지 형변환
        # ====================================================================
        x = float(x)
        y = float(y)
        yaw = float(yaw)

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
            if not self.is_auto_running and not self.is_returning_home and not self.is_manual_moving:
                return False
            time.sleep(0.1)

        self.goal_handle = future.result()
        if not self.goal_handle.accepted: return False

        result_future = self.goal_handle.get_result_async()

        while rclpy.ok() and not result_future.done():
            if not self.is_auto_running and not self.is_returning_home and not self.is_manual_moving:
                self.set_state("정지")  
                self.write_log("정지")  
                self.cancel_active_goal() 
                self.stop_robot(force=True)
                return False
            time.sleep(0.1)

        result = result_future.result()
        return result.status == 4

    def run_auto_process(self):
        # 데이터가 없는 경우 예외 처리
        if not self.sequence_list or not self.waypoint_dict:
            self.get_logger().warn("⚠️ 실행할 시퀀스 데이터가 존재하지 않습니다.")
            self.is_auto_running = False
            return

        self.set_state("자율 주행")
        self.write_log("자율 주행 시작")

        # 시퀀스 리스트에 적힌 순서대로 루프 수행
        for i in range(self.current_seq_idx, len(self.sequence_list)):
            if not self.is_auto_running: break
            
            self.current_seq_idx = i
            wp_id = self.sequence_list[i]
            wp = self.waypoint_dict.get(wp_id)

            if wp is None:
                self.get_logger().error(f"❌ 데이터베이스에 Waypoint ID {wp_id}가 존재하지 않습니다. 스킵합니다.")
                continue

            x = wp['x']
            y = wp['y']
            wp_type = wp['type']
            
            # 💡 [타입 조건 반영] ud 타입이면 방향을 무시(0.0)하고, d 나 ms이면 지정된 theta 사용
            yaw = wp['theta'] if wp_type in ['d', 'ms'] else 0.0

            # --- [NAV 단계: 공통 이동] ---
            self.auto_step = "NAV"
            self.set_state("wp 이동")
            self.write_log(f"ID {wp_id} ({wp_type} 타입) 목표 지점으로 이동 중")

            if not self.send_nav_goal(x, y, yaw):
                if not self.is_auto_running: break
                continue

            # --- [이동 완료 후 타입별 행동 분기 처리] ---
            if wp_type == "ud":
                self.write_log(f"ID {wp_id} (ud) 방향 무시 도착 완료")
                time.sleep(0.5) # 잠시 대기 후 다음 wp로 진행
                
            elif wp_type == "d":
                self.write_log(f"ID {wp_id} (d) 지정 방향 정렬 및 도착 완료")
                time.sleep(0.5)
                
            elif wp_type == "ms":
                # --- [ALIGN 단계: 정밀 정렬] ---
                self.auto_step = "ALIGN"
                self.set_state("마커 정렬")
                self.write_log(f"ID {wp_id} (ms) 카메라 기반 마커 정렬 시작")
                
                self.align_done = False
                self.align_state = 1
                align_start_time = time.time()
                
                # 정렬 완료 또는 타임아웃(30초)까지 대기
                while rclpy.ok() and not self.align_done:
                    if not self.is_auto_running: break
                    if time.time() - align_start_time > 30.0:
                        self.write_log(f"ID {wp_id} 정렬 시간 초과 (30s)")
                        self.stop_robot()
                        break 
                    time.sleep(0.1)

                if not self.is_auto_running: break

                # --- [DONE 단계: 이미지 전송 및 촬영] ---
                self.auto_step = "DONE"
                self.set_state("마커 촬영")
                
                # 정렬 중 카메라 화면 중심에서 가장 에러가 적었던 마커 ID 가져오기
                detected_id = self.current_detected_marker_id if self.current_detected_marker_id is not None else wp_id
                self.write_log(f"마커 {detected_id}번 ID 기반 촬영 데이터 전송 시작")
                
                for capture_idx in range(10):
                    if not self.is_auto_running: break
                    self.publish_capture_image(detected_id)
                    time.sleep(0.3) 
                
                self.write_log(f"ID {wp_id} 촬영 완료 및 종료")

            if not self.is_auto_running: 
                self.set_state("정지")
                break

        # --- [복귀 로직] ---
        if self.is_auto_running and self.current_seq_idx >= len(self.sequence_list) - 1:
            self.write_log("임무 완료 후 복귀")
            self.set_state("이동")
            
            self.is_returning_home = True
            self.current_seq_idx = 0
            self.send_nav_goal(*self.start_pose)
            self.is_returning_home = False
            
            self.set_state("대기")
            self.write_log("home 도착 및 다음 스케줄 대기")
            
        # 오타 lse를 지우고 깔끔하게 두 줄만 남깁니다.
        self.is_auto_running = False
        self.stop_robot()
        
    def publish_capture_image(self, marker_id): # [수정] 인자 추가
        if self.latest_msg is None: return
        np_arr = np.frombuffer(self.latest_msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
        info_text = f"WP: {self.current_wp_idx + 1} | Marker: {marker_id}" # 확인용 텍스트 수정
        cv2.putText(frame, info_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
    
        _, buffer = cv2.imencode('.jpg', frame)
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
    
        # [핵심 수정] 분석 노드가 인식할 수 있도록 frame_id에 마커 ID 삽입
        msg.header.frame_id = f"Marker ID: {marker_id}" 
    
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
