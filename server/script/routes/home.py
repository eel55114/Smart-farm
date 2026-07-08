from collections import defaultdict
from datetime import datetime, timedelta

from db_instance import db
from flask import Blueprint, render_template

home_bp = Blueprint("home", __name__)

# 홈 대시보드에서 표시할 센서 type_id (온도=2, 습도=3, 화재=4)
HOME_SENSOR_TYPES = {2, 3, 4}

# 활성 판단 기준 — 센서: 1분 이내, 로봇: 30분 이내
SENSOR_ACTIVE_THRESHOLD = timedelta(minutes=1)
ROBOT_ACTIVE_THRESHOLD  = timedelta(minutes=30)


@home_bp.route("/")
def index():
    now = datetime.now()
    db_error = False

    # ── KPI: 센서 ──────────────────────────────────────────────────
    all_sensors, err = db.get_current_sensor()
    if err:
        db_error = True
        all_sensors = []
    sensor_total = len(all_sensors)
    sensor_active = sum(
        1 for s in all_sensors
        if s.last_signal and (now - s.last_signal) <= SENSOR_ACTIVE_THRESHOLD
    )

    # ── KPI: 작물 ──────────────────────────────────────────────────
    all_plants, err2 = db.get_current_plant()
    if err2:
        db_error = True
        all_plants = []
    plant_total = len(all_plants)
    plant_disease = sum(1 for p in all_plants if p.is_disease)

    # ── KPI: 로봇 ──────────────────────────────────────────────────
    all_robots, err3 = db.get_current_robot()
    if err3:
        db_error = True
        all_robots = []
    robot_total = len(all_robots)
    robot_active = sum(
        1 for r in all_robots
        if r.last_signal and (now - r.last_signal) <= ROBOT_ACTIVE_THRESHOLD
    )

    # ── 센서 현황: 온도·습도·화재만, 지역별 그룹 ───────────────────
    home_sensors_by_region = defaultdict(list)
    for s in all_sensors:
        if s.type_id not in HOME_SENSOR_TYPES:
            continue
        is_active = s.last_signal and (now - s.last_signal) <= SENSOR_ACTIVE_THRESHOLD

        if s.type_id == 3:      # 습도
            value_str = f"{min(round(s.value * 100, 1), 100)}%"
        elif s.type_id == 2:    # 온도
            value_str = f"{s.value}°C"
        elif s.type_id == 4:    # 화재
            value_str = "화재" if s.value > 0.5 else "없음"
        else:
            value_str = str(s.value)

        is_danger = (s.type_id == 4 and s.value > 0.5)
        display_name = s.name if (s.name and s.name.strip()) else s.type_name

        home_sensors_by_region[s.region_name].append({
            "id": s.id,
            "type_id": s.type_id,
            "type_name": s.type_name,
            "display_name": display_name,
            "value": value_str,
            "is_danger": is_danger,
            "is_active": is_active,
        })

    # ── 로봇 현황: 지역별, 로봇별 최근 로그 1건 ────────────────────
    # robot_id → region_name 매핑
    robot_region_map = {r.id: r for r in all_robots}

    robots_by_region = defaultdict(list)
    for robot in all_robots:
        is_active = robot.last_signal and (now - robot.last_signal) <= ROBOT_ACTIVE_THRESHOLD

        # 해당 로봇의 최근 히스토리 1건
        history, _, _ = db.get_robot_history(robot_ids=[robot.id], n=1)
        last_log = history[0].state if history else None

        robots_by_region[robot.region_id].append({
            "id": robot.id,
            "name": robot.name,
            "region_id": robot.region_id,
            "is_active": is_active,
            "last_log": last_log,
        })

    # region_id → region_name 변환
    all_regions, _ = db.get_all_regions()
    region_name_map = {r.id: r.name for r in all_regions}
    robots_by_region_named = {
        region_name_map.get(rid, f"지역 {rid}"): robots
        for rid, robots in robots_by_region.items()
    }

    return render_template(
        "index.html",
        db_error=db_error,
        # KPI
        sensor_active=sensor_active,
        sensor_total=sensor_total,
        plant_disease=plant_disease,
        plant_total=plant_total,
        robot_active=robot_active,
        robot_total=robot_total,
        # 중단
        home_sensors_by_region=dict(home_sensors_by_region),
        robots_by_region=robots_by_region_named,
    )
