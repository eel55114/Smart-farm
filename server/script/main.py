import json
import os
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from db_manager.manager import DBManager

# from node import node
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request
from flask_bootstrap import Bootstrap5

load_dotenv()


app = Flask(__name__)
bootstrap = Bootstrap5(app)

conn_url = os.getenv("DATABASE_URL")
db = DBManager(conn_url)


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session_local.remove()


IMGS = {"robot_side_camera": None, "robot_front_camera": None}

img = np.zeros((480, 640, 3), dtype=np.uint8)
success, buf = cv2.imencode(".jpg", img)
EMPTY_IMG_BINARY = buf.tobytes()


@app.route("/image_refresh", methods=["POST"])
def image_refresh():
    global IMGS
    direction = request.args.get("dir")

    file = request.files.get("image")

    if file:
        if direction == "side":
            IMGS["robot_side_camera"] = file.read()
        elif direction == "front":
            IMGS["robot_front_camera"] = file.read()
        return "OK", 200

    return "Invalid Request", 400


def generate_frames(img_name):
    while True:
        frame_data = IMGS[img_name] if IMGS[img_name] is not None else EMPTY_IMG_BINARY

        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n")

        time.sleep(0.03)


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


@app.route("/robot")
def robot():
    return render_template("robot.html")


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
            status_data[type_name].append(plant)

    page = request.args.get("page", 1, type=int)
    days = request.args.get("days", 10, type=int)

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
    history_columns = ["일시", "작물 종류", "평균 성장도", "병충해 피해율"]

    for h in history_records:
        temp = [
            h.created_at.strftime('%Y-%m-%d %H:%M'),
            types.get(h.type_id, "Unknown"),
            f"{round(h.avg_maturity*100, 2)}%",
            f"{round(h.disease_ratio*100, 2)}%"
        ]

        history_data.append(temp)

    latest_records, err = db.get_plant_statistics(type_ids=type_ids, n=1)
    if err is not None:
        db_error = True
    
    if latest_records:
        end_date = latest_records[0].created_at
    else:
        end_date = datetime.now()

    start_date = end_date - timedelta(days=days - 1)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    graph_records, err = db.get_plant_statistics(type_ids=type_ids, start_date=start_date)
    if err is not None:
        db_error = True
    

    labels = []
    curr = start_date
    while curr.date() <= end_date.date():
        labels.append(curr.strftime("%y%m%d"))
        curr += timedelta(days=1)

    chart_data = {"labels": labels, "datasets": []}

    colors = [
        ("rgba(255, 99, 132, 1)", "rgba(255, 99, 132, 0.2)"),
        ("rgba(54, 162, 235, 1)", "rgba(54, 162, 235, 0.2)"),
        ("rgba(255, 206, 86, 1)", "rgba(255, 206, 86, 0.2)"),
        ("rgba(75, 192, 192, 1)", "rgba(75, 192, 192, 0.2)"),
    ]

    if graph_records:
        for i, type_id in enumerate(type_ids):
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

            c1, _ = colors[(i * 2) % len(colors)]
            c2, _ = colors[(i * 2 + 1) % len(colors)]

            chart_data["datasets"].append(
                {
                    "label": f"{type_name} 평균 성장도",
                    "data": avg_mat,
                    "borderColor": c1,
                    "backgroundColor": c1,
                    "spanGaps": False,
                    "tension": 0.1,
                }
            )
            chart_data["datasets"].append(
                {
                    "label": f"{type_name} 병충해 비율",
                    "data": dis_rat,
                    "borderColor": c2,
                    "backgroundColor": c2,
                    "spanGaps": False,
                    "tension": 0.1,
                }
            )

    return render_template(
        "plants.html",
        status_data=status_data,
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        days=days,
        chart_data=json.dumps(chart_data),
        db_error=db_error
    )


@app.route("/api/current_sensors")
def get_current_sensors():



    db_error = False
    sensors, err = db.get_current_sensors([], all=True)
    if err is not None:
        db_error = True

    data = []
    for i in sensors:
        is_danger = False
        if i.type_id == 1: # 조도
            value = f"{min(round(i.value * 100, 2), 100)}%"
        elif i.type_id == 2: # 습도
            value = f"{min(round(i.value, 2), 100)}%"
        elif i.type_id == 3: # 온도
            value = f"{i.value}°C"
        elif i.type_id == 4: # 화염
            value = f"{'화재 발생' if i.value > 0.5 else '없음'}"
            is_danger = i.value > 0.5
        else:
            value = "알 수 없음"

        temp = {
            "id": i.sensor_id,
            "type_name": i.type_name,
            "icon_src": f"/static/images/sensor_{i.type_id}.png",
            "value": value,
            "is_danger": is_danger,
        }
        data.append(temp)
        print(i.type_id)
        print(temp)

    return render_template(
        "_sensor_state.html",
        data = data,
        db_error = db_error,
    )



@app.route("/environment")
def environment():
    db_error = False

    page = request.args.get("page", 1, type=int)
    # days = request.args.get("days", 10, type=int)

    per_page = 15
    offset = (page - 1) * per_page

    history_records, err = db.get_sensor_history(
        sensor_ids=[], all=True,
        n=per_page + 1, offset=offset
    )
    if err is not None:
        print(err)
        db_error = True

    has_next = len(history_records) > per_page if history_records else False
    history_records = history_records[:per_page] if history_records else []
    history_data = []
    history_columns = ["이력 ID", "일시", "센서 ID", "센서 유형", "값"]

    for h in history_records:
        temp = [
            h.id,
            h.created_at.strftime('%Y-%m-%d %H:%M'),
            h.sensor_id,
            h.sensor_type_name,
            h.value
        ]

        history_data.append(temp)

    return render_template(
        "environment.html",
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        db_error=db_error
    )


@app.route("/system")
def system():
    return render_template("system.html")


if __name__ == "__main__":
    app.run(port=5000, debug=True)
