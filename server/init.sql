CREATE DATABASE farm;
USE farm;

SET GLOBAL event_scheduler = ON;

-- 재배지 이름
CREATE TABLE region(
    id INT PRIMARY KEY,         -- 재배지 ID
    name VARCHAR(30) NOT NULL   -- 재배지 이름(예. 비닐하우스, 화분1...)
);

-- 작물 유형
CREATE TABLE plant_type(
	id INT PRIMARY KEY,                 -- 작물 유형 ID
    name VARCHAR(30) NOT NULL UNIQUE    -- 작물 이름(예. 토마토, 딸기...)
);

-- 개별 작물 정보와 현재값
CREATE TABLE plant(
	id INT PRIMARY KEY,         -- 개별 작물 ID
    name VARCHAR(30) NOT NULL,  -- 개별 작물 이름(예. 토마토1, 딸기3...)
    region_id INT NOT NULL,       -- 재배지 ID
    type_id INT NOT NULL,       -- 작물 유형 ID
    maturity FLOAT NOT NULL     -- 작물 성장률(0~1)
    CHECK (maturity >= 0 AND maturity <= 1),    
    is_disease bool NOT NULL,   -- 작물 병해 여부
    
    FOREIGN KEY (type_id) REFERENCES plant_type(id),
    FOREIGN KEY (region_id) REFERENCES region(id)
);

-- 일일 작물 정보 통계(작물별)
CREATE TABLE plant_statistics(
	id INT AUTO_INCREMENT PRIMARY KEY,                          -- 로그 ID
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,    -- 생성 시간
    type_id INT NOT NULL,                                       -- 작물 유형 ID
    region_id INT NOT NULL,                                       -- 재배지 ID
    avg_maturity FLOAT NOT NULL                                 -- 작물군의 평균 성장도
    CHECK (avg_maturity >= 0 AND avg_maturity <= 1),
    disease_ratio FLOAT NOT NULL                                -- 작물군의 평균 병해율
    CHECK (disease_ratio >= 0 AND disease_ratio <= 1),

    FOREIGN KEY (type_id) REFERENCES plant_type(id),
    FOREIGN KEY (region_id) REFERENCES region(id)
);

-- 센서 유형
CREATE TABLE sensor_type(
	id INT PRIMARY KEY,                     -- 센서 유형 ID
    type_name VARCHAR(20) NOT NULL UNIQUE   -- 센서 유형 이름(예. 조도, 온도...)
);

-- 개별 센서 최신값
CREATE TABLE sensor(
	id INT PRIMARY KEY,             -- 개별 센서 ID
    type_id INT NOT NULL,           -- 센서 유형 ID
    region_id INT NOT NULL,         -- 재배지 ID
    name VARCHAR(30) NULL,          -- 센서 이름
    value FLOAT NOT NULL,           -- 센서값
    last_signal TIMESTAMP NOT NULL, -- 마지막 신호 연결

    FOREIGN KEY (type_id) REFERENCES sensor_type(id),
    FOREIGN KEY (region_id) REFERENCES region(id)
);

-- 센서 데이터 내역
CREATE TABLE sensor_raw(
	id INT PRIMARY KEY AUTO_INCREMENT,                          -- 내역 ID
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,    -- 생성일
    sensor_id INT NOT NULL,                                     -- 개별 센서 ID
    value FLOAT NOT NULL,                                       -- 센서값

    FOREIGN KEY (sensor_id) REFERENCES sensor(id),
    index idx_created_at (created_at)
);

-- 구간별(5분) 센서 데이터 집계
CREATE TABLE sensor_history(
    time_bucket TIMESTAMP NOT NULL,     -- 구간 시작 시간
    sensor_id INT NOT NULL,             -- 개별 센서 ID
    max_val FLOAT NOT NULL,             -- 구간 내 최댓값
    min_val FLOAT NOT NULL,             -- 구간 내 최솟값
    avg_val FLOAT NOT NULL,             -- 구간 내 평균값

    PRIMARY KEY(time_bucket, sensor_id),
    FOREIGN KEY (sensor_id) REFERENCES sensor(id)
);

-- IoT 장비 유형
CREATE TABLE actuator_type(
	id INT PRIMARY KEY,                     -- 장비 유형 ID
    type_name VARCHAR(20) NOT NULL UNIQUE   -- 장비 유형 이름(예. 허브, 환풍기, 조명)
);

-- 개별 IoT 장비 현황
CREATE TABLE actuator(
	id INT PRIMARY KEY,             -- 개별 장비 ID
    type_id INT NOT NULL,           -- 장비 유형 ID
    region_id INT NOT NULL,         -- 재배지 ID
    state VARCHAR(30) NOT NULL,     -- 장비 상태
    last_signal TIMESTAMP NOT NULL, -- 마지막 신호 연결

    FOREIGN KEY (type_id) REFERENCES actuator_type(id),
    FOREIGN KEY (region_id) REFERENCES region(id)
);

-- 작물 로봇
CREATE TABLE robot(
    id INT PRIMARY KEY,             -- 로봇 ID
    region_id INT NOT NULL,         -- 재배지 ID
    name VARCHAR(30) NOT NULL,      -- 로봇 이름
    state VARCHAR(50) NOT NULL,     -- 로봇 상태
    last_signal TIMESTAMP NOT NULL, -- 마지막 신호 연결
    map VARCHAR(50) NULL,           -- 지도 튜플 이름

    FOREIGN KEY (region_id) REFERENCES region(id)
);

-- 로봇 주행 파라미터
CREATE TABLE robot_parameter(
    robot_id    INT         PRIMARY KEY,        -- 로봇 ID
    controller  VARCHAR(20) NOT NULL DEFAULT 'RPP', -- 현재 활성 주행 알고리즘
    rpp         JSON        NOT NULL,           -- RPP 모드 파라미터 {speed, tolerance, inflation}
    safe        JSON        NOT NULL,           -- SAFE 모드 파라미터 {speed, tolerance, inflation}
    ack         JSON        NOT NULL,           -- ACK 모드 파라미터 {speed, tolerance, inflation}

    FOREIGN KEY (robot_id) REFERENCES robot(id)
);

-- 로봇 상태 내역
CREATE TABLE robot_history (
	id INT PRIMARY KEY AUTO_INCREMENT,                          -- 이력 ID
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,    -- 이력 생성 시간
    robot_id INT NOT NULL,                                      -- 로봇 ID
    state VARCHAR(50) NOT NULL,                                 -- 로봇 상태

    FOREIGN KEY (robot_id) REFERENCES robot(id)
);

-- 5분 단위 센서 데이터 집계 프로시저
delimiter //
create event event_aggregate_sensor_5min
on schedule every 5 minute
starts current_TIMESTAMP
comment '5분 단위 센서 데이터 집계'
do
begin
    insert into sensor_history(time_bucket, sensor_id, max_val, min_val, avg_val)
    select
        from_unixtime(floor(unix_TIMESTAMP(created_at) / 300) * 300) as bucket,
        sensor_id,
        max(value) as max_val,
        min(value) as min_val,
        avg(value) as avg_val
    from sensor_raw
    where created_at >= now() - interval 15 minute
      and created_at < from_unixtime(floor(unix_TIMESTAMP(now()) / 300) * 300)
    group by bucket, sensor_id
    on duplicate key update
        max_val = values(max_val),
        min_val = values(min_val),
        avg_val = values(avg_val);
end //
delimiter ;