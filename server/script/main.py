import json
import os
import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
import rclpy
import requests
from db_manager.manager import DBManager
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request
from flask_bootstrap import Bootstrap5
from node import battery_node, real_time_image
from rclpy.executors import MultiThreadedExecutor

load_dotenv()

app = Flask(__name__)
bootstrap = Bootstrap5(app)

conn_url = os.getenv("DATABASE_URL")
assert conn_url is not None
db = DBManager(conn_url)


BATTERY_MONITOR = None
IMAGE_RECEIVER = None

img = np.zeros((480, 640, 3), dtype=np.uint8)
_, buf = cv2.imencode(".jpg", img)
EMPTY_IMG_BINARY = buf.tobytes()

IMGS = {
    "robot_side_camera": EMPTY_IMG_BINARY,
    "robot_front_camera": EMPTY_IMG_BINARY,
}
IMGS_LOCK = threading.Lock()

HUB_ENDPOINT = "192.168.0.172"


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session_local.remove()


def generate_frames(img_name):
    while True:
        with IMGS_LOCK:
            # None 체크 후 데이터 추출
            frame_data = IMGS.get(img_name)
            if frame_data is None:
                frame_data = EMPTY_IMG_BINARY

        # 표준 MJPEG 스트림 형식:
        # --frame(바운더리) + 헤더 + 빈 줄(\r\n\r\n) + 데이터 + 바운더리 끝(\r\n)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n")

        time.sleep(0.04)  # 25FPS 수준으로 조절 (ROS 주기에 맞춤)


@app.route("/robot_side_camera")
def robot_side_camera():
    return Response(
        generate_frames("robot_side_camera"),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/robot_front_camera")
def robot_front_camera():
    return Response(
        generate_frames("robot_front_camera"),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/change_robot_state")
def change_robot_state():
    is_manual = request.args.get("is_manual", 0, type=int)

    data = "manual" if is_manual else "auto"

    IMAGE_RECEIVER.set_mode(data)
    return "", 200


@app.route("/api/control_robot")
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

    IMAGE_RECEIVER.set_vel(data)

    return "", 200


@app.route("/api/current_robot_state")
def current_robot_state():
    battery_percent = BATTERY_MONITOR.get_battery_state()["percent"]

    return render_template(
        "_robot_state.html",
        current_battery=battery_percent,
        current_state="-",
    )


@app.route("/api/control_actuator")
def control_actuator():
    device = request.args.get("device", "", type=str)
    data = request.args.get("data", 0, type=int)

    if device == "light":
        resp = requests.get(f"{HUB_ENDPOINT}/light?on={data}")

    if resp.status_code == 200:
        return "", 200
    else:
        return "Hub not respond.", 400


@app.route("/robot")
def robot():
    connection_error = False
    db_error = False
    robot_error = False
    error_target = ""

    page = 1
    has_next = False

    page = request.args.get("page", 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    robot_histories, err = db.get_robot_history(n=per_page, offset=offset)
    if err is not None:
        db_error = True

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


@app.route("/plants")
def plants():
    db_error = False
    types, err = db.get_active_plant_type()
    if err is not None:
        types = dict()

    # 현재 작물 정보 쿼리
    plants_data, err = db.get_plant_state(ids=[], all=True)
    if err is not None:
        db_error = True
        plants_data = []

    status_data = dict()
    for type_id, type_name in types.items():
        status_data[type_name] = []

    # 현재 작물 정보를 작물 타입별로 분류
    for plant in plants_data:
        type_name = types.get(plant.type_id)
        if type_name:
            plant.maturity = max(min(round(plant.maturity * 100, 1), 100), 0)
            status_data[type_name].append(plant)

    page = request.args.get("page", 1, type=int)
    days = request.args.get("days", 5, type=int)

    type_ids = list(types.keys())

    per_page = 15
    offset = (page - 1) * per_page

    history_records, err = db.get_plant_statistics(
        type_ids=type_ids, n=per_page + 1, offset=offset
    )
    if err is not None:
        db_error = True

    has_next = len(history_records) > per_page if history_records else False
    history_records = history_records[:per_page] if history_records else []
    history_data = []
    history_columns = ["이력 ID", "일시", "작물 종류", "평균 성장도", "병충해 피해율"]

    for h in history_records:
        temp = [
            h.id,
            h.created_at.strftime("%Y-%m-%d %H:%M"),
            types.get(h.type_id, "Unknown"),
            f"{round(h.avg_maturity * 100, 2)}%",
            f"{round(h.disease_ratio * 100, 2)}%",
        ]

        history_data.append(temp)

    latest_records, err = db.get_plant_statistics(type_ids=type_ids, n=1)
    if err is not None:
        db_error = True

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    parsed_custom_date = False
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            parsed_custom_date = True
        except ValueError:
            pass

    if not parsed_custom_date:
        if latest_records:
            end_date = latest_records[0].created_at
        else:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=days - 1)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    graph_records, err = db.get_plant_statistics(
        type_ids=type_ids, start_date=start_date, end_date=end_date
    )
    if err is not None:
        db_error = True

    labels = []
    curr = start_date
    while curr.date() <= end_date.date():
        labels.append(curr.strftime("%y%m%d"))
        curr += timedelta(days=1)

    charts_data = {}

    if graph_records:
        for type_id in type_ids:
            type_name = types[type_id]
            avg_mat = []
            dis_rat = []

            type_records = [r for r in graph_records if r.type_id == type_id]
            records_by_date = {}
            for r in type_records:
                date_str = r.created_at.strftime("%y%m%d")
                records_by_date.setdefault(date_str, []).append(r)

            for label in labels:
                if label in records_by_date:
                    day_recs = records_by_date[label]
                    avg_mat.append(
                        round(sum(r.avg_maturity for r in day_recs) / len(day_recs), 3)
                    )
                    dis_rat.append(
                        round(sum(r.disease_ratio for r in day_recs) / len(day_recs), 3)
                    )
                else:
                    avg_mat.append(None)
                    dis_rat.append(None)

            maturity_fg_color = "rgba(40, 167, 69, 1)"
            maturity_bg_color = "rgba(40, 167, 69, 0.2)"
            disease_fg_color = "rgba(220, 53, 69, 1)"
            disease_bg_color = "rgba(220, 53, 69, 0.2)"

            charts_data[type_name] = {
                "labels": labels,
                "datasets": [
                    {
                        "label": "평균 성장도",
                        "data": avg_mat,
                        "borderColor": maturity_fg_color,
                        "backgroundColor": maturity_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "병충해 비율",
                        "data": dis_rat,
                        "borderColor": disease_fg_color,
                        "backgroundColor": disease_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                ],
            }

    return render_template(
        "plants.html",
        status_data=status_data,
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        days=days,
        charts_data=json.dumps(charts_data),
        db_error=db_error,
    )


@app.route("/api/current_sensors")
def get_current_sensors():

    SENSORS = {
        1: "lightbulb",
        2: "water_drop",
        3: "thermometer",
        4: "local_fire_department",
    }

    db_error = False
    sensors, err = db.get_current_sensors([], all=True)
    if err is not None:
        db_error = True

    data = []
    for i in sensors:
        is_danger = False
        if i.type_id == 1:  # 조도
            value = f"{min(round(i.value * 100, 2), 100)}%"
        elif i.type_id == 2:  # 습도
            value = f"{min(round(i.value, 2), 100)}%"
        elif i.type_id == 3:  # 온도
            value = f"{i.value}°C"
        elif i.type_id == 4:  # 화염
            value = f"{'화재 발생' if i.value > 0.5 else '없음'}"
            is_danger = i.value > 0.5
        else:
            value = "알 수 없음"

        temp = {
            "id": i.sensor_id,
            "type_name": i.type_name,
            "icon_name": SENSORS[i.type_id],
            "value": value,
            "is_danger": is_danger,
        }
        data.append(temp)
        print(i.type_id)
        print(temp)

    return render_template(
        "_sensor_state.html",
        data=data,
        db_error=db_error,
    )


@app.route("/environment")
def environment():
    db_error = False

    page = request.args.get("page", 1, type=int)
    days = request.args.get("days", 5, type=int)

    per_page = 15
    offset = (page - 1) * per_page

    history_records, err = db.get_sensor_history(
        sensor_ids=[], all=True, n=per_page + 1, offset=offset
    )
    if err is not None:
        print(err)
        db_error = True

    has_next = len(history_records) > per_page if history_records else False
    history_records = history_records[:per_page] if history_records else []
    history_data = []
    history_columns = [
        "기준 시간",
        "센서 ID",
        "센서 유형",
        "최댓값",
        "평균값",
        "최솟값",
    ]

    for h in history_records:
        temp = [
            h.time_bucket.strftime("%Y-%m-%d %H:%M"),
            h.sensor_id,
            h.sensor_type_name,
            round(h.max, 2),
            round(h.avg, 2),
            round(h.min, 2),
        ]
        history_data.append(temp)

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    parsed_custom_date = False
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            parsed_custom_date = True
        except ValueError:
            pass

    if not parsed_custom_date:
        latest_records, err = db.get_sensor_history(sensor_ids=[], all=True, n=1)
        if latest_records:
            end_date = latest_records[0].time_bucket
        else:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=days - 1)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    graph_records, err = db.get_sensor_history(
        sensor_ids=[], all=True, start_date=start_date, end_date=end_date
    )
    if err is not None:
        db_error = True

    labels = []
    curr = start_date
    while curr.date() <= end_date.date():
        labels.append(curr.strftime("%m%d %H:%M:%S"))
        curr += timedelta(minutes=5)

    charts_data = {}
    if graph_records:
        # 센서 종류 파악
        types = {}
        for r in graph_records:
            types[r.sensor_type] = r.sensor_type_name

        for type_id, type_name in types.items():
            avg_vals = []
            max_vals = []
            min_vals = []

            type_records = [r for r in graph_records if r.sensor_type == type_id]
            records_by_date = {}
            for r in type_records:
                date_str = r.time_bucket.strftime("%m%d %H:%M:%S")
                records_by_date.setdefault(date_str, []).append(r)

            for label in labels:
                if label in records_by_date:
                    day_recs = records_by_date[label]
                    avg_vals.append(
                        round(sum(r.avg for r in day_recs) / len(day_recs), 2)
                    )
                    max_vals.append(round(max(r.max for r in day_recs), 2))
                    min_vals.append(round(min(r.min for r in day_recs), 2))
                else:
                    avg_vals.append(None)
                    max_vals.append(None)
                    min_vals.append(None)

            avg_fg_color = "rgba(0, 123, 255, 1)"
            avg_bg_color = "rgba(0, 123, 255, 0.2)"
            max_fg_color = "rgba(220, 53, 69, 1)"
            max_bg_color = "rgba(220, 53, 69, 0.2)"
            min_fg_color = "rgba(40, 167, 69, 1)"
            min_bg_color = "rgba(40, 167, 69, 0.2)"

            charts_data[type_name] = {
                "labels": labels,
                "datasets": [
                    {
                        "label": "최댓값",
                        "data": max_vals,
                        "borderColor": max_fg_color,
                        "backgroundColor": max_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "평균값",
                        "data": avg_vals,
                        "borderColor": avg_fg_color,
                        "backgroundColor": avg_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "최솟값",
                        "data": min_vals,
                        "borderColor": min_fg_color,
                        "backgroundColor": min_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                ],
            }

    return render_template(
        "environment.html",
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        days=days,
        charts_data=json.dumps(charts_data),
        db_error=db_error,
    )


def run_ros_thread(battery_node, image_node):
    global IMGS

    executor = MultiThreadedExecutor()
    executor.add_node(battery_node)
    executor.add_node(image_node)

    try:
        while rclpy.ok():
            executor.spin_once()

            latest_img = image_node.get_image()
            if latest_img is not None:
                with IMGS_LOCK:
                    IMGS["robot_side_camera"] = latest_img

    except Exception as e:
        print(f"ROS Spin Error: {e}")
    finally:
        executor.shutdown()
        rclpy.shutdown()


if __name__ == "__main__":
    try:
        rclpy.init()
        BATTERY_MONITOR = battery_node.BatteryMonitor()
        IMAGE_RECEIVER = real_time_image.RobotWebBridge()

        ros_thread = threading.Thread(
            target=run_ros_thread, args=[BATTERY_MONITOR, IMAGE_RECEIVER], daemon=True
        )
        # ros_thread.start()

        time.sleep(1.0)

        # app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=True)
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print(f"Startup Critical Error: {e}")
    finally:
        if rclpy.ok():
            rclpy.shutdown()
