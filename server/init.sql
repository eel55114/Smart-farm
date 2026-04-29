create database farm;
use farm;

-- create table zone(
-- 	id int primary key,
--     name varchar(20)
-- );

# 개별 작물의 현재 상태
create table plant_stat(
	plant_id int primary key,
    maturity float not null,
    is_disease bool not null
);

create table plant_history(
	id int auto_increment primary key,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
	plant_id int not null,
    maturity_rate float not null,
    disease_rate float not null,
    foreign key (plant_id) references plant_stat(plant_id)
);

# 센서 종류
create table sensor_type (
	id tinyint primary key,
    type_name varchar(20) not null
    # "조도", "온도", "습도" ...
);

# 각 센서들의 현재값
create table sensor(
	id int primary key,
    type_id tinyint not null,
    value float,
    foreign key (type_id) references sensor_type(id)
);

create table sensor_history(
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    sensor_id int not null,
    value float,
    foreign key (sensor_id) references sensor(id)
);

-- create table robot_stat(
-- 	id int primary key,
--     stat varchar(20) not null
--     # "시작", "순찰", "수동주행", "충전 중", "이동 중", "이동불능" ...
-- );

create table robot_history (
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    -- robot_id int not null,
    stat varchar(30) not null
);

insert into farm.sensor_type(id, type_name) values(0, "illuminance");
insert into farm.sensor_type(id, type_name) values(1, "humidity");
insert into farm.sensor_type(id, type_name) values(2, "temperature");


