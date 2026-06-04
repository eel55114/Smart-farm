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
#### 2-1-1. 로봇 상태
- 토픽명: `smartfarm/{region_id}/robot/telemetry/state`
#### 2-1-2. 모드
- 토픽명: `smartfarm/{region_id}/robot/telemetry/mode`

### 2-2. 조작 명령 수신
