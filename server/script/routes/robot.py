import json
import pathlib

from db_instance import db
from flask import Blueprint, redirect, render_template, request

robot_bp = Blueprint("robot", __name__)


@robot_bp.route("/robot")
def robot_redirect():
    return redirect("/robot/schedule")


@robot_bp.route("/robot/schedule")
def robot_schedule():
    return render_template("robot_schedule.html")


@robot_bp.route("/robot/settings")
def robot_settings():
    # 플레이스홀더 고정 설정 데이터 반환 (신규 규격 반영)
    default_settings = {
        "algorithm": "RPP",
        "rpp": {"speed": 0.12, "rotation_speed": 0.50, "obstacle_dist": 0.80},
        "safe": {"speed": 0.10, "rotation_speed": 0.30, "obstacle_dist": 0.60},
        "ack": {"speed": 0.16, "rotation_speed": 0.80, "obstacle_dist": 0.50},
    }
    return render_template("robot_settings.html", settings=default_settings)


@robot_bp.route("/api/robot_settings", methods=["POST"])
def save_robot_settings():
    data = request.get_json() or {}
    robot_id = request.args.get("robot", type=int)
    print(
        f"[Robot Settings Save] Robot ID={robot_id} - Received config parameters: {data}"
    )
    return {"status": "success", "message": "Settings saved successfully"}, 200


@robot_bp.route("/robot/manual_control")
def robot_manual_control() -> str:
    connection_error = False
    db_error = False
    robot_error = False
    error_target = ""

    page = request.args.get("page", 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    region_id = request.args.get("region", type=int)
    regions_filter = [region_id] if region_id else None

    robot_id = request.args.get("robot", type=int)

    robots, _ = db.get_current_robot()
    valid_robots = robots
    if region_id is not None:
        valid_robots = [r for r in robots if r.region_id == region_id]

    if robot_id is not None:
        matching_robot = next((r for r in valid_robots if r.id == robot_id), None)
        if not matching_robot:
            robot_id = None

    if robot_id is None and valid_robots:
        default_robot = min(valid_robots, key=lambda r: r.id)
        robot_id = default_robot.id

    is_manual = False
    # todo: 로봇 3모드로 개편

    robot_histories, count, err = db.get_robot_history(
        n=per_page,
        offset=offset,
        robot_ids=[robot_id] if robot_id else None,
        regions=regions_filter,
    )
    if err is not None:
        db_error = True
        robot_histories = []
        has_next = False
    else:
        has_next = (offset + per_page) < count

    table_name = "로봇 상태 이력"
    history_columns = ["이력 ID", "일시", "상태"]
    history_data = []

    for h in robot_histories:
        history_data.append(
            [
                h.id,
                h.created_at,
                h.state,
            ]
        )

    error_target += "로봇" if robot_error else ""
    error_target += "및" if robot_error and db_error else ""
    error_target += "데이터베이스" if db_error else ""

    return render_template(
        "robot_manual_control.html",
        connection_error=connection_error,
        error_target=error_target,
        table_name=table_name,
        history_columns=history_columns,
        history_data=history_data,
        page=page,
        has_next=has_next,
        is_manual=is_manual,
    )


@robot_bp.route("/api/change_robot_state")
def change_robot_state() -> tuple[str, int]:
    is_manual_val = request.args.get("is_manual", type=int)
    robot_id = request.args.get("robot", type=int)

    if robot_id is not None:
        state_str = "수동 제어" if is_manual_val == 1 else "대기 중"
        # 로봇 상태 DB 업데이트
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            robot = robots_found[0]
            robot.state = state_str
            db.update_robot([robot])
            print(f"[Change Robot State] Robot ID={robot_id} updated to: {state_str}")

    return "", 200


@robot_bp.route("/api/control_robot")
def control_robot() -> tuple[str, int]:
    direction = request.args.get("direction", "stop", type=str)
    robot_id = request.args.get("robot", type=int)
    print(f"[Control Robot] Robot ID={robot_id}, Direction={direction}")

    data = ""
    if direction == "Home":
        data = "h"
    else:
        if direction == "Forward":
            data = "f"
        elif direction == "Right":
            data = "r"
        elif direction == "Left":
            data = "l"
        elif direction == "Backward":
            data = "b"
        elif direction == "Stop":
            data = "s"

    pass
    # todo

    return "", 200


@robot_bp.route("/api/current_robot_state")
def current_robot_state() -> str:
    # battery_percent = BATTERY_MONITOR.get_battery_state()["percent"]
    battery_percent = 100
    state = "-"

    robot_id = request.args.get("robot", type=int)
    if robot_id is not None:
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            state = robots_found[0].state

    return render_template(
        "_robot_state.html",
        current_battery=battery_percent,
        current_state=state,
    )


@robot_bp.route("/api/robot_current_map")
def current_robot_map():
    test_mapdata = json.loads(
        (pathlib.Path(__file__).parent / "___test_mapdata.json").read_text()
    )

    return {**test_mapdata}


@robot_bp.route("/api/robot_moveto", methods=["POST"])
def robot_moveto():
    data = request.get_json() or {}
    robot_id = data.get("robot") or request.args.get("robot", type=int)
    x = data.get("x")
    y = data.get("y")
    print(
        f"[Robot MoveTo] Robot ID={robot_id} - Requested movement to physical coordinates: x={x}, y={y}"
    )
    return {"status": "success", "message": f"Moving to ({x}, {y})"}, 200
