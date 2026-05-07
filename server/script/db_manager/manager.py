from contextlib import contextmanager
from datetime import datetime

from . import datatype
from . import schema
from sqlalchemy import create_engine, select, func, cast, Float
from sqlalchemy.orm import joinedload, scoped_session, sessionmaker, contains_eager


class DBManager:
    def __init__(self, conn_url: str):
        self.engine = create_engine(conn_url)
        self.session_local = scoped_session(sessionmaker(bind=self.engine))

    def table_initialize(self):
        schema.Base.metadata.create_all(self.engine)

    def add_new_sensor(self, data: list[datatype.Sensor]) -> Exception | None:
        """
        `sensor` 테이블에 (1개 이상의) 새 센서를 추가합니다.
        센서 현재 상태를 업데이트하는 것이 아닌 새로운 센서 장치를 추가합니다.

        Args:
            data (list[datatype.Sensor]): 새 센서(들). 필수 필드(sensor_id, type_id), 선택 필드(value)

        Returns:
            Exception | None: 작업 중 발생한 예외

        """
        session = self.session_local()
        try:
            for datum in data:
                sensor = session.get(schema.Sensor, datum.sensor_id)

                if sensor is not None:
                    return ValueError(f"Sensor already exists: {datum.sensor_id}")

                new_sensor = schema.Sensor(
                    id=datum.sensor_id,
                    type_id=datum.type_id,
                    value=datum.value,
                )

                session.add(new_sensor)
            session.commit()
        except Exception as e:
            session.rollback()
            return e
        return None

    def update_sensor_data(self, data: list[datatype.Sensor]) -> Exception | None:
        """
        `sensor`와 `sensor_history` 테이블에 센서값을 업데이트합니다.

        Args:
            data (list[datatype.Sensor]): 센서(들)의 정보. 필수 필드(sensor_id, value)

        Returns:
            Exception | None: 작업 중 발생한 예외

        """
        session = self.session_local()
        try:
            for datum in data:
                sensor = session.get(schema.Sensor, datum.sensor_id)

                if sensor:
                    sensor.value = datum.value
                else:
                    return ValueError(f"Invalid sensor id: {datum.sensor_id}")

                new_history = schema.SensorHistory(
                    sensor_id=sensor.id,
                    value=datum.value,
                )

                session.add(new_history)
            session.commit()
        except Exception as e:
            session.rollback()
            return e
        return None

    def get_current_sensors(
        self, sensor_ids: list[int]
    ) -> tuple[list[datatype.Sensor], Exception | None]:
        """
        `sensor` 테이블에 기록된 가장 최신의 센서 값을 가져옵니다.

        Args:
            sensor_ids (list[int]): 가져올 센서(들)의 ID

        Returns:
            tuple[result, error]:
                - result (list[datatype.Sensor]): 결과. 필드(sensor_id, value, type_name)
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = (
                select(schema.Sensor)
                .options(joinedload(schema.Sensor.sensor_type))
                .where(schema.Sensor.id.in_(sensor_ids))
            )

            data = session.scalars(stmt).all()
            result = []

            for datum in data:
                type_name = datum.sensor_type.type_name

                temp = datatype.Sensor(
                    sensor_id=datum.id, value=datum.value, type_name=type_name
                )
                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def get_sensor_history(
        self,
        sensor_ids: list[int],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[datatype.SensorHistory], Exception | None]:
        """
        `sensor_history`에 기록된 데이터를 가져옵니다.
        검색 범위 인자를 설정하지 않으면 제한 없이 조회합니다.

        Args:
            sensor_ids (list[int]): 가져올 센서들의 ID
            start_date (datetime.datetime, optional): 검색 범위 시작일
            end_date (datetime.datetime, optional): 검색 범위 시작일

        Returns:
            tuple[result, error]:
                - result (list[datatype.SensorHistory])
                - error (Exception | None): 발생한 에러

        """
        session = self.session_local()

        try:
            stmt = select(schema.SensorHistory).where(
                schema.SensorHistory.sensor_id.in_(sensor_ids)
            )

            if start_date is not None:
                stmt = stmt.where(schema.SensorHistory.created_at >= start_date)
            if end_date is not None:
                stmt = stmt.where(schema.SensorHistory.created_at <= end_date)

            data = session.scalars(stmt).all()
            result = []

            for datum in data:
                temp = datatype.SensorHistory(
                    id=datum.id,
                    sensor_id=datum.sensor_id,
                    created_at=datum.created_at,
                    value=datum.value,
                )
                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def update_robot_state(self, state: str) -> Exception | None:
        """
        `robot_history` 테이블에 로봇 상태를 추가합니다.

        Args:
            state (str): 로봇의 현재 상태 문자열

        Returns:
            Exception | None: 발생한 에러

        """
        session = self.session_local()

        try:
            new_state = schema.RobotHistory(
                state = state
            )

            session.add(new_state)
            session.commit()

            return None
        except Exception as e:
            session.rollback()
            return e

    def get_robot_history(
            self,
            n:int|None=None,
            offset:int|None=None) -> tuple[list[datatype.RobotState], Exception | None]:
        """
        `sensor_history`에 기록된 로봇 상태를 가져옵니다.
        검색 범위 인자를 설정하지 않으면 제한 없이 조회합니다.

        Args:
            n (int, optional): 검색 개수
            offset (int, optional): 최신 기록으로부터 떨어진 거리

        Returns:
            tuple[result, error]:
                - result (list[datatype.RobotState])
                - error (Exception | None): 발생한 에러

        """

        session = self.session_local()

        try:
            stmt = select(schema.RobotHistory).order_by(schema.RobotHistory.id.desc())

            if offset is not None:
                stmt = stmt.offset(offset)
            if n is not None:
                stmt = stmt.limit(n)

            data = session.scalars(stmt)

            result = []

            for datum in data:
                temp = datatype.RobotState(
                    id = datum.id,
                    created_at = datum.created_at,
                    state = datum.state
                )

                result.append(temp)

            return result, None
        except Exception as e:
            session.rollback()
            return [], e


    def get_robot_state(self) -> tuple[datatype.RobotState, Exception | None]:
        """
        `sensor_history`에 기록된 로봇의 현재 상태(최신 기록 1개)를 가져옵니다.

        Returns:
            tuple[result, error]:
                - result (datatype.RobotState)
                - error (Exception | None): 발생한 에러
        """
        result, err = self.get_robot_history(n=1)

        if result is not None:
            result = result[0]

        return result, err

    def update_plant(self, data:list[datatype.Plant]) -> Exception | None:
        """
        `plant` 테이블에 식물 정보를 업데이트합니다.

        Args:
            data (list[datatype.Plant]): 수정할 작물

        Returns:
            Exception | None: 발생한 에러

        """
        session = self.session_local()
        try:
            for datum in data:
                plant = session.get(schema.Plant, datum.id)

                if plant is not None:
                    if datum.name is not None:
                        plant.name = datum.name

                    plant.maturity = datum.maturity
                    plant.is_disease = datum.is_disease
                else:
                    return ValueError(f"Invalid plant_id: {datum.id}")

            session.commit()
            return None

        except Exception as e:
            session.rollback()
            return e

    def get_plant_state(self, ids:list[int], all:bool = False) -> tuple[list[datatype.Plant], Exception | None]:
        """
        `plant` 테이블의 현재 상태를 가져옵니다

        Args:
            ids (list[int]): 가져올 작물들의 ID
            all (bool): 전체 가져오기. default=false

        Returns:
            tuple[result, error]:
            - result (list[datatype.Plant]): 결과
            - error (Exception | None): 발생한 에러
        """

        session = self.session_local()
        try:
            stmt = select(schema.Plant)
            if not all:
                stmt = stmt.where(schema.Plant.id.in_(ids))

            data = session.scalars(stmt).all()
            result = []
            for datum in data:
                temp = datatype.Plant(
                    id = datum.id,
                    type_id = datum.type_id,
                    name = datum.name,
                    maturity = datum.maturity,
                    is_disease = datum.is_disease
                )

                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def get_plant_statistics(
            self,
            type_ids:list[int],
            start_date:datetime|None = None,
            end_date:datetime|None = None,
            n:int|None = None,
            offset:int|None = None
    ) -> tuple[list[datatype.Plant], Exception | None]:
        """
        `plant_statistics`에 기록된 로그를 가져옵니다.

        Args:
            type_ids (list[int]): 가져올 작물의 유형(들)
            start_date (datetime, optional): 검색 시작일
            end_date (datetime, optional): 검색 종료일
            n (int, optional): 데이터의 최대 개수 (pagination에 사용)
            offset (int, optional): 최신 데이터와의 오프셋 (pagination에 사용)

        Returns:
            tuple[result, error]:
            - result (list[datatype.PlantStatistics])
            - error (Exception | None): 발생한 에러
        """

        session = self.session_local()
        try:
            stmt = (
                select(schema.PlantStatistics)
                .where(schema.PlantStatistics.type_id.in_(type_ids))
                .order_by(schema.PlantStatistics.id.desc())
            )

            if start_date is not None:
                stmt = stmt.where(schema.PlantStatistics.created_at >= start_date)
            if end_date is not None:
                stmt = stmt.where(schema.PlantStatistics.created_at < end_date)
            if n is not None:
                stmt = stmt.limit(n)
            if offset is not None:
                stmt = stmt.offset(offset)

            data = session.scalars(stmt).all()

            result = []
            for datum in data:
                result.append(datatype.PlantStatistics(
                    id = datum.id,
                    created_at = datum.created_at,
                    type_id = datum.type_id,
                    avg_maturity = datum.avg_maturity,
                    disease_ratio = datum.disease_ratio
                ))

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def calculate_plant_statistics(self) -> tuple[list[datatype.PlantStatistics], Exception | None]:
        """
        현재 시점을 기준으로 `plant` 테이블의 정보를 작물 종류별로 취합한 스냅샷을 저장합니다.

        Returns:
            tuple[result, error]:
                - result (list[PlantStatistics]): 생성된 스냅샷
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()

        try:
            stmt = select(
                schema.Plant.type_id,
                func.avg(schema.Plant.maturity).label("avg_maturity"),
                func.avg(cast(schema.Plant.is_disease, Float)).label("disease_ratio")
            ).group_by(schema.Plant.type_id)


            data = session.execute(stmt).all()

            result = []
            stats = []
            for datum in data:
                result.append(datatype.PlantStatistics(
                    type_id = datum.type_id,
                    avg_maturity = datum.avg_maturity,
                    disease_ratio= datum.disease_ratio
                ))

                stats.append(schema.PlantStatistics(
                    type_id = datum.type_id,
                    avg_maturity = datum.avg_maturity,
                    disease_ratio= datum.disease_ratio
                ))

            session.add_all(stats)
            session.commit()

            return result, None
        except Exception as e:
            session.rollback()
            return [], e

    def get_active_plant_type(self) -> tuple[dict[int, str], Exception | None]:
        """
        현재 `plant`테이블에 기록된 작물에 해당하는 `plant_type`을 가져옵니다.

        Returns:
            tuple[result, error]:
            - result (dict[int, str): 각 작물 타입에 대한 (타입 ID, 타입명)
            - error (Exception | None): 발생한 에러
        """

        session = self.session_local()
        try:
            stmt = (select(schema.PlantType)
                    .join(schema.PlantType.plants) # Plant 테이블과 INNER JOIN
                    .distinct())

            data = session.scalars(stmt).all()
            result = dict()
            for datum in data:
                result[datum.id] = datum.name

            return result, None
        except Exception as e:
            session.rollback()
            return dict(), e


    @contextmanager
    def session_scope(self):
        try:
            yield self.session_local()
        finally:
            self.session_local.remove()

    @staticmethod
    def make_url(
        database: str,
        username: str = "root",
        password: str = "0000",
        host: str = "127.0.0.1",
        port: int = 3306,
    ):
        return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"


if __name__ == "__main__":
    url = DBManager.make_url(database="farm")
    print(url)
    db = DBManager(url)
    with db.session_scope() as session:
        print(db.get_active_plant_type())