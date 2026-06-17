import json
import math
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped, Twist
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose

# [신규 추가] 동적 파라미터 변경을 위한 ROS 2 인터페이스
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue

class RosWorkerNode(Node):
    def __init__(self, gui_app):
        super().__init__("gui_dashboard_node_tk")
        self.gui_app = gui_app
        
        self.current_wp_idx = 0

        # Map 관련
        self.map_list_sub = self.create_subscription(String, "/map_list", self.map_list_callback, 10)
        self.map_select_pub = self.create_publisher(String, "/select_map", 10)
        self.map_sub = self.create_subscription(OccupancyGrid, "/map", self.map_received_callback, 10)

        # Pose & Nav 관련 (원본 유지)
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.goal_pose_pub = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.remote_pub = self.create_publisher(String, '/remote_control', 10)
        
        # Normal WP, Mission WP, WP List 퍼블리셔
        self.normal_wp_pub = self.create_publisher(PoseStamped, "/normal_wp", 10)
        self.mission_wp_pub = self.create_publisher(PoseStamped, "/mission_wp", 10)
        self.wp_list_pub = self.create_publisher(String, "/wp_list", 10)
        
        # 수동 조작 및 모드/컨트롤러 관련
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.ctrl_select_pub = self.create_publisher(String, 'select_controller', 10)
        self.mode_pub = self.create_publisher(String, 'robot_mode', 10)
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.current_nav_goal_handle = None
	
        # [신규 추가] Nav2 동적 파라미터 튜닝을 위한 서비스 클라이언트
        self.param_client_ctrl = self.create_client(SetParameters, '/controller_server/set_parameters')
        self.param_client_costmap = self.create_client(SetParameters, '/local_costmap/local_costmap/set_parameters')

        # 로봇 현재 위치 (AMCL)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self.amcl_pose_callback, 10)
        
        

        self.current_robot_pose = None
        self.current_goal = None
        self.waypoint_queue = []
        self.create_timer(0.5, self.check_goal_reached)

    # ---------------------------------------------
    # Nav2 실시간 파라미터 변경 로직 [신규 추가]
    # ---------------------------------------------
    def send_remote_cmd(self, command):
        msg = String()
        msg.data = command
        self.remote_pub.publish(msg)
        
    def update_nav2_params(self, speed, inflation, tolerance):
        # 1. Controller Server 파라미터 변경 (속도 및 오차)
        req_ctrl = SetParameters.Request()
        req_ctrl.parameters = [
            Parameter(name='FollowPathFast.desired_linear_vel', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(speed))),
            Parameter(name='FollowPathSafe.max_vel_x', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(speed))),
            Parameter(name='FollowPathAck.max_vel_x', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(speed))),
            Parameter(name='general_goal_checker.xy_goal_tolerance', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(tolerance))),
            Parameter(name='general_goal_checker.yaw_goal_tolerance', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(tolerance)))
        ]
        if self.param_client_ctrl.service_is_ready():
            self.param_client_ctrl.call_async(req_ctrl)
            
        # 2. Local Costmap 파라미터 변경 (장애물 회피 범위/Inflation 반경)
        req_costmap = SetParameters.Request()
        req_costmap.parameters = [
            Parameter(name='inflation_layer.inflation_radius', value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(inflation)))
        ]
        if self.param_client_costmap.service_is_ready():
            self.param_client_costmap.call_async(req_costmap)
        
        self.get_logger().info(f"🎛️ [파라미터 전송 완료] 속도: {speed:.2f}, 회피 반경: {inflation:.2f}, 오차: {tolerance:.2f}")

    # ---------------------------------------------
    # Map Test 원본 로직 유지
    # ---------------------------------------------
    def map_list_callback(self, msg):
        try:
            map_names = json.loads(msg.data)
            self.gui_app.root.after(0, self.gui_app.update_map_list_ui, map_names)
        except Exception: pass

    def publish_map_select(self, map_name):
        msg = String()
        msg.data = map_name
        self.map_select_pub.publish(msg)

    def publish_initial_pose(self, x, y, yaw=0.0):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance = [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0685]
        self.initial_pose_pub.publish(msg)
        self.get_logger().info(f"📍 [Initial Pose Sent] x: {x:.4f}, y: {y:.4f}, yaw: {math.degrees(yaw):.1f}")

    def map_received_callback(self, msg):
        map_info = {
            "width": msg.info.width,
            "height": msg.info.height,
            "resolution": msg.info.resolution,
            "origin_x": msg.info.origin.position.x,
            "origin_y": msg.info.origin.position.y,
            "raw_grid_data": list(msg.data),
        }
        self.gui_app.root.after(0, self.gui_app.update_map_info_ui, map_info)

    # ---------------------------------------------
    # Navigation & Control 로직
    # ---------------------------------------------
    def publish_goal_pose(self, x, y, yaw=0.0):
        # RViz 시각화 등을 위해 기존 토픽 발행은 유지
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        msg.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.orientation.w = math.cos(yaw / 2.0)
        self.goal_pose_pub.publish(msg)

        # Nav2 액션 서버로 목표 전송
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = msg
        
        if not self.nav_client.wait_for_server(timeout_sec=1.0):
            self.gui_app.append_log("❌ Nav2 액션 서버를 찾을 수 없습니다.\n")
            return
            
        send_goal_future = self.nav_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.goal_response_callback)
        
    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            return
        self.current_nav_goal_handle = goal_handle

    def cancel_nav_goal(self):
        if self.current_nav_goal_handle is not None:
            self.current_nav_goal_handle.cancel_goal_async()
            self.current_nav_goal_handle = None
            self.gui_app.append_log("🛑 진행 중인 Nav2 자율주행 목표가 강제 취소되었습니다.\n")
    
    def publish_normal_wp(self, x, y, yaw=0.0):
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        msg.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.orientation.w = math.cos(yaw / 2.0)
        self.normal_wp_pub.publish(msg)
        
    def publish_mission_wp(self, x, y, yaw=0.0):
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        msg.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.orientation.w = math.cos(yaw / 2.0)
        self.mission_wp_pub.publish(msg)

    def publish_wp_list(self, wp_routines_dict):
        msg = String()
        msg.data = json.dumps(wp_routines_dict)
        self.wp_list_pub.publish(msg)
        self.gui_app.append_log("📡 WP 루틴 목록(List)이 발행되었습니다.\n")

    def publish_controller(self, ctrl_name):
        msg = String(); msg.data = ctrl_name
        self.ctrl_select_pub.publish(msg)
        self.gui_app.append_log(f"⚙️ 컨트롤러 변경: {ctrl_name}\n")

    def publish_mode(self, mode):
        msg = String(); msg.data = mode.lower()
        self.mode_pub.publish(msg)
        self.gui_app.append_log(f"🕹️ 모드 변경: {mode}\n")

    def send_teleop_cmd(self, linear, angular):
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.cmd_vel_pub.publish(msg)

    def amcl_pose_callback(self, msg):
        self.current_robot_pose = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (ori.w * ori.z + ori.x * ori.y), 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z))
        self.gui_app.root.after(0, self.gui_app.update_robot_position, self.current_robot_pose.x, self.current_robot_pose.y, yaw)

    def check_goal_reached(self):
        if not self.current_robot_pose or not self.current_goal: return
        dist = math.sqrt((self.current_robot_pose.x - self.current_goal['x'])**2 + (self.current_robot_pose.y - self.current_goal['y'])**2)
        if dist < 0.3:
            self.gui_app.append_log(f"✅ WP {self.current_wp_idx} 도착 완료.\n")
            self.current_wp_idx += 1
            self.current_goal = None
            self.process_next_waypoint()
            
    def set_waypoint_list(self, waypoints):
        self.waypoint_queue = list(waypoints)
        self.process_next_waypoint()

    def process_next_waypoint(self):
        if self.waypoint_queue:
            next_wp = self.waypoint_queue.pop(0)
            self.current_goal = next_wp
            
            self.publish_goal_pose(next_wp['x'], next_wp['y'], next_wp.get('yaw', 0.0))
            
            if next_wp['type'] == 'normal':
                self.publish_normal_wp(next_wp['x'], next_wp['y'], next_wp.get('yaw', 0.0))
            elif next_wp['type'] == 'mission':
                self.publish_mission_wp(next_wp['x'], next_wp['y'], next_wp.get('yaw', 0.0))
                
        else:
            self.gui_app.append_log("✅ 모든 경로 주행 완료.\n")
            self.current_goal = None
            self.waypoint_queue.clear()
            self.current_wp_idx = 0


class GuiDashboardTk:
    def __init__(self, root):
        self.root = root
        self.ros_node = None
        self.pixel_size = 4
        self.map_meta = None
        
        self.is_pose_mode = False
        self.mode = None 
        self.waypoints = []
        self.waypoint_objs = []
        self.robot_id = None
        self.robot_arrow_id = None
        self.drive_mode = "AUTO"

        self.saved_routines = {}

        self.drag_start_px = None
        self.drag_start_map = None
        self.temp_arrow = None
        
        self.controller_presets = {
            "RPP": {"speed": 0.24, "inflation": 0.55, "tolerance": 0.25},
            "SAFE": {"speed": 0.15, "inflation": 0.55, "tolerance": 0.25},
            "ACK": {"speed": 0.16, "inflation": 0.55, "tolerance": 0.25}
        }

        self.init_ui()

    def set_ros_node(self, ros_node): 
        self.ros_node = ros_node

    def init_ui(self):
        self.root.title("🤖 Robot Pose & Controller Integrated")
        self.root.geometry("1400x950")  # UI 추가를 위해 높이 소폭 확장
        
        main_frame = tk.Frame(self.root, padx=10, pady=1)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---------------------------------------------
        # Left Frame (제어 패널)
        # ---------------------------------------------
        left_frame = tk.Frame(main_frame, width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left_frame.pack_propagate(False)

        # 1. 맵 로드 UI
        map_frame = tk.LabelFrame(left_frame, text="🗺️ 맵 선택", padx=5, pady=1)
        map_frame.pack(fill=tk.X, pady=1)
        self.map_listbox = tk.Listbox(map_frame, height=1)
        self.map_listbox.pack(fill=tk.X)
        self.btn_select = tk.Button(map_frame, text="📍 맵 활성화 요청", bg="#3498db", fg="white", command=self.on_click_select_map)
        self.btn_select.pack(fill=tk.X, pady=(2,0))

        # 2. 모드 및 컨트롤러 선택
        ctrl_frame = tk.LabelFrame(left_frame, text="⚙️ 제어 모드 및 컨트롤러", font=("Arial", 10, "bold"), padx=5, pady=1)
        ctrl_frame.pack(fill=tk.X, pady=1)
        
        btn_mode_frame = tk.Frame(ctrl_frame)
        btn_mode_frame.pack(fill=tk.X)
        self.btn_mode_auto = tk.Button(btn_mode_frame, text="AUTO", bg="green", fg="white", command=lambda: self.switch_drive_mode("AUTO"))
        self.btn_mode_auto.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        self.btn_mode_manual = tk.Button(btn_mode_frame, text="MANUAL", bg="gray", fg="white", command=lambda: self.switch_drive_mode("MANUAL"))
        self.btn_mode_manual.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        
        self.ctrl_combo = ttk.Combobox(ctrl_frame, values=["RPP", "SAFE", "ACK"], state="readonly")
        self.ctrl_combo.set("RPP")
        self.ctrl_combo.pack(fill=tk.X, pady=1)
        self.ctrl_combo.bind("<<ComboboxSelected>>", self.on_controller_combobox_changed)
        tk.Button(ctrl_frame, text="컨트롤러 적용", command=self.apply_controller_and_params).pack(fill=tk.X)

        tk.Button(left_frame, text="🏠 홈 복귀 (0,0)", bg="#9b59b6", fg="white", font=("Arial", 10, "bold"), command=lambda: self.ros_node.publish_goal_pose(0, 0)).pack(fill=tk.X, pady=1)

        # 3. 내비게이션 좌표 설정 UI
        nav_frame = tk.LabelFrame(left_frame, text="📍 마우스 WP 설정", padx=5, pady=1)
        nav_frame.pack(fill=tk.X, pady=1)
        
        self.btn_pose = tk.Button(nav_frame, text="🟢 초기 위치/방향 (드래그) (Off)", bg="gray", fg="white", font=("Arial", 10, "bold"), command=self.toggle_pose_mode)
        self.btn_pose.pack(fill=tk.X, pady=1)
        
        tk.Button(nav_frame, text="🏁 단일 목표 지점 설정", command=lambda: self.set_mode("goal")).pack(fill=tk.X, pady=1)
        tk.Button(nav_frame, text="📍 일반 WP 추가 (클릭)", bg="lightblue", command=lambda: self.set_mode("normal_wp")).pack(fill=tk.X, pady=1)
        tk.Button(nav_frame, text="🚩 임무 WP 추가 (드래그)", bg="plum", command=lambda: self.set_mode("mission_wp")).pack(fill=tk.X, pady=1)
        
        tk.Button(nav_frame, text="🚀 WP 주행 시작", bg="#2ecc71", fg="white", command=self.start_waypoint_drive).pack(fill=tk.X, pady=1)
        tk.Button(nav_frame, text="🔄 WP 캔버스 초기화", bg="orange", command=self.clear_waypoints).pack(fill=tk.X, pady=1)

        # 4. WP 루틴(List) 관리 UI
        routine_frame = tk.LabelFrame(left_frame, text="📂 WP 루틴(List) 관리", padx=5, pady=1)
        routine_frame.pack(fill=tk.X, pady=1)

        self.routine_name_var = tk.StringVar()
        self.routine_name_var.set("Routine_1")
        tk.Entry(routine_frame, textvariable=self.routine_name_var).pack(fill=tk.X, pady=1)

        btn_routine_frame = tk.Frame(routine_frame)
        btn_routine_frame.pack(fill=tk.X, pady=1)
        tk.Button(btn_routine_frame, text="저장", command=self.save_routine).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        tk.Button(btn_routine_frame, text="적용", command=self.load_routine).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        tk.Button(btn_routine_frame, text="삭제", command=self.delete_routine).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        
        self.routine_listbox = tk.Listbox(routine_frame, height=1)
        self.routine_listbox.pack(fill=tk.X, pady=1)
        
        tk.Button(routine_frame, text="📡 전체 WP 리스트 발행", bg="#f1c40f", font=("Arial", 9, "bold"), command=self.publish_routine_list).pack(fill=tk.X, pady=1)

        # 5. [신규 추가] Nav2 실시간 파라미터 튜닝 패널
        tuning_frame = tk.LabelFrame(left_frame, text="🎛️ Nav2 실시간 파라미터 튜닝", padx=5, pady=1)
        tuning_frame.pack(fill=tk.X, pady=1)

        tk.Label(tuning_frame, text="최대 주행 속도 (m/s)").pack(anchor="w")
        self.scale_speed = tk.Scale(tuning_frame, from_=0.05, to_=0.5, resolution=0.01, orient=tk.HORIZONTAL)
        self.scale_speed.set(0.24) 
        self.scale_speed.pack(fill=tk.X)

        tk.Label(tuning_frame, text="장애물 회피 여유 반경 (m)").pack(anchor="w")
        self.scale_inflation = tk.Scale(tuning_frame, from_=0.1, to_=1.5, resolution=0.05, orient=tk.HORIZONTAL)
        self.scale_inflation.set(0.55) 
        self.scale_inflation.pack(fill=tk.X)

        tk.Label(tuning_frame, text="도착 인정 오차 반경 (m)").pack(anchor="w")
        self.scale_tolerance = tk.Scale(tuning_frame, from_=0.05, to_=1.0, resolution=0.01, orient=tk.HORIZONTAL)
        self.scale_tolerance.set(0.25) 
        self.scale_tolerance.pack(fill=tk.X)

        tk.Button(tuning_frame, text="파라미터 즉시 적용", bg="#34495e", fg="white", command=self.apply_nav2_params).pack(fill=tk.X, pady=1)

        # 6. 수동 조작 UI
        self.teleop_frame = tk.LabelFrame(left_frame, text="🎮 수동 조작 (WASDX)", padx=5, pady=1)
        # 버튼 생성 시 람다 식 수정
        btn_w = tk.Button(self.teleop_frame, text="W\n(전진)", bg="#3498db", fg="white", font=("Consolas", 9, "bold"), command=lambda: self.manual_move('f'))
        btn_a = tk.Button(self.teleop_frame, text="A\n(좌)", bg="#3498db", fg="white", font=("Consolas", 9, "bold"), command=lambda: self.manual_move('l'))
        btn_s = tk.Button(self.teleop_frame, text="S\n(정지)", bg="#e74c3c", fg="white", font=("Consolas", 9, "bold"), command=lambda: self.manual_move('s'))
        btn_d = tk.Button(self.teleop_frame, text="D\n(우)", bg="#3498db", fg="white", font=("Consolas", 9, "bold"), command=lambda: self.manual_move('r'))
        btn_x = tk.Button(self.teleop_frame, text="X\n(후진)", bg="#3498db", fg="white", font=("Consolas", 9, "bold"), command=lambda: self.manual_move('b'))

        btn_w.grid(row=0, column=1, sticky="nsew", padx=2, pady=1)
        btn_a.grid(row=1, column=0, sticky="nsew", padx=2, pady=1)
        btn_s.grid(row=1, column=1, sticky="nsew", padx=2, pady=1)
        btn_d.grid(row=1, column=2, sticky="nsew", padx=2, pady=1)
        btn_x.grid(row=2, column=1, sticky="nsew", padx=2, pady=1)
        
        self.teleop_frame.grid_columnconfigure(0, weight=1)
        self.teleop_frame.grid_columnconfigure(1, weight=1)
        self.teleop_frame.grid_columnconfigure(2, weight=1)
        self.teleop_frame.pack(fill=tk.X, pady=1)

        self.root.bind("<Key>", self.on_key_press)

        # ---------------------------------------------
        # Middle Frame (Map Canvas)
        # ---------------------------------------------
        middle_frame = tk.Frame(main_frame, padx=10)
        middle_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.map_canvas = tk.Canvas(middle_frame, bg="#bdc3c7")
        self.map_canvas.pack(fill=tk.BOTH, expand=True)
        
        self.map_canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.map_canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.map_canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        # ---------------------------------------------
        # Right Frame (Log)
        # ---------------------------------------------
        right_frame = tk.Frame(main_frame, width=300)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
        self.txt_log = scrolledtext.ScrolledText(right_frame, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------
    # [신규 추가] GUI 버튼 연동 로직
    # ---------------------------------------------
    def on_controller_combobox_changed(self, event=None):
        """콤보박스에서 컨트롤러를 선택하면 슬라이더 값을 프리셋으로 갱신합니다."""
        selected_ctrl = self.ctrl_combo.get()
        if selected_ctrl in self.controller_presets:
            preset = self.controller_presets[selected_ctrl]
            self.scale_speed.set(preset["speed"])
            self.scale_inflation.set(preset["inflation"])
            self.scale_tolerance.set(preset["tolerance"])
            self.append_log(f"🔄 GUI 연동: {selected_ctrl} 모드 프리셋으로 슬라이더 갱신됨.\n")

    def apply_controller_and_params(self):
        """컨트롤러 적용 버튼 클릭 시, 컨트롤러를 바꾸면서 현재 슬라이더의 파라미터도 함께 적용합니다."""
        if not self.ros_node: return
        ctrl_name = self.ctrl_combo.get()
        self.ros_node.publish_controller(ctrl_name)
        self.apply_nav2_params()
    
    def apply_nav2_params(self):
        if not self.ros_node: return
        speed = self.scale_speed.get()
        inflation = self.scale_inflation.get()
        tolerance = self.scale_tolerance.get()
        
        self.ros_node.update_nav2_params(speed, inflation, tolerance)
        self.append_log(f"\n🎛️ [파라미터 적용]\n  - 최대 속도: {speed} m/s\n  - 회피 반경: {inflation} m\n  - 도착 오차: {tolerance} m\n")
    # ---------------------------------------------
    # 루틴(WP List) 관리 로직
    # ---------------------------------------------
    def save_routine(self):
        name = self.routine_name_var.get().strip()
        if not name:
            messagebox.showwarning("경고", "루틴 이름을 입력하세요.")
            return
        if not self.waypoints:
            messagebox.showwarning("경고", "저장할 웨이포인트가 캔버스에 없습니다.")
            return
            
        self.saved_routines[name] = list(self.waypoints)
        self.update_routine_listbox()
        self.append_log(f"💾 루틴 '{name}' 이(가) 저장되었습니다. (총 {len(self.waypoints)}개 WP)\n")

    def load_routine(self):
        try:
            sel = self.routine_listbox.get(self.routine_listbox.curselection()[0])
            self.clear_waypoints()
            self.waypoints = list(self.saved_routines[sel])
            
            for idx, wp in enumerate(self.waypoints):
                px_x = int(((wp['x'] - self.map_meta['origin_x']) / self.map_meta['resolution']) * self.pixel_size)
                ros_row_index = (wp['y'] - self.map_meta['origin_y']) / self.map_meta['resolution']
                px_y = int((self.map_meta['height'] - 1 - ros_row_index) * self.pixel_size)
                
                self.draw_waypoint_ui(px_x, px_y, idx+1, wp['type'], wp.get('yaw', 0.0))
                
            self.append_log(f"📂 루틴 '{sel}' 을(를) 불러왔습니다.\n")
        except: 
            messagebox.showwarning("경고", "불러올 루틴을 리스트에서 선택하세요.")

    def delete_routine(self):
        try:
            sel_idx = self.routine_listbox.curselection()[0]
            sel_name = self.routine_listbox.get(sel_idx)
            del self.saved_routines[sel_name]
            self.update_routine_listbox()
            self.append_log(f"🗑️ 루틴 '{sel_name}' 이(가) 삭제되었습니다.\n")
        except:
            messagebox.showwarning("경고", "삭제할 루틴을 리스트에서 선택하세요.")

    def update_routine_listbox(self):
        self.routine_listbox.delete(0, tk.END)
        for name in self.saved_routines.keys():
            self.routine_listbox.insert(tk.END, name)

    def publish_routine_list(self):
        if self.ros_node:
            self.ros_node.publish_wp_list(self.saved_routines)

    # ---------------------------------------------
    # 기능 백엔드 로직
    # ---------------------------------------------
    def switch_drive_mode(self, mode):
        self.drive_mode = mode
        if mode == "AUTO":
            self.btn_mode_auto.config(bg="green")
            self.btn_mode_manual.config(bg="gray")
        else:
            self.btn_mode_auto.config(bg="gray")
            self.btn_mode_manual.config(bg="red")
            
            if self.ros_node:
                self.ros_node.waypoint_queue.clear()
                self.ros_node.current_goal = None
                # 🌟 [수정] 매뉴얼 모드로 전환되거나 정지 명령 시 Nav2 액션 취소
                self.ros_node.cancel_nav_goal() 
        
        if self.ros_node: self.ros_node.publish_mode(mode)
        
    def manual_move(self, command):
        """
        command: 'f'(전진), 'b'(후진), 'l'(좌회전), 'r'(우회전), 's'(정지)
        """
        if self.drive_mode != "MANUAL":
            self.switch_drive_mode("MANUAL")
        
        # ROS 노드를 통해 원격 제어 토픽 발행
        if self.ros_node:
            self.ros_node.send_remote_cmd(command)
        
        # GUI 로그 처리
        action_map = {'f': "전진", 'b': "후진", 'l': "좌회전", 'r': "우회전", 's': "정지"}
        self.append_log(f"🎮 수동 명령: {action_map.get(command, command)}\n")

    def on_key_press(self, event):
        key = event.char.lower()
        if key == 'w': self.manual_move('f')
        elif key == 'a': self.manual_move('l')
        elif key == 's': self.manual_move('s')
        elif key == 'd': self.manual_move('r')
        elif key == 'x': self.manual_move('b')

    def toggle_pose_mode(self):
        self.is_pose_mode = not self.is_pose_mode
        self.btn_pose.config(text=f"🔴 초기 위치/방향 (드래그) ({'On' if self.is_pose_mode else 'Off'})", bg="red" if self.is_pose_mode else "gray")
        if self.is_pose_mode: self.mode = None 

    def set_mode(self, mode):
        self.mode = mode
        self.is_pose_mode = False
        self.btn_pose.config(text="🟢 초기 위치/방향 설정 (Off)", bg="gray")
        self.append_log(f"--- 📌 마우스 입력 모드: {mode.upper()} ---\n")

    def get_map_coords(self, px_x, px_y):
        canvas_px_x = px_x // self.pixel_size
        canvas_px_y = px_y // self.pixel_size
        ros_row_index = self.map_meta['height'] - 1 - canvas_px_y
        map_x = (canvas_px_x * self.map_meta['resolution']) + self.map_meta['origin_x']
        map_y = (ros_row_index * self.map_meta['resolution']) + self.map_meta['origin_y']
        return map_x, map_y

    def on_canvas_press(self, event):
        if not self.map_meta: return
        
        self.drag_start_px = (event.x, event.y)
        self.drag_start_map = self.get_map_coords(event.x, event.y)
        map_x, map_y = self.drag_start_map

        if self.is_pose_mode or self.mode == "mission_wp":
            pass
        elif self.mode == "goal":
            if self.ros_node: self.ros_node.publish_goal_pose(map_x, map_y)
            self.append_log(f"\n🏁 목표 좌표 발행: X={map_x:.2f}, Y={map_y:.2f}\n")
            self.mode = None 
        elif self.mode == "normal_wp":
            self.waypoints.append({'type': 'normal', 'x': map_x, 'y': map_y, 'yaw': 0.0})
            self.draw_waypoint_ui(event.x, event.y, len(self.waypoints), wp_type="normal")

    def on_canvas_drag(self, event):
        if (self.mode == "mission_wp" or self.is_pose_mode) and self.drag_start_px:
            if self.temp_arrow: self.map_canvas.delete(self.temp_arrow)
            arrow_color = "red" if self.is_pose_mode else "purple"
            self.temp_arrow = self.map_canvas.create_line(self.drag_start_px[0], self.drag_start_px[1], event.x, event.y, fill=arrow_color, arrow=tk.LAST, width=2)

    def on_canvas_release(self, event):
        if (self.mode == "mission_wp" or self.is_pose_mode) and self.drag_start_map:
            map_end_x, map_end_y = self.get_map_coords(event.x, event.y)
            
            if self.drag_start_px[0] == event.x and self.drag_start_px[1] == event.y:
                yaw = 0.0
            else:
                yaw = math.atan2(map_end_y - self.drag_start_map[1], map_end_x - self.drag_start_map[0])
            
            if self.is_pose_mode:
                if self.ros_node: self.ros_node.publish_initial_pose(self.drag_start_map[0], self.drag_start_map[1], yaw)
                self.append_log(f"\n📍 초기 좌표/방향 발행됨 (Yaw: {math.degrees(yaw):.1f}°)\n")
                self.toggle_pose_mode()
            else:
                self.waypoints.append({'type': 'mission', 'x': self.drag_start_map[0], 'y': self.drag_start_map[1], 'yaw': yaw})
                self.draw_waypoint_ui(self.drag_start_px[0], self.drag_start_px[1], len(self.waypoints), wp_type="mission", yaw=yaw)
            
            if self.temp_arrow:
                self.map_canvas.delete(self.temp_arrow)
                self.temp_arrow = None
                
            self.drag_start_px = None
            self.drag_start_map = None

    def draw_occupancy_grid(self, width, height, grid_data):
        if not self.root.winfo_exists(): return
        self.map_canvas.delete("all")
        
        c_w, c_h = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        if c_w < 10 or c_h < 10: return
        self.pixel_size = max(1, min(c_w // width, c_h // height))

        for y in range(height):
            for x in range(width):
                val = grid_data[y * width + x]
                if val == -1: continue 
                color = "#2c3e50" if val > 50 else "#ffffff"

                screen_y = (height - 1 - y) * self.pixel_size
                screen_x = x * self.pixel_size
                self.map_canvas.create_rectangle(screen_x, screen_y, screen_x + self.pixel_size, screen_y + self.pixel_size, fill=color, outline="")

    def update_map_info_ui(self, map_info):
        if not self.root.winfo_exists(): return
        self.map_meta = map_info
        self.append_log(f"\n✅ 맵 수신 완료: {map_info['width']}x{map_info['height']}\n")
        self.draw_occupancy_grid(map_info["width"], map_info["height"], map_info["raw_grid_data"])

    def on_click_select_map(self):
        try:
            sel = self.map_listbox.get(self.map_listbox.curselection()[0])
            self.map_meta = None
            self.map_canvas.delete("all")
            if self.ros_node: self.ros_node.publish_map_select(sel)
        except: messagebox.showwarning("경고", "지도를 선택하세요")

    def update_map_list_ui(self, map_names):
        if not self.root.winfo_exists(): return
        self.map_listbox.delete(0, tk.END)
        for name in map_names: self.map_listbox.insert(tk.END, name)

    def append_log(self, text, color=None):
        if not self.root.winfo_exists(): return
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, text)
        self.txt_log.config(state=tk.DISABLED)
        self.txt_log.see(tk.END)

    # --- UI 헬퍼 및 기타 기능 ---
    def draw_waypoint_ui(self, cx, cy, idx, wp_type="normal", yaw=0.0):
        color = "blue" if wp_type == "normal" else "purple"
        
        obj1 = self.map_canvas.create_oval(cx-4, cy-4, cx+4, cy+4, fill=color)
        obj2 = self.map_canvas.create_text(cx+10, cy-10, text=f"WP{idx}", fill=color, font=("Arial", 9, "bold"))
        self.waypoint_objs.extend([obj1, obj2])
        
        if wp_type == "mission":
            ex = cx + 20 * math.cos(-yaw)
            ey = cy + 20 * math.sin(-yaw)
            obj3 = self.map_canvas.create_line(cx, cy, ex, ey, fill="purple", arrow=tk.LAST, width=2)
            self.waypoint_objs.append(obj3)
            self.append_log(f"🚩 임무 WP{idx} 추가됨. (Yaw: {math.degrees(yaw):.1f}°)\n")
        else:
            self.append_log(f"📍 일반 WP{idx} 추가됨.\n")

    def clear_waypoints(self):
        for obj in self.waypoint_objs: self.map_canvas.delete(obj)
        self.waypoints = []; self.waypoint_objs = []
        self.append_log("🔄 캔버스 상의 WP가 초기화되었습니다.\n")

    def start_waypoint_drive(self):
        if not self.waypoints: return
        idx = self.ros_node.current_wp_idx
        if idx >= len(self.waypoints):
            idx = 0
            self.ros_node.current_wp_idx = 0
        # 🌟 1. 만약 직전에 정지(s)해서 가려던 목표(current_goal)가 노드에 남아있는 경우
        if idx > 0:
            # 🌟 [핵심] 전체 WP 배열에서 이미 지나간 idx만큼은 싹 잘라내고, 
            # 남은 웨이포인트들만(wp3, wp4, wp5...) 다시 대기 큐에 주입합니다.
            remaining_wps = self.waypoints[idx:]
            self.ros_node.set_waypoint_list(remaining_wps)
            self.append_log(f"▶️ 정지했던 위치(WP {idx + 1})부터 남은 경로 주행을 재개합니다. (남은 WP: {len(remaining_wps)}개)\n")
        else:
            # 아예 처음 시작하는 상황 (idx == 0)
            self.ros_node.current_wp_idx = 0
            self.ros_node.set_waypoint_list(self.waypoints)
            self.append_log("🚀 다중 웨이포인트 주행을 처음부터 시작합니다.\n")

    def update_robot_position(self, x, y, yaw):
        if not self.map_meta: return
        
        px_x = int(((x - self.map_meta['origin_x']) / self.map_meta['resolution']) * self.pixel_size)
        ros_row_index = (y - self.map_meta['origin_y']) / self.map_meta['resolution']
        px_y = int((self.map_meta['height'] - 1 - ros_row_index) * self.pixel_size)

        if not self.robot_id:
            self.robot_id = self.map_canvas.create_oval(0,0,0,0, fill="red")
            self.robot_arrow_id = self.map_canvas.create_line(0,0,0,0, fill="yellow", width=2, arrow=tk.LAST)

        self.map_canvas.coords(self.robot_id, px_x-5, px_y-5, px_x+5, px_y+5)
        ex = px_x + 15 * math.cos(-yaw)
        ey = px_y + 15 * math.sin(-yaw)
        self.map_canvas.coords(self.robot_arrow_id, px_x, px_y, ex, ey)

def ros_spin_loop(ros_node, root):
    if rclpy.ok(): rclpy.spin_once(ros_node, timeout_sec=0.001)
    root.after(50, ros_spin_loop, ros_node, root)

def main():
    rclpy.init()
    root = tk.Tk()
    app = GuiDashboardTk(root)
    ros_node = RosWorkerNode(app)
    app.set_ros_node(ros_node)
    
    root.after(50, ros_spin_loop, ros_node, root)
    root.protocol("WM_DELETE_WINDOW", lambda: (ros_node.destroy_node(), rclpy.shutdown(), root.destroy()))
    root.mainloop()

if __name__ == "__main__":
    main()
