create database farm;
use farm;

SET GLOBAL event_scheduler = ON;

# 작물 종류
create table plant_type(
	id int primary key,
    name varchar(30) not null
);

# 작물 정보
create table plant(
	id int primary key,
    name varchar(30) not null,
    type_id int not null,
    maturity float not null,
    is_disease bool not null,

    foreign key (type_id) references plant_type(id)
);

create table plant_statistics(
	id int auto_increment primary key,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    type_id int not null,
    avg_maturity float not null,
    disease_ratio float not null,
    foreign key (type_id) references plant_type(id)
);

# 센서 종류
create table sensor_type(
	id tinyint primary key,
    type_name varchar(20) not null
    # "조도", "온도", "습도" ...
);

# 각 센서들의 현재값
create table sensor(
	id int primary key,
    type_id tinyint not null,
    value float not null,
    foreign key (type_id) references sensor_type(id)
);

create table sensor_raw(
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    sensor_id int not null,
    value float not null,
    foreign key (sensor_id) references sensor(id)
);

create table sensor_history(
    time_bucket timestamp not null,
    sensor_id int not null,
    max float not null,
    min float not null,
    avg float not null,
    primary key(time_bucket, sensor_id),
    foreign key (sensor_id) references sensor(id)
);

create table robot_history (
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    -- robot_id int not null,
    state varchar(30) not null
);


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