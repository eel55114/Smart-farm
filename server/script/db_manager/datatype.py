from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Region:
    id: int
    name: str


@dataclass
class Sensor:
    # 항상 필요
    id: int
    value: float = field(default=None)

    last_signal: datetime = field(default=None)

    # 신규 입력시 필요
    type_id: int = field(default=None)
    region_id: int = field(default=None)

    # 읽기 전용
    type_name: str = field(default="")
    region_name: str = field(default="")


@dataclass
class SensorHistory:
    # 로그를 생성한 센서의 ID
    sensor_id: int
    time_bucket: datetime
    max: float
    min: float
    avg: float
    sensor_type: int
    sensor_type_name: str


@dataclass
class Plant:
    # 항상 필요
    id: int
    maturity: float
    is_disease: bool

    # 신규 입력에만 필요
    type_id: int = field(default=None)
    region_id: int = field(default=None)
    name: str = field(default=None)

    # 읽기 전용
    type_name: str = field(default="")
    region_name: str = field(default="")


@dataclass
class PlantStatistics:
    type_id: int
    avg_maturity: float
    disease_ratio: float
    region_id: int
    created_at: datetime = field(default=None)
    id: int = field(default=None)


@dataclass
class Actuator:
    id: int
    state: str

    # 신규 입력시에만 필요
    type_id: int = field(default=None)
    region_id: int = field(default=None)

    # 읽기 전용
    type_name: str = field(default=None)
    region_name: str = field(default=None)
    last_signal: datetime = field(default=None)


@dataclass
class Robot:
    id: int
    state: str
    region_id: int = field(default=None)
    name: str = field(default=None)
    last_signal: datetime = field(default=None)


@dataclass
class RobotHistory:
    id: int
    created_at: datetime
    robot_id: int
    state: str
    robot_name: str = field(default=None)
