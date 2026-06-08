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
    return render_template("robot_settings.html")


@robot_bp.route("/robot/manual_control")
def robot_manual_control():
    connection_error = False
    db_error = False
    robot_error = False
    error_target = ""

    page = request.args.get("page", 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    robot_histories, count, err = db.get_robot_history(n=per_page, offset=offset)
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
        "robot.html",
        connection_error=connection_error,
        error_target=error_target,
        table_name=table_name,
        history_columns=history_columns,
        history_data=history_data,
        page=page,
        has_next=has_next,
    )


@robot_bp.route("/api/change_robot_state")
def change_robot_state():
    pass
    # todo
    return "", 200


@robot_bp.route("/api/control_robot")
def control_robot():
    direction = request.args.get("direction", "stop", type=str)
    print(direction)

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
def current_robot_state():
    # battery_percent = BATTERY_MONITOR.get_battery_state()["percent"]
    # history, err = db.get_robot_history(n=1, offset=0)
    # state = history[0].state

    battery_percent = 100
    state = ""
    pass  # todo

    return render_template(
        "_robot_state.html",
        current_battery=battery_percent,
        current_state=state,
    )
