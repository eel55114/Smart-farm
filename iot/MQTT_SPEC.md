# 1. 공통
### 1-1. 토픽 접투어
- 공통: `smartfarm/{region_id}//`
- IoT 장비: `.../iot/`
- Turtlebot: `.../robot/`
- 작물: `.../plant/`

- 메시지 발신: `.../.../telemetry`
- 메시지 수신: `.../.../command`
- 이미지 토픽: `.../.../img`


# 2. IoT
### 2-1. 센서 데이터 발신
IoT 허브 -> 서버
- 토픽명: `smartfarm/{region_id}/iot/telemetry/sensor/{sensor_id}`
- 페이로드: json string {
    "time": (int) timestamp,
    "value": (int) value,
}

### 2-2. 액추에이터 조작
서버 -> IoT 허브
- 토픽명: `smartfarm/{region_id}/iot/command/device/{device_id}`
- 페이로드: json string {
    "on": bool,
}
### 2-3. 장치 상태
IoT 허브 -> 서버
- 토픽명: `smartfarm/{region_id}/iot/telemetry/device/{device_id}`
- 페이로드: json string {
    "time": (int) timestamp,
    "state": bool,
}

# 3. 로봇
### 2-1. 로봇 정보 발신

(→로봇)지도 선택 		/select_map		std_msgs/String 
(→로봇)초기 위치 설정 		/initialpose		geometry_msgs/PoseWithCovarianceStamped
(→로봇)목표 지점 설정 		/goal_pose		geometry_msgs/PoseStamped
(로봇→)로봇 위치 수신 		/amcl_pose		geometry_msgs/PoseWithCovarianceStamped
(↔쌍방)로봇 모드 변경		/robot_mode		std_msgs/String		["AUTO", "MANUAL"]
(→로봇)주행 알고리즘 		/select_controller	std_msgs/String 	["RPP", "SAFE", "ACK"]
(→로봇)수동 조작		/remote_control		std_msgs/String		["f", "b", "l", "r", "s"]
(로봇→)상태 메시지		/robot_state		std_msgs/String
(로봇→)배터리 잔량		/battery		std_msgs/String


(로봇→)지도 데이터 수신 	/map			nav_msgs/OccupancyGrid
(로봇→)작물 촬영 결과		/captured_image/compressed	sensor_msgs/CompressedImage

#### 2-1-1. 로봇 실시간 상태
<-로봇
- 토픽명: `smartfarm/{region_id}/robot/telemetry/{robot_id}/state`

#### 2-1-2. 동작 모드
<-로봇<-
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/robot_mode`

#### 2-1-3. 지도 선택
파이<-
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/set_map`
- 페이로드: json string {
    "name": (string) map name,
    "img_hash": (int),
    "inform_hash": (int),
}

name, hash가 일치하면 저장된 파일을 기반으로 ROS /map (nav_msgs/OccupancyGrid) 발행
name, hash가 일치하지 않으면 지도 요청 토픽 발행

### 2-1-4. 지도 요청
<-파이
- 토픽명: `smartfarm/{region_id}/robot/telemetry/{robot_id}/get_map`
- 페이로드: json string {
    "name": (string) map name,
    "img": (bool) img request,
    "inform": (bool) yaml request,
}

### 2-1-5. 지도 데이터
파이<-
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/map_data`
- 페이로드: json string {
    "name": (string) map name,
    "img": (binary, optional) pgm binary encoded by BASE64,
    "inform": (string, optional) yaml string,
}

name, hash가 일치하면 저장된 파일을 기반으로 ROS /map (nav_msgs/OccupancyGrid) 발행
name, hash가 일치하지 않으면 지도 요청 토픽 발행

### 2-1-6. 작물 이미지 데이터
<-파이
- 토픽명: `smartfarm/{region_id}/plant/img/captured_img`
- 페이로드: json string {
    "id": (int) plant ID,
    "time": (int) timestamp,
    "img": (string) plant image encoded by BASE64,
}

### 2-1-7. 초기 위치 설정 (Initial Pose)
서버 -> 라즈베리파이 -> ROS /initialpose
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/initial_pose`
- 페이로드: json string {
    "x": (float) 물리 좌표 x (미터),
    "y": (float) 물리 좌표 y (미터),
    "z": (float) 0.0 (고정),
    "qx": (float) 0.0 (고정),
    "qy": (float) 0.0 (고정),
    "qz": (float) sin(yaw/2),
    "qw": (float) cos(yaw/2),
}

ROS 매핑: geometry_msgs/PoseWithCovarianceStamped
- frame_id: "map"
- position: (x, y, z)
- orientation: (qx, qy, qz, qw)
- covariance: 36개 원소 0.0 (기본값)

### 2-1-8. 목표 지점 이동 (Goal Pose)
서버 -> 라즈베리파이 -> ROS /goal_pose
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/goal_pose`
- 페이로드: json string {
    "x": (float) 물리 좌표 x (미터),
    "y": (float) 물리 좌표 y (미터),
    "z": (float) 0.0 (고정),
    "qx": (float) 0.0 (고정),
    "qy": (float) 0.0 (고정),
    "qz": (float) sin(yaw/2) 또는 0.0 (방향 미지정 시),
    "qw": (float) cos(yaw/2) 또는 1.0 (방향 미지정 시),
}

ROS 매핑: geometry_msgs/PoseStamped
- frame_id: "map"
- position: (x, y, z)
- orientation: (qx, qy, qz, qw)

### 2-1-9. 로봇 위치 텔레메트리 (AMCL Pose)
라즈베리파이 -> 서버 (ROS /amcl_pose 수신 후 발신)
- 토픽명: `smartfarm/{region_id}/robot/telemetry/{robot_id}/amcl_pose`
- 페이로드: json string {
    "pose": {
        "pose": {
            "position": { "x": float, "y": float, "z": float },
            "orientation": { "x": float, "y": float, "z": float, "w": float }
        }
    }
}

ROS 매핑: geometry_msgs/PoseWithCovarianceStamped (covariance 제외하고 발신)

### 2-1-10. 주행 파라미터 전송 (Publish Param)
서버 -> 라즈베리파이 -> ROS /publish_param
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/publish_param`
- 페이로드: json string {
    "controllers": {
        "RPP":  { "speed": float, "tolerance": float, "inflation": float },
        "SAFE": { "speed": float, "tolerance": float, "inflation": float },
        "ACK":  { "speed": float, "tolerance": float, "inflation": float }
    },
    "current_controller": (string) "RPP" | "SAFE" | "ACK"
}

필드 설명:
- speed (m/s): 이동 속도
- tolerance (m): 목표 지점 도달 허용 오차 (대시보드 cm 값 / 100)
- inflation (m): 장애물 인식 반경 (대시보드 cm 값 / 100)
- current_controller: 현재 활성화할 주행 알고리즘

ROS 매핑: std_msgs/String
- data: 위 JSON을 문자열로 직렬화한 값


#### 2-1-11. 로봇 상세 로그
<-로봇
- 토픽명: `smartfarm/{region_id}/robot/telemetry/{robot_id}/log`
- 페이로드: json string {
    "time": (int) timestamp,
    "data": (string) log message,
}