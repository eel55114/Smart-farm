import schema
import datatype

from sqlalchemy import (
    create_engine,
    select
)

from sqlalchemy.orm import (
    scoped_session, sessionmaker
)


class DBManager:
    def __init__(self, conn_url:str):
        self.engine = create_engine(conn_url)
        self.session_local = scoped_session(sessionmaker(bind=self.engine))

        ''
    def put_new_sensor(self, data: list[datatype.SensorData]) -> tuple[bool, Exception | None]:
        with self.session_local() as session:
            try:
                for datum in data:
                    new_sensor = schema.Sensor(
                        sensor_id=datum.sensor_id,
                        sensor_type=datum.type_id,
                        value=datum.value
                    )

                    if sensor:
                        sensor.value = datum.sensor_value
                    else:
                        return False, Exception(f"Invalid sensor id: {datum.sensor_id}")
                    new_history = schema.SensorHistory(
                        sensor_id=sensor.sensor_id,
                        value=datum.value,
                    )
                    session.add(new_history)

                    session.commit()
            except Exception as e:
                session.rollback()
                return False, e
        return True, None

    def put_sensor_data(self, data: list[datatype.SensorData]) -> tuple[bool, Exception | None]:
        with self.session_local() as session:
            try:
                for datum in data:
                    sensor = session.get(schema.SensorData, datum.sensor_id)

                    if sensor:
                        sensor.value = datum.sensor_value
                    else:
                        return False, Exception(f"Invalid sensor id: {datum.sensor_id}")
                    new_history = schema.SensorHistory(
                        sensor_id=sensor.sensor_id,
                        value=datum.value,
                    )
                    session.add(new_history)

                    session.commit()
            except Exception as e:
                session.rollback()
                return False, e
        return True, None

    # todo
    def get_current_sensors(self, sensor_ids: list[int]) -> tuple[list[datatype.SensorData], Exception | None]:
        with self.session_local() as session:
            try:
                stmt = select(schema.Sensor).where(schema.SensorData.sensor_id.in_(sensor_ids))
            except Exception as e:
                session.rollback()
                return [], Exception(f"Invalid sensor ids: {sensor_ids}")

        # todo
        return [], None


    @staticmethod
    def make_url(
            database:str,
            username:str="root",
            password:str = "0000",
            host:str = "localhost",
            port:int = 3306
    ):
        return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"

if __name__ == '__main__':
    url = DBManager.make_url(database="farm")
    db = DBManager(url)