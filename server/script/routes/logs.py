from datetime import datetime
from db_instance import db
from flask import Blueprint, render_template, request

logs_bp = Blueprint("logs", __name__)

# --- 공통 헬퍼 함수 ---

def parse_page_params(per_page=15):
    """요청으로부터 페이지네이션 변수를 파싱합니다."""
    page = request.args.get("page", 1, type=int)
    offset = (page - 1) * per_page
    return page, per_page, offset

def parse_date_range():
    """요청으로부터 시작일과 종료일 문자열 및 datetime 객체를 파싱합니다."""
    start_date_str = request.args.get("start_date", "").strip()
    end_date_str = request.args.get("end_date", "").strip()
    
    start_date = None
    end_date = None
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
            
    return start_date_str, end_date_str, start_date, end_date

def render_log_page(
    template_name,
    table_name,
    endpoint,
    history_columns,
    history_data,
    page,
    has_next,
    count,
    per_page,
    start_date_str,
    end_date_str,
    selected_regions,
    selected_types=None,
    selected_sensors=None,
    selected_robots=None,
    **extra_context
):
    """htmx 요청 여부에 따라 부분 템플릿 또는 전체 템플릿을 분기 렌더링합니다."""
    is_hx = request.headers.get("HX-Request") == "true"
    
    # 공통 컨텍스트 구성
    context = {
        "table_name": table_name,
        "history_columns": history_columns,
        "history_data": history_data,
        "page": page,
        "has_next": has_next,
        "endpoint": endpoint,
        "count": count,
        "per_page": per_page,
        "selected_regions": selected_regions,
        "selected_types": selected_types,
        "selected_sensors": selected_sensors,
        "selected_robots": selected_robots,
        "start_date": start_date_str,
        "end_date": end_date_str
    }
    
    if is_hx:
        return render_template("_logs_viewer_partial.html", **context)
        
    # 전체 페이지 렌더링 시에는 extra_context를 병합하여 전송
    context.update(extra_context)
    return render_template(template_name, **context)


# --- 라우트 핸들러 ---

@logs_bp.route("/logs/plants")
def logs_plants():
    db_error = False
    page, per_page, offset = parse_page_params()

    # 1. 마스터 테이블 개별 조회 (JOIN 방지 규정 준수)
    all_regions, reg_err = db.get_all_regions()
    all_plant_types, pt_err = db.get_all_plant_types()
    if reg_err or pt_err:
        db_error = True

    # 2. 필터 파라미터 및 일시 파싱
    selected_regions = request.args.getlist("regions", type=int)
    selected_types = request.args.getlist("types", type=int)
    start_date_str, end_date_str, start_date, end_date = parse_date_range()

    # 3. 로그 테이블 쿼리 (마스터 테이블 조인하지 않고 그대로 가져옴)
    history_records, count, err = db.get_plant_statistics(
        type_ids=selected_types or None,
        regions=selected_regions or None,
        start_date=start_date,
        end_date=end_date,
        n=per_page,
        offset=offset
    )
    if err is not None:
        db_error = True
        history_records = []
        count = 0

    has_next = (offset + per_page) < count

    # 4. 메모리 상에서 ID와 이름을 매핑하여 표시용 데이터 빌드 (JOIN 방지 규정 준수)
    regions_map = {r.id: r.name for r in all_regions}
    types_map = {t["id"]: t["name"] for t in all_plant_types}

    history_data = []
    for h in history_records:
        history_data.append([
            h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else "-",
            regions_map.get(h.region_id, f"ID {h.region_id}"),
            types_map.get(h.type_id, f"ID {h.type_id}"),
            f"{round(h.avg_maturity * 100, 1)}%" if h.avg_maturity is not None else "-",
            f"{round(h.disease_ratio * 100, 1)}%" if h.disease_ratio is not None else "-"
        ])

    history_columns = ["일시", "지역", "작물 유형", "평균 성숙도", "병해 발생 비율"]

    return render_log_page(
        template_name="logs_plants.html",
        table_name="작물 로그 이력",
        endpoint="logs.logs_plants",
        history_columns=history_columns,
        history_data=history_data,
        page=page,
        has_next=has_next,
        count=count,
        per_page=per_page,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        selected_regions=selected_regions,
        selected_types=selected_types,
        db_error=db_error,
        all_regions=all_regions,
        all_plant_types=all_plant_types
    )

@logs_bp.route("/logs/sensors")
def logs_sensors():
    db_error = False
    page, per_page, offset = parse_page_params()

    # 1. 마스터 테이블 개별 조회 (JOIN 방지 규정 준수)
    all_regions, reg_err = db.get_all_regions()
    all_sensor_types, st_err = db.get_all_sensor_types()
    all_sensors, s_err = db.get_current_sensor()
    if reg_err or st_err or s_err:
        db_error = True

    # 2. 필터 파라미터 및 일시 파싱
    selected_regions = request.args.getlist("regions", type=int)
    selected_types = request.args.getlist("types", type=int)
    selected_sensors = request.args.getlist("sensors", type=int)
    start_date_str, end_date_str, start_date, end_date = parse_date_range()

    # 3. 로그 테이블 쿼리
    history_records, count, err = db.get_sensor_history(
        sensor_ids=selected_sensors or None,
        regions=selected_regions or None,
        types=selected_types or None,
        start_date=start_date,
        end_date=end_date,
        n=per_page,
        offset=offset
    )
    if err is not None:
        db_error = True
        history_records = []
        count = 0

    has_next = (offset + per_page) < count

    # 4. 메모리 상에서 ID와 이름을 매핑하여 표시용 데이터 빌드 (JOIN 방지 규정 준수)
    regions_map = {r.id: r.name for r in all_regions}
    sensor_types_map = {st["id"]: st["name"] for st in all_sensor_types}
    sensors_map = {s.id: s for s in all_sensors}

    history_data = []
    for h in history_records:
        sensor = sensors_map.get(h.sensor_id)
        if sensor:
            region_name = regions_map.get(sensor.region_id, f"ID {sensor.region_id}")
            type_name = sensor_types_map.get(sensor.type_id, f"ID {sensor.type_id}")
            sensor_name = f"[{sensor.id}] {sensor.name}" if (sensor.name and sensor.name.strip()) else f"[{sensor.id}] {type_name}"
        else:
            region_name = "-"
            type_name = "-"
            sensor_name = f"ID {h.sensor_id}"

        # 타입별 포맷 지정
        type_id = sensor.type_id if sensor else None
        if type_id in [1, 2, 5]: # 습도, 조도, 토양습도
            fmt = lambda v: f"{round(v * 100, 1)}%"
        elif type_id == 3: # 온도
            fmt = lambda v: f"{round(v, 1)}°C"
        elif type_id == 4: # 화염
            fmt = lambda v: "화재" if v > 0.5 else "없음"
        else:
            fmt = lambda v: str(round(v, 2))

        history_data.append([
            h.time_bucket.strftime("%Y-%m-%d %H:%M:%S") if h.time_bucket else "-",
            region_name,
            type_name,
            sensor_name,
            fmt(h.max),
            fmt(h.avg),
            fmt(h.min)
        ])

    history_columns = ["기준 시간", "지역", "센서 유형", "센서", "최댓값", "평균값", "최솟값"]

    # 템플릿에 전달할 센서 리스트 가공 (ID와 이름 결합 표시용)
    display_sensors = []
    for s in all_sensors:
        type_name = sensor_types_map.get(s.type_id, "알 수 없는 유형")
        display_name = f"[{s.id}] {s.name}" if (s.name and s.name.strip()) else f"[{s.id}] {type_name}"
        display_sensors.append({
            "id": s.id,
            "name": display_name,
            "region_id": s.region_id,
            "type_id": s.type_id
        })

    return render_log_page(
        template_name="logs_sensors.html",
        table_name="센서 로그 이력",
        endpoint="logs.logs_sensors",
        history_columns=history_columns,
        history_data=history_data,
        page=page,
        has_next=has_next,
        count=count,
        per_page=per_page,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        selected_regions=selected_regions,
        selected_types=selected_types,
        selected_sensors=selected_sensors,
        db_error=db_error,
        all_regions=all_regions,
        all_sensor_types=all_sensor_types,
        display_sensors=display_sensors
    )

@logs_bp.route("/logs/robots")
def logs_robots():
    db_error = False
    page, per_page, offset = parse_page_params()

    # 1. 마스터 테이블 개별 조회 (JOIN 방지 규정 준수)
    all_regions, reg_err = db.get_all_regions()
    all_robots, rob_err = db.get_current_robot()
    if reg_err or rob_err:
        db_error = True

    # 2. 필터 파라미터 및 일시 파싱
    selected_regions = request.args.getlist("regions", type=int)
    selected_robots = request.args.getlist("robots", type=int)
    start_date_str, end_date_str, start_date, end_date = parse_date_range()

    # 3. 로그 테이블 쿼리
    history_records, count, err = db.get_robot_history(
        robot_ids=selected_robots or None,
        regions=selected_regions or None,
        start_date=start_date,
        end_date=end_date,
        n=per_page,
        offset=offset
    )
    if err is not None:
        db_error = True
        history_records = []
        count = 0

    has_next = (offset + per_page) < count

    # 4. 메모리 상에서 ID와 이름을 매핑하여 표시용 데이터 빌드 (JOIN 방지 규정 준수)
    regions_map = {r.id: r.name for r in all_regions}
    robots_map = {r.id: r for r in all_robots}

    history_data = []
    for h in history_records:
        robot = robots_map.get(h.robot_id)
        if robot:
            region_name = regions_map.get(robot.region_id, f"ID {robot.region_id}")
            robot_name = f"[{robot.id}] {robot.name}"
        else:
            region_name = "-"
            robot_name = f"ID {h.robot_id}"

        history_data.append([
            h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else "-",
            region_name,
            robot_name,
            h.state or "-"
        ])

    history_columns = ["일시", "지역", "로봇", "상태"]

    # 템플릿에 전달할 로봇 리스트 가공 (ID와 이름 결합 표시용)
    display_robots = []
    for r in all_robots:
        display_robots.append({
            "id": r.id,
            "name": f"[{r.id}] {r.name}",
            "region_id": r.region_id
        })

    return render_log_page(
        template_name="logs_robots.html",
        table_name="로봇 로그 이력",
        endpoint="logs.logs_robots",
        history_columns=history_columns,
        history_data=history_data,
        page=page,
        has_next=has_next,
        count=count,
        per_page=per_page,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        selected_regions=selected_regions,
        selected_robots=selected_robots,
        db_error=db_error,
        all_regions=all_regions,
        display_robots=display_robots
    )
