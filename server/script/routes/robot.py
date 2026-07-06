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
    robot_id = request.args.get("robot", type=int)

    # 사용 가능한 지도 목록 조회 (pgm+yaml 튜플)
    map_dir = pathlib.Path(__file__).parent.parent / "map"
    map_names = []
    if map_dir.exists():
        pgm_files = {p.stem for p in map_dir.glob("*.pgm")}
        yaml_files = {p.stem for p in map_dir.glob("*.yaml")}
        map_names = sorted(list(pgm_files.intersection(yaml_files)))

    current_robot_data = None
    if robot_id is not None:
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            current_robot_data = robots_found[0]

    return render_template(
        "robot_schedule.html",
        map_names=map_names,
        current_robot_data=current_robot_data,
    )


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


def _parse_map_files(map_name: str):
    import yaml
    from map.map_converter import parse_pgm, convert_scale_img, convert_trinary_img

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    pgm_path = map_dir / f"{map_name}.pgm"
    yaml_path = map_dir / f"{map_name}.yaml"

    if not pgm_path.exists() or not yaml_path.exists():
        return None, ({"error": "지도 파일을 찾을 수 없습니다."}, 404)

    try:
        pgm_bytes = pgm_path.read_bytes()
        yaml_str = yaml_path.read_text(encoding="utf-8")

        map_image = parse_pgm(pgm_bytes)
        map_inform = yaml.safe_load(yaml_str) or {}

        mode = map_inform.get("mode", "trinary")
        negate = map_inform.get("negate", 0)
        occupied_thresh = map_inform.get("occupied_thresh", 0.65)
        free_thresh = map_inform.get("free_thresh", 0.196)

        if "free_thresh" in map_inform:
            free_thresh = map_inform["free_thresh"]
        if "occupied_thresh" in map_inform:
            occupied_thresh = map_inform["occupied_thresh"]

        if mode == "scale":
            converted_data = [convert_scale_img(i, negate) for i in map_image["data"]]
        elif mode == "raw":
            converted_data = list(map_image["data"])
        else:
            converted_data = [
                convert_trinary_img(i, negate, occupied_thresh, free_thresh)
                for i in map_image["data"]
            ]

        height = map_image["height"]
        width = map_image["width"]

        map_arr = []
        for r in range(height - 1, -1, -1):
            map_arr.extend(converted_data[r * width : (r + 1) * width])

        origin_pos = map_inform.get("origin", [0.0, 0.0, 0.0])

        return {
            "width": width,
            "height": height,
            "resolution": map_inform.get("resolution", 0.05),
            "origin": [origin_pos[0], origin_pos[1]],
            "array": map_arr,
            "mode": mode,
            "negate": negate,
            "occupied_thresh": occupied_thresh,
            "free_thresh": free_thresh,
        }, None

    except Exception as e:
        print(f"[Map Parse Error] {map_name}: {e}")
        return None, ({"error": f"서버 오류: 지도 데이터 파싱에 실패했습니다. ({e})"}, 500)


@robot_bp.route("/api/map_data/<map_name>", methods=["GET"])
def get_map_data(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400
    data, err = _parse_map_files(map_name)
    if err:
        return err
    return data


@robot_bp.route("/api/plans/<map_name>", methods=["GET"])
def get_plans(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400
    plan_path = pathlib.Path(__file__).parent.parent / "map" / f"{map_name}_plan.json"
    if not plan_path.exists():
        plan_path.write_text("[]", encoding="utf-8")
    try:
        plans = json.loads(plan_path.read_text(encoding="utf-8"))
        return {"plans": plans}
    except Exception as e:
        print(f"[Plan API Error] {map_name}: {e}")
        return {"error": str(e)}, 500


@robot_bp.route("/api/plans/<map_name>", methods=["PUT"])
def save_plans(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400
    data = request.get_json() or {}
    plans = data.get("plans", [])
    plan_path = pathlib.Path(__file__).parent.parent / "map" / f"{map_name}_plan.json"
    try:
        plan_path.write_text(
            json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "success"}
    except Exception as e:
        print(f"[Plan Save Error] {map_name}: {e}")
        return {"error": str(e)}, 500


@robot_bp.route("/api/map_pgm_pixels/<map_name>", methods=["GET"])
def get_map_pgm_pixels(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400

    from map.map_converter import parse_pgm

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    pgm_path = map_dir / f"{map_name}.pgm"

    if not pgm_path.exists():
        return {"error": f"지도 '{map_name}'의 pgm 파일을 찾을 수 없습니다."}, 404

    try:
        pgm_bytes = pgm_path.read_bytes()
        map_image = parse_pgm(pgm_bytes)
        return {"pixels": map_image["data"]}, 200
    except Exception as e:
        print(f"[GET map_pgm_pixels Error] {map_name}: {e}")
        return {"error": str(e)}, 500


@robot_bp.route("/api/map_data/<map_name>", methods=["PUT"])
def save_map_data(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400

    import base64

    data = request.get_json() or {}
    pixels = data.get("pixels")
    width = data.get("width")
    height = data.get("height")

    if pixels is None or width is None or height is None:
        return {"error": "필수 항목(pixels, width, height)이 누락되었습니다."}, 400

    if len(pixels) != width * height:
        return {"error": "픽셀 데이터 크기가 가로x세로 크기와 일치하지 않습니다."}, 400

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    pgm_path = map_dir / f"{map_name}.pgm"
    yaml_path = map_dir / f"{map_name}.yaml"

    try:
        header = f"P5\n{width} {height}\n255\n".encode()
        pgm_bytes = header + bytes(pixels)
        pgm_path.write_bytes(pgm_bytes)

        yaml_str = ""
        if yaml_path.exists():
            yaml_str = yaml_path.read_text(encoding="utf-8")

        mqtt_payload = {
            "name": map_name,
            "img": base64.b64encode(pgm_bytes).decode("utf-8"),
            "inform": yaml_str
        }

        connector = current_app.config.get("MQTT_CONNECTOR")
        all_robots, _ = db.get_current_robot()

        published_count = 0
        if all_robots:
            for robot in all_robots:
                if robot.map == map_name:
                    region_id = robot.region_id or 1
                    robot_id = robot.id
                    topic = f"smartfarm/{region_id}/robot/command/{robot_id}/map_data"
                    if connector:
                        connector.publish(topic, mqtt_payload)
                        published_count += 1

        print(f"[Save Map Data] '{map_name}.pgm' saved. Width={width}, Height={height}. Published MQTT to {published_count} robots.")
        return {"status": "success", "published_robots": published_count}, 200

    except Exception as e:
        print(f"[Save Map Data Error] {map_name}: {e}")
        return {"error": str(e)}, 500


@robot_bp.route("/api/map_clone/<map_name>", methods=["POST"])
def clone_map(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    pgm_path = map_dir / f"{map_name}.pgm"
    yaml_path = map_dir / f"{map_name}.yaml"
    plan_path = map_dir / f"{map_name}_plan.json"

    if not pgm_path.exists() or not yaml_path.exists():
        return {"error": "원본 지도 파일을 찾을 수 없습니다."}, 404

    import re
    m = re.match(r"^(.*?)\((\d+)\)$", map_name)
    if m:
        stem = m.group(1)
        digit = int(m.group(2))
    else:
        stem = map_name
        digit = 1

    new_digit = digit + 1
    while True:
        candidate_name = f"{stem}({new_digit})"
        cand_pgm = map_dir / f"{candidate_name}.pgm"
        cand_yaml = map_dir / f"{candidate_name}.yaml"
        if not cand_pgm.exists() and not cand_yaml.exists():
            new_map_name = candidate_name
            break
        new_digit += 1

    # 파일 복사
    import shutil
    try:
        shutil.copy2(pgm_path, map_dir / f"{new_map_name}.pgm")
    except Exception as e:
        return {"error": f"PGM 복사 실패: {e}"}, 500
    
    # yaml 복사 및 image 속성 변경
    import yaml
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
        yaml_data["image"] = f"{new_map_name}.pgm"
        with open(map_dir / f"{new_map_name}.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(yaml_data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return {"error": f"YAML 처리 중 오류 발생: {e}"}, 500

    # plan 복사 (있다면)
    if plan_path.exists():
        try:
            shutil.copy2(plan_path, map_dir / f"{new_map_name}_plan.json")
        except Exception as e:
            print(f"[Clone Map Warning] Plan 파일 복사 실패: {e}")

    return {"status": "success", "new_map": new_map_name}, 200


@robot_bp.route("/api/map_rename", methods=["POST"])
def rename_map():
    data = request.get_json() or {}
    old_name = data.get("old_name")
    new_name = data.get("new_name")

    if not old_name or not new_name:
        return {"error": "기존 이름과 새 이름이 모두 필요합니다."}, 400

    if "/" in old_name or "\\" in old_name or ".." in old_name or "/" in new_name or "\\" in new_name or ".." in new_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    old_pgm = map_dir / f"{old_name}.pgm"
    old_yaml = map_dir / f"{old_name}.yaml"
    old_plan = map_dir / f"{old_name}_plan.json"

    new_pgm = map_dir / f"{new_name}.pgm"
    new_yaml = map_dir / f"{new_name}.yaml"
    new_plan = map_dir / f"{new_name}_plan.json"

    if not old_pgm.exists() or not old_yaml.exists():
        return {"error": "원본 지도 파일을 찾을 수 없습니다."}, 404

    if new_pgm.exists() or new_yaml.exists():
        return {"error": "동일한 이름의 지도가 이미 존재합니다."}, 400

    # DB 업데이트: robot 테이블의 map 필드 갱신
    err = db.rename_robot_map(old_name, new_name)
    if err:
        return {"error": f"DB 업데이트 실패: {err}"}, 500

    # 파일 이름 변경 및 yaml 수정
    import shutil
    import yaml

    try:
        with open(old_yaml, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
        yaml_data["image"] = f"{new_name}.pgm"
        with open(new_yaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(yaml_data, f, default_flow_style=False, allow_unicode=True)

        shutil.move(str(old_pgm), str(new_pgm))
        if old_yaml.exists():
            old_yaml.unlink()

        if old_plan.exists():
            shutil.move(str(old_plan), str(new_plan))

        return {"status": "success", "new_map": new_name}, 200
    except Exception as e:
        return {"error": f"파일 변경 실패: {e}"}, 500


@robot_bp.route("/api/map_delete/<map_name>", methods=["POST"])
def delete_map(map_name: str):
    if "/" in map_name or "\\" in map_name or ".." in map_name:
        return {"error": "유효하지 않은 지도명입니다."}, 400

    map_dir = pathlib.Path(__file__).parent.parent / "map"
    pgm_path = map_dir / f"{map_name}.pgm"
    yaml_path = map_dir / f"{map_name}.yaml"
    plan_path = map_dir / f"{map_name}_plan.json"

    # DB 업데이트: robot 테이블의 map 필드 None 처리
    err = db.clear_robot_map_on_delete(map_name)
    if err:
        return {"error": f"DB 업데이트 실패: {err}"}, 500

    deleted_files = []
    try:
        if pgm_path.exists():
            pgm_path.unlink()
            deleted_files.append(pgm_path.name)
        if yaml_path.exists():
            yaml_path.unlink()
            deleted_files.append(yaml_path.name)
        if plan_path.exists():
            plan_path.unlink()
            deleted_files.append(plan_path.name)

        return {"status": "success", "deleted": deleted_files}, 200
    except Exception as e:
        return {"error": f"파일 삭제 중 오류 발생: {e}"}, 500
