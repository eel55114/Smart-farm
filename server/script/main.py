import cv2
import numpy as np
import time
from flask import Flask, render_template, Response, request
from flask_bootstrap import Bootstrap5
import os
from dotenv import load_dotenv

load_dotenv()

from script.db_manager.manager import DBManager
import script.db_manager.datatype

app = Flask(__name__)
bootstrap = Bootstrap5(app)

conn_url = os.getenv('DATABASE_URL')
db = DBManager(conn_url)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session_local.remove()

IMGS = {
    "robot_side_camera": None,
    "robot_front_camera": None
}

img = np.zeros((480, 640, 3), dtype=np.uint8)
success, buf = cv2.imencode('.jpg', img)
EMPTY_IMG_BINARY = buf.tobytes()


@app.route('/image_refresh', methods=['POST'])
def image_refresh():
    global IMGS
    direction = request.args.get('dir')

    file = request.files.get('image')

    if file:
        if direction == "side":
            IMGS[f"robot_side_camera"] = file.read()
        elif direction == "front":
            IMGS[f"robot_front_camera"] = file.read()
        return "OK", 200

    return "Invalid Request", 400


def generate_frames(img_name):
    while True:
        frame_data = IMGS[img_name] if IMGS[img_name] is not None else EMPTY_IMG_BINARY

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

        time.sleep(0.03)


@app.route('/robot_side_camera')
def robot_side_camera():
    return Response(generate_frames("robot_side_camera"),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/robot_front_camera')
def robot_front_camera():
    return Response(generate_frames("robot_front_camera"),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/robot')
def robot():
    return render_template('robot.html')

@app.route('/plants')
def plants():
    types, err = db.get_active_plant_type()
    if err is not None:
        return render_template('plants.html', data=dict())

    plants, err = db.get_plant_state(ids=[], all=True)
    if err is not None:
        return render_template('plants.html', data=dict())

    data = dict()
    for type_id, type_name in types.items():
        data[type_name] = []

    for plant in plants:
        type_name = types[plant.type_id]
        data[type_name].append(plant)

    return render_template('plants.html', data=data)

@app.route('/environment')
def environment():
    return render_template('environment.html')

@app.route('/system')
def system():
    return render_template('system.html')


if __name__ == '__main__':
    # 외부 접근이 가능하도록 host 설정 권장
    app.run(port=5000, debug=True)