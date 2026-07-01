import json
import math
import pathlib

from db_instance import db
from flask import Blueprint, redirect, render_template, request, current_app

robot_bp = Blueprint("robot", __name__)


@robot_bp.route("/robot")
def robot_redirect():
    return redirect("/robot/schedule")


@robot_bp.route("/robot/schedule")
def robot_schedule():
    return render_template("robot_schedule.html")


@robot_bp.route("/robot/settings")
def robot_settings():
    robot_id = request.args.get("robot", type=int)

    # DB에서 파라미터 조회 (없으면 기본값 사용)
    settings = None
    if robot_id is not None:
        param, _ = db.get_robot_parameter(robot_id)
        if param is not None:
            settings = {
                "algorithm": param.controller,
                "rpp":  {
                    "speed":          param.rpp.get("speed",     0.12),
                    "goal_tolerance": param.rpp.get("tolerance", 0.10),
                    "obstacle_dist":  param.rpp.get("inflation", 0.80),
                },
                "safe": {
                    "speed":          param.safe.get("speed",     0.10),
                    "goal_tolerance": param.safe.get("tolerance", 0.10),
                    "obstacle_dist":  param.safe.get("inflation", 0.60),
                },
                "ack":  {
                    "speed":          param.ack.get("speed",     0.16),
                    "goal_tolerance": param.ack.get("tolerance", 0.10),
                    "obstacle_dist":  param.ack.get("inflation", 0.50),
                },
            }

    if settings is None:
        # DB 데이터 없으면 기본값
        settings = {
            "algorithm": "RPP",
            "rpp":  {"speed": 0.12, "goal_tolerance": 0.10, "obstacle_dist": 0.80},
            "safe": {"speed": 0.10, "goal_tolerance": 0.10, "obstacle_dist": 0.60},
            "ack":  {"speed": 0.16, "goal_tolerance": 0.10, "obstacle_dist": 0.50},
        }

    return render_template("robot_settings.html", settings=settings)


@robot_bp.route("/api/robot_settings", methods=["POST"])
def save_robot_settings():
    data = request.get_json() or {}
    robot_id = request.args.get("robot", type=int)
    print(
        f"[Robot Settings Save] Robot ID={robot_id} - Received config parameters: {data}"
    )

    if robot_id is not None:
        # region_id 조회
        region_id = None
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            region_id = robots_found[0].region_id
        if region_id is None:
            region_id = 1

        connector = current_app.config.get("MQTT_CONNECTOR")
        if connector:
            # 브라우저 payload 키 → ROS /publish_param 규격으로 변환
            # goal_tolerance → tolerance, obstacle_dist → inflation
            # mode 키(rpp/safe/ack) → 대문자 콘트롤러명(RPP/SAFE/ACK)
            mode_map = {"rpp": "RPP", "safe": "SAFE", "ack": "ACK"}
            controllers = {}
            for mode_lower, mode_upper in mode_map.items():
                cfg = data.get(mode_lower, {})
                controllers[mode_upper] = {
                    "speed":     cfg.get("speed", 0.0),
                    "tolerance": cfg.get("goal_tolerance", 0.0),
                    "inflation": cfg.get("obstacle_dist", 0.0),
                }

            ros_payload = {
                "controllers":         controllers,
                "current_controller":  data.get("algorithm", "RPP"),
            }

            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/publish_param"
            connector.publish(topic, ros_payload)

        # DB에 파라미터 저장 (upsert)
        from db_manager import datatype as dt
        param = dt.RobotParameter(
            robot_id=robot_id,
            controller=data.get("algorithm", "RPP"),
            rpp={
                "speed":     data.get("rpp", {}).get("speed", 0.12),
                "tolerance": data.get("rpp", {}).get("goal_tolerance", 0.10),
                "inflation": data.get("rpp", {}).get("obstacle_dist", 0.80),
            },
            safe={
                "speed":     data.get("safe", {}).get("speed", 0.10),
                "tolerance": data.get("safe", {}).get("goal_tolerance", 0.10),
                "inflation": data.get("safe", {}).get("obstacle_dist", 0.60),
            },
            ack={
                "speed":     data.get("ack", {}).get("speed", 0.16),
                "tolerance": data.get("ack", {}).get("goal_tolerance", 0.10),
                "inflation": data.get("ack", {}).get("obstacle_dist", 0.50),
            },
        )
        err = db.upsert_robot_parameter(param)
        if err:
            print(f"[Robot Settings Save] DB upsert 오류: {err}")

    return {"status": "success", "message": "Settings saved successfully"}, 200


@robot_bp.route("/robot/manual_control")
def robot_manual_control() -> str:
    connection_error = False
    db_error = False
    robot_error = False
    error_target = ""

    region_id = request.args.get("region", type=int)
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

    robot_mode = "auto"

    # 현재 로봇 상태 및 배터리 초기값 조회
    current_state = '-'
    current_battery = '-'
    if robot_id is not None:
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            current_state = robots_found[0].state or '-'

    error_target += "로봇" if robot_error else ""
    error_target += "및" if robot_error and db_error else ""
    error_target += "데이터베이스" if db_error else ""

    return render_template(
        "robot_manual_control.html",
        connection_error=connection_error,
        error_target=error_target,
        robot_mode=robot_mode,
        current_state=current_state,
        current_battery=current_battery,
    )


@robot_bp.route("/api/change_robot_state")
def change_robot_state() -> tuple[str, int]:
    mode = request.args.get("mode", type=str)
    robot_id = request.args.get("robot", type=int)

    if robot_id is not None and mode in ("auto", "manual", "follow"):
        region_id = None
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            region_id = robots_found[0].region_id
        if region_id is None:
            region_id = 1

        connector = current_app.config.get("MQTT_CONNECTOR")
        if connector:
            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/robot_mode"
            connector.publish(topic, {"data": mode})
            print(f"[Change Robot Mode] Robot ID={robot_id} command published to MQTT: {mode}")

    return "", 200


@robot_bp.route("/api/control_robot")
def control_robot() -> tuple[str, int]:
    direction = request.args.get("direction", "stop", type=str)
    robot_id = request.args.get("robot", type=int)
    region_id = request.args.get("region", type=int)
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

    if robot_id is not None:
        if region_id is None:
            robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
            if robots_found:
                region_id = robots_found[0].region_id
        if region_id is None:
            region_id = 1

        connector = current_app.config.get('MQTT_CONNECTOR')
        if connector and data:
            # MQTT_SPEC.md 규격: smartfarm/{region_id}/robot/command/{robot_id}/remote_control
            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/remote_control"
            # MQTT_SPEC.md 규격: {"data": data}
            connector.publish(topic, {"data": data})

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

    if robot_id is not None and x is not None and y is not None:
        region_id = None
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            region_id = robots_found[0].region_id
        if region_id is None:
            region_id = 1

        connector = current_app.config.get("MQTT_CONNECTOR")
        if connector:
            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/goal_pose"
            payload = {
                "x": x,
                "y": y,
                "z": 0.0,
                "qx": 0.0,
                "qy": 0.0,
                "qz": 0.0,
                "qw": 1.0,
            }
            connector.publish(topic, payload)

    return {"status": "success", "message": f"Moving to ({x}, {y})"}, 200


@robot_bp.route("/api/robot_set_initial_pose", methods=["POST"])
def robot_set_initial_pose():
    data = request.get_json() or {}
    robot_id = data.get("robot") or request.args.get("robot", type=int)
    x = data.get("x")
    y = data.get("y")
    yaw = data.get("yaw")  # radians
    print(
        f"[Robot SetInitialPose] Robot ID={robot_id} - x={x}, y={y}, yaw={yaw}"
    )

    if robot_id is not None and x is not None and y is not None and yaw is not None:
        region_id = None
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            region_id = robots_found[0].region_id
        if region_id is None:
            region_id = 1

        connector = current_app.config.get("MQTT_CONNECTOR")
        if connector:
            topic = f"smartfarm/{region_id}/robot/command/{robot_id}/initial_pose"
            payload = {
                "x": x,
                "y": y,
                "z": 0.0,
                "qx": 0.0,
                "qy": 0.0,
                "qz": math.sin(yaw / 2),
                "qw": math.cos(yaw / 2),
            }
            connector.publish(topic, payload)

    return {"status": "success", "message": f"Initial pose set at ({x}, {y}), yaw={yaw}"}, 200
