from urllib.parse import scheme_chars

import pytest
from datetime import datetime, timedelta

import schema
import datatype
from manager import DBManager
import pymysql


@pytest.fixture
def db():
    test_db_url = DBManager.make_url(
        database="farm_test"
    )
    manager = DBManager(test_db_url)

    schema.Base.metadata.drop_all(manager.engine)
    manager.table_initialize()

    with manager.session_scope() as session:
        test_data = [
            schema.SensorType(id=1, type_name="illuminance"),
            schema.SensorType(id=2, type_name="humidity"),
            schema.SensorType(id=3, type_name="temperature"),
            schema.PlantType(id=1, name="tomato"),
            schema.Plant(id=1, type_id=1, name="Tomato1", maturity=0.5, is_disease=False)

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
        port=3307
    )
    expected_url = "mysql+pymysql://testuser:testpassword@192.168.0.1:3307/farm_test"
    assert url == expected_url


def test_add_new_sensor(db):
    """새로운 센서 추가 및 중복 추가 예외 테스트"""
    sensor_data = [
        datatype.Sensor(sensor_id=1, type_id=1, value=25.5)
    ]

    # 1. 정상 추가
    err = db.add_new_sensor(sensor_data)
    assert err is None

    # 2. 중복 추가 시 예외 발생 확인
    err_duplicate = db.add_new_sensor(sensor_data)
    assert err_duplicate is not None
    assert isinstance(err_duplicate, ValueError)
    assert "Sensor already exists" in str(err_duplicate)


def test_update_sensor_data(db):
    """센서 값 업데이트 및 기록(History) 추가 테스트"""
    # 초기 센서 세팅
    initial_sensor = [datatype.Sensor(sensor_id=1, type_id=1, value=10.0)]
    db.add_new_sensor(initial_sensor)

    # 센서 값 업데이트
    update_data = [datatype.Sensor(sensor_id=1, type_id=1, value=20.5)]
    err = db.update_sensor_data(update_data)
    assert err is None

    # 존재하지 않는 센서 업데이트 시 예외 발생 확인
    invalid_update_data = [datatype.Sensor(sensor_id=99, type_id=1, value=15.0)]
    err_invalid = db.update_sensor_data(invalid_update_data)
    assert err_invalid is not None
    assert isinstance(err_invalid, ValueError)


def test_get_sensor_history(db):
    """센서 히스토리 조회 테스트 (기간 포함)"""
    # 초기 세팅
    db.add_new_sensor([datatype.Sensor(sensor_id=1, type_id=1, value=0.0)])
    db.update_sensor_data([datatype.Sensor(sensor_id=1, type_id=1, value=1.0)])
    db.update_sensor_data([datatype.Sensor(sensor_id=1, type_id=1, value=2.0)])

    # 전체 히스토리 조회
    history, err = db.get_sensor_history(sensor_ids=[1])
    assert err is None
    assert len(history) == 2  # update_sensor_data가 호출될 때마다 history가 추가됨

    # 날짜 필터링 조회 (현재 시간 기준)
    now = datetime.now()
    start_date = now - timedelta(days=1)
    end_date = now + timedelta(days=1)

    history_filtered, err = db.get_sensor_history(
        sensor_ids=[1],
        start_date=start_date,
        end_date=end_date
    )
    assert err is None
    assert len(history_filtered) == 2


def test_update_and_get_robot_state(db):
    """로봇 상태 추가 및 조회 테스트"""
    # 상태 추가
    err1 = db.update_robot_state("IDLE")
    assert err1 is None

    err2 = db.update_robot_state("MOVING")
    assert err2 is None

    # 최근 로봇 상태 1개 조회
    state, err = db.get_robot_state()
    assert err is None
    assert state is not None
    assert state.state == "MOVING"

    # 히스토리 리스트 조회 (Limit 및 Offset)
    history, err = db.get_robot_history(n=2, offset=0)
    assert err is None
    assert len(history) == 2
    assert history[0].state == "MOVING"  # 내림차순 정렬이므로 최신 상태가 첫 번째
    assert history[1].state == "IDLE"


def test_update_and_get_plant_state(db):
    """작물 상태 업데이트 및 조회 테스트"""
    # 작물 상태 업데이트
    update_data = [
        datatype.Plant(id=1, type_id=100, name="Tomato_1", maturity=0.5, is_disease=True)
    ]
    err = db.update_plant(update_data)
    assert err is None

    # 업데이트되지 않은 잘못된 작물 ID 테스트
    invalid_data = [datatype.Plant(id=99, type_id=100, name="Unknown", maturity=0, is_disease=False)]
    err_invalid = db.update_plant(invalid_data)
    assert err_invalid is not None
    assert isinstance(err_invalid, ValueError)

    # 작물 상태 조회
    plants, err = db.get_plant_state(ids=[1])
    assert err is None
    assert len(plants) == 1
    assert plants[0].name == "Tomato_1"
    assert plants[0].maturity == 0.5
    assert plants[0].is_disease is True

def test_calculate_plant_statistics(db):

    with db.session_scope() as session:
        data = [
            schema.Plant(id=2, type_id=1, name="Tomato_2", maturity=0.5, is_disease=False),
            schema.Plant(id=3, type_id=1, name="Tomato_3", maturity=0.5, is_disease=False),

            schema.PlantType(id=2, name="berry"),
            schema.Plant(id=4, type_id=2, name="Berry_1", maturity=0.7, is_disease=False),
            schema.Plant(id=5, type_id=2, name="Berry_2", maturity=0.5, is_disease=True),
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