from dataclasses import dataclass

@dataclass
class SensorData:
    sensor_id: int
    value: float
    type_id: int # sensor_type 테이블에 정의된 TINYINT

@dataclass
class PlantData:
    plant_id: int
    maturity: float
    is_disease: bool

