# 1. 공통
### 1-1. 토픽 접투어
- 공통: `smartfarm/{region_id}//`
- IoT 장비: `.../iot/`
- Turtlebot: `.../robot/`

- 메시지 발신: `.../.../telemetry`
- 메시지 수신: `.../.../command`


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
(로봇→)배터리 잔량		/battery_state		sensor_msgs/BatteryState


(로봇→)지도 데이터 수신 	/map			nav_msgs/OccupancyGrid
(로봇→)작물 촬영 결과		/captured_image/compressed	sensor_msgs/CompressedImage

#### 2-1-1. 로봇 상태
<-로봇
- 토픽명: `smartfarm/{region_id}/robot/telemetry/{robot_id}/state`
#### 2-1-2. 모드
<-로봇<-
- 토픽명: `smartfarm/{region_id}/robot/command/{robot_id}/robot_mode`
#### 2-1. 지도 선택


### 2-2. 조작 명령 수신
