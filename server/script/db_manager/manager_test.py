import manager
import schema
import datatype

import inspect

def p(*txt):
    # 현재 코드가 실행되는 줄 번호를 반환합니다.
    caller_line = inspect.currentframe().f_back.f_lineno
    print(f"{caller_line} >", *txt)

from sqlalchemy import create_engine
url = manager.DBManager.make_url(database="farm_t")

db = manager.DBManager(url)
schema.Base.metadata.drop_all(db.engine)
schema.Base.metadata.create_all(db.engine)

# DB 초기화
with db.session_scope() as session:
    # insert into farm.sensor_type(id, type_name) values(1, "illuminance");
    # insert into farm.sensor_type(id, type_name) values(2, "humidity");
    # insert into farm.sensor_type(id, type_name) values(3, "temperature");

    for idx, name in enumerate(["illuminance", "humidity", "temperature"]):
        temp = schema.SensorType(id=idx+1, type_name=name)
        session.add(temp)
    session.commit()
# 세션 삭제 검증

with db.session_scope() as session:
    # ---------------
    p("정상:: 센서 추가")
    err = db.add_new_sensor(data=[
        # 1번/습도/값 없음
        datatype.Sensor(
            sensor_id=1,
            value=None,
            type_id = 2,
        ),
        # 3번/조도/50%
        datatype.Sensor(
            sensor_id=3,
            value=0.5,
            type_id = 1,
        ),
    ])

    if err:
        p("의도하지 않은 에러:", err)
        # 에러 발생시 종료
        exit()

    # ---------------
    p("정상:: 센서 값 업데이트")
    err = db.update_sensor_data([
        # 1번/35%
        datatype.Sensor(
            sensor_id=1,
            value=0.35,
        ),
        # 3번/없는 타입/값 없음 <- 센서 타입 정보는 무시됨
        datatype.Sensor(
            sensor_id=3,
            value=None,
            type_id = 7,
        ),
    ])

    if err:
        p("의도하지 않은 에러:", err)
        # 에러 발생시 종료
        exit()

    # ---------------
    p("에러:: 센서 값 업데이트")
    err = db.update_sensor_data([
        # 2번 <- 존재하지 않는 센서
        datatype.Sensor(
            sensor_id=2,
            value=0.35
        )
    ])

    if err and isinstance(err, ValueError):
        p("목표 에러:", err)
    else:
        p("에러 발생 실패")
        exit()
    #
    p("정상:: 현재 센서 확인")
    sensors, err = db.get_current_sensors(
        sensor_ids=[1, 3],
    )


    if err:
        p("의도하지 않은 에러:", err)
        # 에러 발생시 종료
        exit()

    else:
        ''



    # ---------------
    p("정상:: 센서 값 업데이트")