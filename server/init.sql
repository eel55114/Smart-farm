create database farm;
use farm;

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

create table sensor_history(
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    sensor_id int not null,
    value float not null,
    foreign key (sensor_id) references sensor(id)
);

create table robot_history (
	id int primary key auto_increment,
    created_at timestamp not null DEFAULT CURRENT_TIMESTAMP,
    -- robot_id int not null,
    state varchar(30) not null
);

--insert into farm.sensor_type(id, type_name) values(1, "illuminance");
--insert into farm.sensor_type(id, type_name) values(2, "humidity");
--insert into farm.sensor_type(id, type_name) values(3, "temperature");


