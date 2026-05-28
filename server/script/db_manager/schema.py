from datetime import datetime
from typing import List

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "region"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column("name", String(30))

    plants: Mapped[List["Plant"]] = relationship(back_populates="region")
    statistics: Mapped[List["PlantStatistics"]] = relationship(back_populates="region")
    sensors: Mapped[List["Sensor"]] = relationship(back_populates="region")
    actuators: Mapped[List["Actuator"]] = relationship(back_populates="region")
    robots: Mapped[List["Robot"]] = relationship(back_populates="region")


class PlantType(Base):
    __tablename__ = "plant_type"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column("name", String(30))

    plants: Mapped[List["Plant"]] = relationship(back_populates="plant_type")
    histories: Mapped[List["PlantStatistics"]] = relationship(
        back_populates="plant_type"
    )


class Plant(Base):
    __tablename__ = "plant"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column("name", String(30))
    type_id: Mapped[int] = mapped_column("type_id", ForeignKey("plant_type.id"))
    region_id: Mapped[int] = mapped_column("region_id", ForeignKey("region.id"))
    maturity: Mapped[float] = mapped_column("maturity")
    is_disease: Mapped[bool] = mapped_column("is_disease")

    plant_type: Mapped["PlantType"] = relationship(back_populates="plants")
    region: Mapped["Region"] = relationship(back_populates="plants")


class PlantStatistics(Base):
    __tablename__ = "plant_statistics"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime, server_default=func.now()
    )
    type_id: Mapped[int] = mapped_column(ForeignKey("plant_type.id"))
    region_id: Mapped[int] = mapped_column("region_id", ForeignKey("region.id"))
    avg_maturity: Mapped[float] = mapped_column("avg_maturity")
    disease_ratio: Mapped[float] = mapped_column("disease_ratio")

    plant_type: Mapped["PlantType"] = relationship(back_populates="histories")
    region: Mapped["Region"] = relationship(back_populates="statistics")


class SensorType(Base):
    __tablename__ = "sensor_type"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    type_name: Mapped[str] = mapped_column("type_name", String(20))

    sensors: Mapped[List["Sensor"]] = relationship(
        back_populates="sensor_type", cascade="all, delete-orphan"
    )


class Sensor(Base):
    __tablename__ = "sensor"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    type_id: Mapped[int] = mapped_column("type_id", ForeignKey("sensor_type.id"))
    region_id: Mapped[int] = mapped_column("region_id", ForeignKey("region.id"))
    value: Mapped[float] = mapped_column("value")

    raw_data: Mapped[List["SensorRaw"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )
    bucket_data: Mapped[List["SensorHistory"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )
    sensor_type: Mapped[SensorType] = relationship(back_populates="sensors")
    region: Mapped["Region"] = relationship(back_populates="sensors")


class SensorRaw(Base):
    __tablename__ = "sensor_raw"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime, server_default=func.now()
    )
    sensor_id: Mapped[int] = mapped_column("sensor_id", ForeignKey("sensor.id"))
    value: Mapped[float] = mapped_column("value")

    sensor: Mapped[Sensor] = relationship(back_populates="raw_data")


class SensorHistory(Base):
    __tablename__ = "sensor_history"
    time_bucket: Mapped[datetime] = mapped_column("time_bucket", primary_key=True)
    sensor_id: Mapped[int] = mapped_column(
        "sensor_id", ForeignKey("sensor.id"), primary_key=True
    )
    max_val: Mapped[float] = mapped_column("max_val")
    min_val: Mapped[float] = mapped_column("min_val")
    avg_val: Mapped[float] = mapped_column("avg_val")

    sensor: Mapped[Sensor] = relationship(back_populates="bucket_data")


class ActuatorType(Base):
    __tablename__ = "actuator_type"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    type_name: Mapped[str] = mapped_column("type_name", String(20))

    actuators: Mapped[List["Actuator"]] = relationship(
        back_populates="actuator_type", cascade="all, delete-orphan"
    )


class Actuator(Base):
    __tablename__ = "actuator"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    type_id: Mapped[int] = mapped_column("type_id", ForeignKey("actuator_type.id"))
    region_id: Mapped[int] = mapped_column("region_id", ForeignKey("region.id"))
    state: Mapped[str] = mapped_column("state", String(30))

    actuator_type: Mapped[ActuatorType] = relationship(back_populates="actuators")
    region: Mapped["Region"] = relationship(back_populates="sensors")


class Robot(Base):
    __tablename__ = "robot"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=False)
    region_id: Mapped[int] = mapped_column("region_id", ForeignKey("region.id"))
    name: Mapped[str] = mapped_column("name", String(30))

    region: Mapped["Region"] = relationship(back_populates="robots")
    histories: Mapped[List["RobotHistory"]] = relationship(back_populates="robot")


class RobotHistory(Base):
    __tablename__ = "robot_history"
    id: Mapped[int] = mapped_column("id", primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime, server_default=func.now()
    )
    robot_id: Mapped[int] = mapped_column("robot_id", ForeignKey("robot.id"))
    state: Mapped[str] = mapped_column("state", String(30))

    robot: Mapped["Robot"] = relationship(back_populates="histories")
