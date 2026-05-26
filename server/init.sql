create database farm;
use farm;

SET GLOBAL event_scheduler = ON;

-- 작물 유형
create table plant_type(
	id int primary key,                 -- 작물 유형 ID
    name varchar(30) not null unique    -- 작물 이름(예. 토마토, 딸기...)
);

-- 개별 작물 정보
create table plant(
	id int primary key,         -- 개별 작물 ID
    name varchar(30) not null,  -- 개별 작물 이름(예. 토마토1, 딸기3...)
    type_id int not null,       -- 작물 유형 ID
    maturity float not null,    -- 작물 성장률(0~1)
    is_disease bool not null,   -- 작물 병해 여부

    foreign key (type_id) references plant_type(id)
);

-- 일일 작물 정보 통계(작물별)
create table plant_statistics(
	id int auto_increment primary key,                          -- 로그 ID
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,    -- 생성 시간
    type_id int not null,                                       -- 작물 유형 ID
    avg_maturity float not null,                                -- 작물군의 평균 성장도(0~1)
    disease_ratio float not null,                               -- 작물군의 평균 병해율(0~1)

    foreign key (type_id) references plant_type(id)
);

-- 센서 유형
create table sensor_type(
	id tinyint primary key,                 -- 센서 유형 ID
    type_name varchar(20) not null unique   -- 센서 유형 이름(예. 조도, 온도...)
    # "조도", "온도", "습도" ...
);

-- 개별 센서 최신값
create table sensor(
	id int primary key,         -- 개별 센서 ID
    type_id tinyint not null,   -- 센서 유형 ID
    value float not null,       -- 센서값

    foreign key (type_id) references sensor_type(id)
);

-- 센서 데이터 내역
create table sensor_raw(
	id int primary key auto_increment,                          -- 내역 ID
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,    -- 생성일
    sensor_id int not null,                                     -- 개별 센서 ID
    value float not null,                                       -- 센서값

    foreign key (sensor_id) references sensor(id)
);

-- 구간별(5분) 센서 데이터 집계
create table sensor_history(
    time_bucket timestamp not null, -- 구간 시작 시간
    sensor_id int not null,         -- 개별 센서 ID
    max float not null,             -- 구간 내 최댓값
    min float not null,             -- 구간 내 최솟값
    avg float not null,             -- 구간 내 평균값

    primary key(time_bucket, sensor_id),
    foreign key (sensor_id) references sensor(id)
);

-- 로봇 상태 내역
create table robot_history (
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    -- robot_id int not null,
    state varchar(40) not null
);

-- 5분 단위 센서 데이터 집계 프로시저
delimiter //
create event event_aggregate_sensor_5min
on schedule every 5 minute
starts current_timestamp
comment '5분 단위 센서 데이터 집계'
do
begin
    insert into sensor_history (time_bucket, sensor_id, max, min, avg)
    select
        from_unixtime(floor(unix_timestamp(created_at) / 300) * 300) as bucket,
        sensor_id,
        max(value) as max_val,
        min(value) as min_val,
        avg(value) as avg_val
    from sensor_raw
    where created_at >= now() - interval 15 minute
      and created_at < from_unixtime(floor(unix_timestamp(now()) / 300) * 300)
    group by bucket, sensor_id
    on duplicate key update
        max = values(max),
        min = values(min),
        avg = values(avg);
end //
delimiter ;