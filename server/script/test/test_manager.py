import math
import time
from datetime import datetime

import pytest
from script.db_manager import datatype, schema
from script.db_manager.manager import DBManager
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def db():
    test_db_url = DBManager.make_url(database="farm_test")
    manager = DBManager(test_db_url)

    schema.Base.metadata.drop_all(manager.engine)
    manager.table_initialize()

    with manager.session_scope() as session:
        test_data = [
            # 지역
            schema.Region(id=1, name="온실"),
            schema.Region(id=2, name="정원"),
            schema.Region(id=3, name="옥상"),
            # 센서 타입
            schema.SensorType(id=1, type_name="조도"),
            schema.SensorType(id=2, type_name="습도"),
            schema.SensorType(id=3, type_name="온도"),
            schema.SensorType(id=4, type_name="화염"),
            # 액추에이터 타입
            schema.ActuatorType(id=1, type_name="환풍기"),
            schema.ActuatorType(id=2, type_name="급수기"),
            schema.ActuatorType(id=3, type_name="조명"),
            # 작물 타입
            schema.PlantType(id=1, name="토마토"),
            schema.PlantType(id=2, name="딸기"),
            schema.PlantType(id=3, name="수박"),
            # 작물
            schema.Plant(
                id=1,
                type_id=1,
                region_id=1,
                name="토마토1",
                maturity=0.2,
                is_disease=False,
            ),
            schema.Plant(
                id=2,
                type_id=1,
                region_id=1,
                name="토마토2",
                maturity=0.5,
                is_disease=True,
            ),
            schema.Plant(
                id=3,
                type_id=2,
                region_id=1,
                name="딸기1",
                maturity=0.6,
                is_disease=True,
            ),
            schema.Plant(
                id=4,
                type_id=3,
                region_id=3,
                name="수박1",
                maturity=0.9,
                is_disease=False,
            ),
            # 로봇
            schema.Robot(
                id=1,
                region_id=1,
                name="bot_1",
                state="-",
                last_signal=datetime.now(),
            ),
            schema.Robot(
                id=2,
                region_id=1,
                name="bot_2",
                state="-",
                last_signal=datetime.now(),
            ),
            schema.Robot(
                id=3,
                region_id=2,
                name="bot_3",
                state="-",
                last_signal=datetime.now(),
            ),
        ]

        session.add_all(test_data)
        session.commit()

    yield manager

    manager.session_local.remove()
    schema.Base.metadata.drop_all(manager.engine)
    manager.engine.dispose()


def test_make_url():
    """make_url 정적 메서드 정상 동작 테스트"""
    url = DBManager.make_url(
        database="farm_test",
        username="testuser",
        password="testpassword",
        host="192.168.0.1",
        port=3307,
    )
    expected_url = "mysql+pymysql://testuser:testpassword@192.168.0.1:3307/farm_test"
    assert url == expected_url


def test_add_new_sensor(db: DBManager):
    """새로운 센서 추가 및 중복 추가 예외 테스트"""
    sensor_data = [datatype.Sensor(id=1, region_id=1, type_id=1, value=25.5)]

    # 1. 정상 추가
    err_none = db.add_new_sensor(sensor_data)
    assert err_none is None

    # 2. 중복 추가 시 예외 발생
    err_duplicate = db.add_new_sensor(sensor_data)
    assert err_duplicate is not None
    assert isinstance(err_duplicate, ValueError)
    assert "Sensor already exists" in str(err_duplicate)

    # 3. 존재하지 않는 타입 추가 시 예외 발생
    sensor_data = [datatype.Sensor(id=2, region_id=1, type_id=9999, value=25.5)]
    err_invalid_type = db.add_new_sensor(sensor_data)
    assert err_invalid_type is not None
    assert isinstance(err_invalid_type, IntegrityError)
    assert "Cannot add or update a child row" in str(err_invalid_type)

    # 4. 존재하지 않는 지역 추가 시 예외 발생
    sensor_data = [datatype.Sensor(id=2, region_id=9999, type_id=1, value=25.5)]
    err_invalid_region = db.add_new_sensor(sensor_data)
    assert err_invalid_region is not None
    assert isinstance(err_invalid_region, IntegrityError)
    assert "Cannot add or update a child row" in str(err_invalid_region)

    # 5. name 필드가 정상적으로 저장되고 조회되는지 테스트
    sensor_with_name = [datatype.Sensor(id=10, region_id=1, type_id=1, value=20.0, name="테스트 센서 A")]
    err = db.add_new_sensor(sensor_with_name)
    assert err is None
    
    current_sensors, err = db.get_current_sensor(sensor_ids=[10])
    assert err is None
    assert len(current_sensors) == 1
    assert current_sensors[0].name == "테스트 센서 A"


def test_update_sensor(db: DBManager):
    # 초기 센서 세팅
    initial_sensor = [datatype.Sensor(id=1, region_id=1, type_id=1, value=10)]
    db.add_new_sensor(initial_sensor)

    # 1. 센서 값 업데이트
    prev = math.floor(time.time())
    value = 25.5
    update_data = [datatype.Sensor(id=1, value=value)]
    err_none = db.update_sensor(update_data)
    assert err_none is None

    session = db.session_local()
    sensor = session.get(schema.Sensor, 1)

    assert sensor is not None
    assert sensor.value == value
    last_signal = sensor.last_signal.timestamp()
    now = math.ceil(time.time())
    # 자동 시간 기록 검증
    assert prev <= last_signal <= now

    # 2. 존재하지 않는 센서 업데이트 시 예외 발생
    invalid_update_data = [datatype.Sensor(id=9999, value=25.5)]
    err_invalid = db.update_sensor(invalid_update_data)
    assert err_invalid is not None
    assert isinstance(err_invalid, ValueError)

    # # 3. 시간 수동/자동 입력
    # now = time.time()
    # now_date = datetime.fromtimestamp(now)

    # target_time = 100
    # target_date = datetime.fromtimestamp(target_time)


def test_get_current_sensor(db: DBManager):
    sensors_spec = [
        {
            "id": 4,
            "type_id": 1,
            "region_id": 1,
            "value": 0.5,
            "last_signal": datetime.fromtimestamp(100),
        },
        {
            "id": 5,
            "type_id": 2,
            "region_id": 1,
            "value": 0.4,
            "last_signal": datetime.fromtimestamp(1000),
        },
        {
            "id": 6,
            "type_id": 3,
            "region_id": 1,
            "value": 0.3,
            "last_signal": datetime.fromtimestamp(10000),
        },
    ]

    session = db.session_local()
    sensors = [schema.Sensor(**spec) for spec in sensors_spec]
    session.add_all(sensors)
    session.commit()

    # 1. 전체 검색
    results, err_none = db.get_current_sensor()
    assert err_none is None
    results = [
        {
            "id": i.id,
            "type_id": i.type_id,
            "region_id": i.region_id,
            "value": i.value,
            "last_signal": i.last_signal,
        }
        for i in results
    ]
    assert results == sensors_spec

    # 2. 부분 검색
    results, err_none = db.get_current_sensor([5, 6, 7])
    assert err_none is None
    results = [
        {
            "id": i.id,
            "type_id": i.type_id,
            "region_id": i.region_id,
            "value": i.value,
            "last_signal": i.last_signal,
        }
        for i in results
    ]
    assert results == sensors_spec[1:]


def test_get_sensor_history(db: DBManager):
    # 초기 세팅
    sensor_spec = [
        {
            "id": 1,
            "region_id": 1,
            "type_id": 1,
            "value": 10.0,
            "last_signal": datetime.fromtimestamp(10),
        },
        {
            "id": 2,
            "region_id": 1,
            "type_id": 2,
            "value": 20.0,
            "last_signal": datetime.fromtimestamp(20),
        },
    ]
    for data in sensor_spec:
        db.add_new_sensor([datatype.Sensor(**data)])

    session = db.session_local()
    histories_data = [
        schema.SensorHistory(
            time_bucket=datetime.fromtimestamp(100),
            sensor_id=1,
            max_val=15.0,
            min_val=5.0,
            avg_val=10.0,
        ),
        schema.SensorHistory(
            time_bucket=datetime.fromtimestamp(200),
            sensor_id=1,
            max_val=16.0,
            min_val=6.0,
            avg_val=11.0,
        ),
        schema.SensorHistory(
            time_bucket=datetime.fromtimestamp(300),
            sensor_id=2,
            max_val=25.0,
            min_val=15.0,
            avg_val=20.0,
        ),
    ]
    session.add_all(histories_data)
    session.commit()

    # 1. 전체 히스토리 조회
    histories, count, err = db.get_sensor_history()
    assert err is None
    assert count == 3

    # 2. 필터링 및 페이징 조회
    histories, count, err = db.get_sensor_history(sensor_ids=[1], n=2, offset=0)
    assert err is None
    assert count == 2
    assert len(histories) == 2


def test_update_robot(db: DBManager):
    robot_data = [
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(100)},
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(1000)},
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(10000)},
    ]

    # 1. 정상 다중 추가
    data = [datatype.Robot(**datum) for datum in robot_data]
    err_none = db.update_robot(data)
    assert err_none is None

    session = db.session_local()
    stmt = select(schema.RobotHistory).where(schema.RobotHistory.robot_id.in_([1]))
    result = session.scalars(stmt).all()
    assert len(result) == 3
    result = [
        {"id": i.robot_id, "state": i.state, "last_signal": i.created_at}
        for i in result
    ]
    assert result == robot_data

    # 2. 비정상 다중 추가(없는 ID)
    robot_data = [
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(100)},
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(1000)},
        {"id": 9999, "state": "대기", "last_signal": datetime.fromtimestamp(10000)},
    ]
    err_invalid_id = db.update_robot([datatype.Robot(**datum) for datum in robot_data])
    assert err_invalid_id is not None
    assert isinstance(err_invalid_id, ValueError)
    assert "There's no robot" in str(err_invalid_id)


def test_get_robot_history(db: DBManager):
    # 초기 설정

    robot_data = [
        {"id": 1, "state": "대기", "last_signal": datetime.fromtimestamp(100)},
        {"id": 1, "state": "주행", "last_signal": datetime.fromtimestamp(1000)},
        {"id": 1, "state": "충전", "last_signal": datetime.fromtimestamp(10000)},
        {"id": 2, "state": "대기", "last_signal": datetime.fromtimestamp(150)},
        {"id": 2, "state": "전복", "last_signal": datetime.fromtimestamp(1500)},
        {"id": 2, "state": "수동 조작", "last_signal": datetime.fromtimestamp(15000)},
    ]

    err_none = db.update_robot([datatype.Robot(**datum) for datum in robot_data])
    assert err_none is None

    # 1. 전체 정상 조회
    histories, count, err_none = db.get_robot_history()
    assert err_none is None
    assert count == len(robot_data)
    histories = [
        {
            "id": i.robot_id,
            "state": i.state,
            "last_signal": i.created_at,
        }
        for i in histories
    ]
    histories = sorted(histories, key=lambda x: x["last_signal"])
    histories = sorted(histories, key=lambda x: x["id"])
    assert histories == robot_data

    # 2. 부분 정상 조회
    histories, count, err_none = db.get_robot_history(robot_ids=[1], n=10, offset=1)
    assert err_none is None

    histories = [
        {
            "id": i.robot_id,
            "state": i.state,
            "last_signal": i.created_at,
        }
        for i in histories
    ]
    histories = sorted(histories, key=lambda x: x["last_signal"])
    histories = sorted(histories, key=lambda x: x["id"])

    assert histories == robot_data[:2]


def test_get_current_robot(db: DBManager):
    # 로봇은 db fixture에서 초기 3대 등록되어 있음
    results, err = db.get_current_robot()
    assert err is None
    assert len(results) == 3

    # 필터링 검색
    results, err = db.get_current_robot(robot_ids=[1])
    assert err is None
    assert len(results) == 1
    assert results[0].id == 1


def test_update_plant(db: DBManager):
    update_data = [
        datatype.Plant(id=1, maturity=0.8, is_disease=True, name="Tomato_Updated")
    ]
    err = db.update_plant(update_data)
    assert err is None

    session = db.session_local()
    plant = session.get(schema.Plant, 1)
    assert plant is not None
    assert plant.maturity == 0.8
    assert plant.is_disease is True
    assert plant.name == "Tomato_Updated"

    # 존재하지 않는 작물 업데이트 예외 테스트
    invalid_data = [datatype.Plant(id=9999, maturity=0.5, is_disease=False)]
    err_invalid = db.update_plant(invalid_data)
    assert err_invalid is not None
    assert isinstance(err_invalid, ValueError)


def test_get_current_plant(db: DBManager):
    results, err = db.get_current_plant()
    assert err is None
    assert len(results) == 4

    results, err = db.get_current_plant(plant_ids=[1])
    assert err is None
    assert len(results) == 1
    assert results[0].id == 1


def test_get_plant_statistics(db: DBManager):
    db.calculate_plant_statistics()

    stats, count, err = db.get_plant_statistics(type_ids=[1])
    assert err is None
    assert count > 0
    assert stats[0].type_id == 1


def test_calculate_plant_statistics(db: DBManager):
    with db.session_scope() as session:
        session.query(schema.Plant).delete()
        data = [
            schema.Plant(
                id=2,
                type_id=1,
                region_id=1,
                name="Tomato_2",
                maturity=0.5,
                is_disease=False,
            ),
            schema.Plant(
                id=3,
                type_id=1,
                region_id=1,
                name="Tomato_3",
                maturity=0.5,
                is_disease=False,
            ),
            schema.Plant(
                id=4,
                type_id=2,
                region_id=1,
                name="Berry_1",
                maturity=0.7,
                is_disease=False,
            ),
            schema.Plant(
                id=5,
                type_id=2,
                region_id=1,
                name="Berry_2",
                maturity=0.5,
                is_disease=True,
            ),
        ]
        session.add_all(data)
        session.commit()

    result, err = db.calculate_plant_statistics()

    assert err is None
    assert result[0].type_id == 1
    assert result[0].avg_maturity == pytest.approx(0.5)
    assert result[0].disease_ratio == pytest.approx(0)
    assert result[1].type_id == 2
    assert result[1].avg_maturity == pytest.approx(0.6)
    assert result[1].disease_ratio == pytest.approx(0.5)


def test_get_active_plant_type(db: DBManager):
    types, err = db.get_active_plant_type()
    assert err is None
    assert 1 in types
    assert types[1] == "토마토"


def test_update_actuator(db: DBManager):
    session = db.session_local()
    new_actuator = schema.Actuator(
        id=1, type_id=1, region_id=1, state="정지", last_signal=datetime.now()
    )
    session.add(new_actuator)
    session.commit()

    update_data = [datatype.Actuator(id=1, state="가동")]
    err = db.update_actuator(update_data)
    assert err is None

    actuator = session.get(schema.Actuator, 1)
    assert actuator is not None
    assert actuator.state == "가동"

    invalid_data = [datatype.Actuator(id=9999, state="정지")]
    err_invalid = db.update_actuator(invalid_data)
    assert err_invalid is not None
    assert isinstance(err_invalid, ValueError)


def test_get_current_actuator(db: DBManager):
    session = db.session_local()
    new_actuator = schema.Actuator(
        id=2, type_id=1, region_id=1, state="정지", last_signal=datetime.now()
    )
    session.add(new_actuator)
    session.commit()

    results, err = db.get_current_actuator(actuator_ids=[2])
    assert err is None
    assert len(results) == 1
    assert results[0].id == 2
