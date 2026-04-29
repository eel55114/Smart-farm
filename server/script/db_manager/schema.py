from typing import List
from sqlalchemy import (
    create_engine, ForeignKey,func,
    String, DateTime, Integer, Text,
)

from sqlalchemy.dialects import mysql

from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column,
    relationship
)
from datetime import datetime

class Base(DeclarativeBase):
    pass

class PlantStat(Base):
    __tablename__ = "plant_stat"
    plant_id: Mapped[int] = mapped_column("plant_id", primary_key=True)
    maturity: Mapped[float] = mapped_column("maturity")
    is_disease: Mapped[bool] = mapped_column("is_disease")

    histories: Mapped[List["PlantHistory"]] = relationship(
        back_populates="plant", cascade="all, delete-orphan"
    )

class PlantHistory(Base):
    __tablename__ = "plant_history"
    id: Mapped[int] = mapped_column("id", primary_key=True, auto_increment=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime,
        server_default=func.now()
    )
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant_stat.plant_id"))
    maturity_rate: Mapped[float] = mapped_column("maturity_rate")
    disease_rate: Mapped[float] = mapped_column("disease_rate")

    plant: Mapped["PlantStat"] = relationship(back_populates="histories")


class SensorType(Base):
    __tablename__ = "sensor_type"
    id: Mapped[int] = mapped_column("id", mysql.TINYINT, primary_key=True)
    type_name: Mapped[str] = mapped_column("type_name", String(20))

    sensors: Mapped[List["Sensor"]] = relationship(
        back_populates="sensor_type", cascade="all, delete-orphan"
    )

class Sensor(Base):
    __tablename__ = "sensor"
    id: Mapped[int] = mapped_column("id", primary_key=True)
    type_id: Mapped[int] = mapped_column("type_id", mysql.TINYINT, ForeignKey("sensor_type.id"))
    value: Mapped[float | None] = mapped_column("value")
    sensor_type: Mapped[SensorType] = relationship(
        back_populates="sensors"
    )
    histories: Mapped[List["SensorHistory"]] = relationship(
        back_populates="referred_sensor", cascade="all, delete-orphan"
    )

class SensorHistory(Base):
    __tablename__ = "sensor_history"
    id: Mapped[int] = mapped_column("id", primary_key=True, auto_increment=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime,
        server_default=func.now()
    )
    sensor_id: Mapped[int] = mapped_column("sensor_id", ForeignKey("sensor.id"))
    value: Mapped[float | None] = mapped_column("value")

    referred_sensor: Mapped[Sensor] = relationship(
        back_populates="histories"
    )

class RobotHistory(Base):
    __tablename__ = "robot_history"
    id: Mapped[int] = mapped_column("id", primary_key=True, auto_increment=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime,
        server_default=func.now()
    )
    stat: Mapped[str] = mapped_column("stat", String(30))


