from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Sensor:
    sensor_id: int
    value: float | None = field(default=None)
    # sensor_type 테이블에 정의된 TINYINT
    type_id: int = field(default=0)
    # sensor_type 테이블의 type_name. 출력 전용
    type_name: str = field(default="")


@dataclass
class SensorHistory:
    # 로그 자체의 ID
    id: int
    created_at: datetime
    # 로그를 생성한 센서의 ID
    sensor_id: int
    value: float | None


@dataclass
class Plant:
    id: int
    maturity: float
    is_disease: bool
    # 신규 입력시 필요
    type_id: int = field(default=None)
    # 신규 입력시 필요
    name: str = field(default=None)

@dataclass
class PlantStatistics:
    type_id: int
    avg_maturity: float
    disease_ratio: float
    created_at: datetime = field(default=None)
    id: int = field(default=None)

@dataclass
class RobotState:
    id: int
    created_at: datetime
    state: str
