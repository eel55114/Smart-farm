from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Float, cast, create_engine, func, select, update
from sqlalchemy.orm import contains_eager, joinedload, scoped_session, sessionmaker

from . import datatype, schema


class DBManager:
    def __init__(self, conn_url: str):
        self.engine = create_engine(conn_url)
        self.session_local = scoped_session(sessionmaker(bind=self.engine))

    def table_initialize(self):
        schema.Base.metadata.create_all(self.engine)

    def get_current_sensor(
        self,
        sensor_ids: list[int] | None = None,
        regions: list[int] | None = None,
        types: list[int] | None = None,
    ) -> tuple[list[datatype.Sensor], Exception | None]:
        """
        `sensor` 테이블에 기록된 가장 최신의 센서 값을 가져옵니다.

        Args:
            sensor_ids (list[int], optional): 가져올 센서(들)의 ID
            regions (list[int], optional): 해당하는 지역
            types (list[int], optional): 해당하는 타입

        Returns:
            tuple[result, error]:
                - result (list[datatype.Sensor]): 결과. 필드(id, value, type_id, type_name, region_id, region_name, last_signal)
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.Sensor).options(
                joinedload(schema.Sensor.sensor_type),
                joinedload(schema.Sensor.region),
            )

            if sensor_ids:
                stmt = stmt.where(schema.Sensor.id.in_(sensor_ids))
            if regions:
                stmt = stmt.where(schema.Sensor.region_id.in_(regions))
            if types:
                stmt = stmt.where(schema.Sensor.type_id.in_(types))

            data = session.scalars(stmt).all()
            result = []

            for datum in data:
                temp = datatype.Sensor(
                    id=datum.id,
                    value=datum.value,
                    type_name=datum.sensor_type.type_name,
                    type_id=datum.sensor_type.id,
                    region_id=datum.region.id,
                    region_name=datum.region.name,
                    name=datum.name,
                    last_signal=datum.last_signal,
                )
                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def get_current_robot(
        self, robot_ids: list[int] | None = None, regions: list[int] | None = None
    ) -> tuple[list[datatype.Robot], Exception | None]:
        """
        `robot` 테이블에서 현재 로봇 정보를 가져옵니다.

        Args:
            robot_ids (list[int], optional): 조회할 로봇 ID
            regions (list[int], optional): 조회할 지역

        Returns:
            tuple[result, error]:
                - result (list[datatype.Robot])
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()

        try:
            stmt = select(schema.Robot)

            if robot_ids:
                stmt = stmt.where(schema.Robot.id.in_(robot_ids))
            if regions:
                stmt = stmt.where(schema.Robot.region_id.in_(regions))

            data = session.scalars(stmt).all()
            result = []
            for datum in data:
                temp = datatype.Robot(
                    id=datum.id,
                    state=datum.state,
                    region_id=datum.region_id,
                    name=datum.name,
                    last_signal=datum.last_signal,
                )

                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def get_current_plant(
        self,
        plant_ids: list[int] | None = None,
        regions: list[int] | None = None,
        types: list[int] | None = None,
    ) -> tuple[list[datatype.Plant], Exception | None]:
        """
        `plant` 테이블의 현재 상태를 가져옵니다

        Args:
            plant_ids (list[int], optional): 가져올 작물들의 ID
            regions (list[int], optional): 가져올 지역
            types (list[int], optional): 가져올 작물 유형

        Returns:
            tuple[result, error]:
            - result (list[datatype.Plant]): 결과
            - error (Exception | None): 발생한 에러
        """

        session = self.session_local()
        try:
            stmt = select(schema.Plant).options(joinedload(schema.Plant.region))

            if plant_ids:
                stmt = stmt.where(schema.Plant.id.in_(plant_ids))
            if regions:
                stmt = stmt.where(schema.Plant.region_id.in_(regions))
            if types:
                stmt = stmt.where(schema.Plant.type_id.in_(types))

            data = session.scalars(stmt).all()
            result = []
            for datum in data:
                temp = datatype.Plant(
                    id=datum.id,
                    type_id=datum.type_id,
                    region_id=datum.region_id,
                    region_name=datum.region.name,
                    name=datum.name,
                    maturity=datum.maturity,
                    is_disease=datum.is_disease,
                )

                result.append(temp)

            return result, None

        except Exception as e:
            session.rollback()
            return [], e

    def get_current_actuator(
        self,
        actuator_ids: list[int] | None = None,
        regions: list[int] | None = None,
        types: list[int] | None = None,
    ) -> tuple[list[datatype.Actuator], Exception | None]:
        """
        `actuator` 테이블의 현재 상태를 가져옵니다.

        Args:
            actuator_ids (list[int], optional): 가져올 액추에이터들의 ID
            regions (list[int], optional): 해당하는 지역
            types (list[int], optional): 해당하는 타입

        Returns:
            tuple[result, error]:
                - result (list[datatype.Actuator]): 결과
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()

        try:
            stmt = select(schema.Actuator).options(
                joinedload(schema.Actuator.region),
                joinedload(schema.Actuator.actuator_type),
            )

            if actuator_ids:
                stmt = stmt.where(schema.Actuator.id.in_(actuator_ids))
            if regions:
                stmt = stmt.where(schema.Actuator.region_id.in_(regions))
            if types:
                stmt = stmt.where(schema.Actuator.type_id.in_(types))

            data = session.scalars(stmt).all()
            result: list[datatype.Actuator] = []

            for datum in data:
                temp = datatype.Actuator(
                    id=datum.id,
                    state=datum.state,
                    type_id=datum.type_id,
                    region_id=datum.region_id,
                    type_name=datum.actuator_type.type_name,
                    region_name=datum.region.name,
                    last_signal=datum.last_signal,
                )

                result.append(temp)

            return result, None
        except Exception as e:
            session.rollback()
            return [], e

    def get_sensor_history(
        self,
        sensor_ids: list[int] | None = None,
        regions: list[int] | None = None,
        types: list[int] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        n: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[datatype.SensorHistory], int, Exception | None]:
        """
        `sensor_history`에 기록된 데이터를 가져옵니다.
        검색 범위 인자를 설정하지 않으면 제한 없이 조회합니다.

        Args:
            sensor_ids (list[int], optional): 가져올 센서들의 ID
            regions (list[int], optional): 가져올 지역
            types (list[int], optional): 가져올 센서 타입
            start_date (datetime.datetime, optional): 검색 범위 시작일
            end_date (datetime.datetime, optional): 검색 범위 종료일
            n (int, optional): 데이터의 최대 개수 (pagination에 사용)
            offset (int, optional): 최신 데이터와의 오프셋 (pagination에 사용)

        Returns:
            tuple[result, int, error]:
                - result (list[datatype.SensorHistory])
                - count (int): 전체 데이터 개수
                - error (Exception | None): 발생한 에러

        """
        session = self.session_local()

        try:
            base_stmt = (
                select(schema.SensorHistory)
                .join(schema.SensorHistory.sensor)
                .order_by(schema.SensorHistory.time_bucket.desc())
            )

            if sensor_ids:
                base_stmt = base_stmt.where(
                    schema.SensorHistory.sensor_id.in_(sensor_ids)
                )
            if regions:
                base_stmt = base_stmt.where(schema.Sensor.region_id.in_(regions))
            if types:
                base_stmt = base_stmt.where(schema.Sensor.type_id.in_(types))
            if start_date is not None:
                base_stmt = base_stmt.where(
                    schema.SensorHistory.time_bucket >= start_date
                )
            if end_date is not None:
                base_stmt = base_stmt.where(
                    schema.SensorHistory.time_bucket <= end_date
                )

            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count = session.scalar(count_stmt) or 0

            query_stmt = base_stmt.options(
                contains_eager(schema.SensorHistory.sensor).joinedload(
                    schema.Sensor.sensor_type
                )
            )

            if offset is not None:
                query_stmt = query_stmt.offset(offset)
            if n is not None:
                query_stmt = query_stmt.limit(n)

            data = session.scalars(query_stmt).all()
            result = []

            for datum in data:
                temp = datatype.SensorHistory(
                    sensor_id=datum.sensor_id,
                    time_bucket=datum.time_bucket,
                    max=datum.max_val,
                    min=datum.min_val,
                    avg=datum.avg_val,
                    sensor_type=datum.sensor.sensor_type.id,
                    sensor_type_name=datum.sensor.sensor_type.type_name,
                )
                result.append(temp)

            return result, count, None

        except Exception as e:
            session.rollback()
            return [], 0, e

    def add_new_sensor(self, sensors: list[datatype.Sensor]) -> Exception | None:
        """
        `sensor` 테이블에 (1개 이상의) 새 센서를 추가합니다.
        센서 현재 상태를 업데이트하는 것이 아닌 새로운 센서 장치를 추가합니다.

        Args:
            sensors (list[datatype.Sensor]): 새 센서(들). 필수 필드(id, type_id), 선택 필드(value)

        Returns:
            Exception | None: 작업 중 발생한 예외

        """
        session = self.session_local()
        try:
            ids = [i.id for i in sensors]
            stmt = select(schema.Sensor.id).where(schema.Sensor.id.in_(ids))
            existing_ids = session.scalars(stmt).all()

            for sensor_id in ids:
                if sensor_id in existing_ids:
                    return ValueError(f"Sensor already exists: {sensor_id}")

            now = datetime.now()
            new_data = []
            for datum in sensors:
                if datum.last_signal is not None:
                    last_signal = datum.last_signal
                else:
                    last_signal = now

                new_sensor = schema.Sensor(
                    id=datum.id,
                    type_id=datum.type_id,
                    region_id=datum.region_id,
                    name=datum.name,
                    value=datum.value,
                    last_signal=last_signal,
                )

                new_raw = schema.SensorRaw(
                    sensor_id=datum.id, created_at=last_signal, value=datum.value
                )

                new_data.append(new_sensor)
                new_data.append(new_raw)

            session.add_all(new_data)
            session.commit()
        except Exception as e:
            session.rollback()
            return e
        return None

    def update_sensor(self, sensors: list[datatype.Sensor]) -> Exception | None:
        """
        `sensor`와 `sensor_raw` 테이블에 센서 정보를 업데이트합니다.

        Args:
            sensors (list[datatype.Sensor]): 센서(들)의 정보. 필수 필드(id, value)

        Returns:
            Exception | None: 작업 중 발생한 예외

        """
        session = self.session_local()
        try:
            ids = [i.id for i in sensors]
            stmt = select(schema.Sensor.id).where(schema.Sensor.id.in_(ids))
            existing_ids = set(session.scalars(stmt).all())

            for sensor_id in ids:
                if sensor_id not in existing_ids:
                    return ValueError(f"There's no sensor has ID '{sensor_id}'")

            update_data = []
            new_raws = []
            now = datetime.now()

            for datum in sensors:
                last_signal = (
                    datum.last_signal if datum.last_signal is not None else now
                )
                upd = {
                    "id": datum.id,
                    "value": datum.value,
                    "last_signal": last_signal,
                }
                if datum.name is not None:
                    upd["name"] = datum.name
                update_data.append(upd)
                new_raws.append(
                    schema.SensorRaw(
                        sensor_id=datum.id,
                        value=datum.value,
                        created_at=last_signal,
                    )
                )

            session.execute(update(schema.Sensor), update_data)
            session.add_all(new_raws)
            session.commit()
            return None

        except Exception as e:
            session.rollback()
            return e

    def update_robot(self, robots: list[datatype.Robot]) -> Exception | None:
        """
        `robot`테이블을 갱신하고 `robot_history` 테이블에 로봇 상태를 추가합니다.

        Args:
            robots (list[datatype.Robot]): 업데이트할 로봇
        Returns:
            Exception | None: 발생한 에러

        """
        session = self.session_local()

        try:
            ids = [i.id for i in robots]
            stmt = select(schema.Robot).where(schema.Robot.id.in_(ids))
            existing_robots = session.scalars(stmt).all()
            existing_ids = {r.id for r in existing_robots}

            for robot_id in ids:
                if robot_id not in existing_ids:
                    return ValueError(f"There's no robot has ID '{robot_id}'")

            existings = {r.id: r for r in existing_robots}
            update_data = []
            new_histories = []
            now = datetime.now()

            for robot in robots:
                last_signal = (
                    robot.last_signal if robot.last_signal is not None else now
                )
                if existings[robot.id].last_signal < last_signal:
                    update_data.append(
                        {
                            "id": robot.id,
                            "state": robot.state,
                            "last_signal": last_signal,
                        }
                    )

                temp = schema.RobotHistory(
                    robot_id=robot.id, state=robot.state, created_at=last_signal
                )
                new_histories.append(temp)

            new_histories = sorted(new_histories, key=lambda x: x.created_at)

            if update_data:
                session.execute(update(schema.Robot), update_data)
            session.add_all(new_histories)
            session.commit()

            return None
        except Exception as e:
            session.rollback()
            return e

    def get_robot_history(
        self,
        robot_ids: list[int] | None = None,
        regions: list[int] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        n: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[datatype.RobotHistory], int, Exception | None]:
        """
        `robot_history`에 기록된 로봇 상태를 가져옵니다.
        검색 범위 인자를 설정하지 않으면 제한 없이 조회합니다.

        Args:
            robot_ids (list[int], optional): 조회할 로봇의 ID 목록
            regions (list[int], optional): 조회할 지역
            start_date (datetime.datetime, optional): 검색 범위 시작일
            end_date (datetime.datetime, optional): 검색 범위 종료일
            n (int, optional): 검색 개수
            offset (int, optional): 최신 기록으로부터 떨어진 거리

        Returns:
            tuple[result, count, error]:
                - result (list[datatype.RobotHistory])
                - count (int): 전체 데이터 개수
                - error (Exception | None): 발생한 에러

        """

        session = self.session_local()

        try:
            base_stmt = (
                select(schema.RobotHistory)
                .join(schema.Robot)
                .order_by(schema.RobotHistory.id.desc())
            )

            if robot_ids:
                base_stmt = base_stmt.where(schema.RobotHistory.robot_id.in_(robot_ids))
            if regions:
                base_stmt = base_stmt.where(schema.Robot.region_id.in_(regions))
            if start_date is not None:
                base_stmt = base_stmt.where(
                    schema.RobotHistory.created_at >= start_date
                )
            if end_date is not None:
                base_stmt = base_stmt.where(schema.RobotHistory.created_at <= end_date)

            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count = session.scalar(count_stmt) or 0

            query_stmt = base_stmt.options(contains_eager(schema.RobotHistory.robot))

            if offset is not None:
                query_stmt = query_stmt.offset(offset)
            if n is not None:
                query_stmt = query_stmt.limit(n)

            data = session.scalars(query_stmt)

            result = []

            for datum in data:
                temp = datatype.RobotHistory(
                    id=datum.id,
                    created_at=datum.created_at,
                    robot_id=datum.robot_id,
                    state=datum.state,
                )

                result.append(temp)

            return result, count, None
        except Exception as e:
            session.rollback()
            return [], 0, e

    def get_robot_parameter(
        self, robot_id: int
    ) -> tuple[datatype.RobotParameter | None, Exception | None]:
        """
        `robot_parameter` 테이블에서 로봇 파라미터를 조회합니다.

        Args:
            robot_id (int): 조회할 로봇 ID

        Returns:
            tuple[result, error]:
                - result (datatype.RobotParameter | None): 조회 결과. 데이터가 없으면 None
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.RobotParameter).where(
                schema.RobotParameter.robot_id == robot_id
            )
            datum = session.scalars(stmt).first()

            if datum is None:
                return None, None

            result = datatype.RobotParameter(
                robot_id=datum.robot_id,
                controller=datum.controller,
                rpp=datum.rpp,
                safe=datum.safe,
                ack=datum.ack,
            )
            return result, None

        except Exception as e:
            session.rollback()
            return None, e

    def upsert_robot_parameter(
        self, param: datatype.RobotParameter
    ) -> Exception | None:
        """
        `robot_parameter` 테이블에 파라미터를 저장합니다.
        이미 해당 robot_id의 행이 있으면 갱신(UPDATE), 없으면 삽입(INSERT)합니다.

        Args:
            param (datatype.RobotParameter): 저장할 파라미터 객체

        Returns:
            Exception | None: 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.RobotParameter).where(
                schema.RobotParameter.robot_id == param.robot_id
            )
            existing = session.scalars(stmt).first()

            if existing is not None:
                existing.controller = param.controller
                existing.rpp  = param.rpp
                existing.safe = param.safe
                existing.ack  = param.ack
            else:
                new_row = schema.RobotParameter(
                    robot_id=param.robot_id,
                    controller=param.controller,
                    rpp=param.rpp,
                    safe=param.safe,
                    ack=param.ack,
                )
                session.add(new_row)

            session.commit()
            return None

        except Exception as e:
            session.rollback()
            return e


    def get_plant_statistics(
        self,
        type_ids: list[int] | None = None,
        regions: list[int] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        n: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[datatype.PlantStatistics], int, Exception | None]:
        """
        `plant_statistics`에 기록된 로그를 가져옵니다.

        Args:
            type_ids (list[int], optional): 가져올 작물의 유형(들)
            regions (list[int], optional): 가져올 지역(들)
            start_date (datetime, optional): 검색 시작일
            end_date (datetime, optional): 검색 종료일
            n (int, optional): 데이터의 최대 개수 (pagination에 사용)
            offset (int, optional): 최신 데이터와의 오프셋 (pagination에 사용)

        Returns:
            tuple[result, count, error]:
            - result (list[datatype.PlantStatistics])
            - count (int): 전체 데이터 개수
            - error (Exception | None): 발생한 에러
        """

        session = self.session_local()
        try:
            base_stmt = select(schema.PlantStatistics).order_by(
                schema.PlantStatistics.id.desc()
            )

            if type_ids:
                base_stmt = base_stmt.where(
                    schema.PlantStatistics.type_id.in_(type_ids)
                )
            if regions:
                base_stmt = base_stmt.where(
                    schema.PlantStatistics.region_id.in_(regions)
                )
            if start_date is not None:
                base_stmt = base_stmt.where(
                    schema.PlantStatistics.created_at >= start_date
                )
            if end_date is not None:
                base_stmt = base_stmt.where(
                    schema.PlantStatistics.created_at <= end_date
                )

            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count = session.scalar(count_stmt) or 0

            query_stmt = base_stmt
            if offset is not None:
                query_stmt = query_stmt.offset(offset)
            if n is not None:
                query_stmt = query_stmt.limit(n)

            data = session.scalars(query_stmt).all()

            result = []
            for datum in data:
                result.append(
                    datatype.PlantStatistics(
                        id=datum.id,
                        created_at=datum.created_at,
                        type_id=datum.type_id,
                        avg_maturity=datum.avg_maturity,
                        region_id=datum.region_id,
                        disease_ratio=datum.disease_ratio,
                    )
                )

            return result, count, None

        except Exception as e:
            session.rollback()
            return [], 0, e

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
            stmt = (
                select(schema.PlantType)
                .join(schema.PlantType.plants)  # Plant 테이블과 INNER JOIN
                .distinct()
            )

            data = session.scalars(stmt).all()
            result = dict()
            for datum in data:
                result[datum.id] = datum.name

            return result, None
        except Exception as e:
            session.rollback()
            return dict(), e

    def get_all_regions(self) -> tuple[list[datatype.Region], Exception | None]:
        """
        모든 재배지(Region) 정보를 가져옵니다.

        Returns:
            tuple[result, error]:
            - result (list[datatype.Region]): 결과
            - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.Region)
            data = session.scalars(stmt).all()
            result = []
            for datum in data:
                result.append(datatype.Region(id=datum.id, name=datum.name))
            return result, None
        except Exception as e:
            session.rollback()
            return [], e

    def update_plant(self, plants: list[datatype.Plant]) -> Exception | None:
        """
        `plant` 테이블에 작물 정보를 업데이트합니다.

        Args:
            plants (list[datatype.Plant]): 업데이트할 작물

        Returns:
            Exception | None: 발생한 에러

        """
        session = self.session_local()

        try:
            ids = [i.id for i in plants]
            stmt = select(schema.Plant.id).where(schema.Plant.id.in_(ids))
            existing_ids = set(session.scalars(stmt).all())

            for plant_id in ids:
                if plant_id not in existing_ids:
                    return ValueError(f"There's no plant has ID '{plant_id}'")

            update_data = []
            for datum in plants:
                upd = {
                    "id": datum.id,
                    "maturity": datum.maturity,
                    "is_disease": datum.is_disease,
                }
                if datum.name is not None:
                    upd["name"] = datum.name
                update_data.append(upd)

            session.execute(update(schema.Plant), update_data)
            session.commit()
            return None

        except Exception as e:
            session.rollback()
            return e

    def calculate_plant_statistics(
        self,
    ) -> tuple[list[datatype.PlantStatistics], Exception | None]:
        """
        현재 시점을 기준으로 `plant` 테이블의 정보를 작물 종류별로 취합한 스냅샷을 저장합니다.

        Returns:
            tuple[result, error]:
                - result (list[datatype.PlantStatistics]): 생성된 스냅샷
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()

        try:
            stmt = select(
                schema.Plant.type_id,
                schema.Plant.region_id,
                func.avg(schema.Plant.maturity).label("avg_maturity"),
                func.avg(cast(schema.Plant.is_disease, Float)).label("disease_ratio"),
            ).group_by(schema.Plant.type_id, schema.Plant.region_id)

            data = session.execute(stmt).all()

            result = []
            stats = []
            for datum in data:
                result.append(
                    datatype.PlantStatistics(
                        type_id=datum.type_id,
                        avg_maturity=datum.avg_maturity,
                        disease_ratio=datum.disease_ratio,
                        region_id=datum.region_id,
                    )
                )

                stats.append(
                    schema.PlantStatistics(
                        type_id=datum.type_id,
                        avg_maturity=datum.avg_maturity,
                        disease_ratio=datum.disease_ratio,
                        region_id=datum.region_id,
                    )
                )

            session.add_all(stats)
            session.commit()

            return result, None
        except Exception as e:
            session.rollback()
            return [], e

    def update_actuator(self, actuators: list[datatype.Actuator]) -> Exception | None:
        """
        `actuator` 테이블에 액추에이터 상태를 업데이트합니다.

        Args:
            actuators (list[datatype.Actuator]): 업데이트할 액추에이터 목록

        Returns:
            Exception | None: 발생한 에러
        """
        session = self.session_local()

        try:
            ids = [i.id for i in actuators]
            stmt = select(schema.Actuator.id).where(schema.Actuator.id.in_(ids))
            existing_ids = set(session.scalars(stmt).all())

            for actuator_id in ids:
                if actuator_id not in existing_ids:
                    return ValueError(f"There's no actuator has ID '{actuator_id}'")

            update_data = []
            now = datetime.now()

            for actuator in actuators:
                last_signal = (
                    actuator.last_signal if actuator.last_signal is not None else now
                )
                update_data.append(
                    {
                        "id": actuator.id,
                        "state": actuator.state,
                        "last_signal": last_signal,
                    }
                )

            session.execute(update(schema.Actuator), update_data)
            session.commit()

            return None
        except Exception as e:
            session.rollback()
            return e

    def get_all_plant_types(self) -> tuple[list[dict], Exception | None]:
        """모든 작물 유형 정보를 가져옵니다.

        Returns:
            tuple[result, error]:
                - result (list[dict]): 각 딕셔너리는 {"id": int, "name": str} 형태
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.PlantType)
            data = session.scalars(stmt).all()
            result = [{"id": d.id, "name": d.name} for d in data]
            return result, None
        except Exception as e:
            session.rollback()
            return [], e

    def get_all_sensor_types(self) -> tuple[list[dict], Exception | None]:
        """모든 센서 유형 정보를 가져옵니다.

        Returns:
            tuple[result, error]:
                - result (list[dict]): 각 딕셔너리는 {"id": int, "name": str} 형태
                - error (Exception | None): 발생한 에러
        """
        session = self.session_local()
        try:
            stmt = select(schema.SensorType)
            data = session.scalars(stmt).all()
            result = [{"id": d.id, "name": d.type_name} for d in data]
            return result, None
        except Exception as e:
            session.rollback()
            return [], e

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
    url = DBManager.make_url(database="farm", host="192.168.0.28")
    db = DBManager(url)
    with db.session_scope() as session:
        print(db.get_active_plant_type())
