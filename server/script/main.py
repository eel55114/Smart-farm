from dotenv import load_dotenv

load_dotenv()

import os

import gevent.monkey

gevent.monkey.patch_all()

from db_instance import db
from flask import Flask, request
from flask_bootstrap import Bootstrap5
from flask_socketio import SocketIO
from mqtt_manager import Connector
from routes.environment import environment_bp
from routes.home import home_bp
from routes.plants import plants_bp
from routes.robot import robot_bp

app = Flask(__name__)
bootstrap = Bootstrap5(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")


def relay_robot_ephemeral_data(robot_id, data):
    socketio.emit(f"robot_{robot_id}_ephemeral", data)


@socketio.on("control_robot")
def handle_robot_control(data):
    robot_id = data.get("robot_id")
    region_id = data.get("region_id")
    command = data.get("command")
    value = data.get("value")

    if not robot_id or not command:
        return

    # region_id가 소켓 페이로드에 누락되어 넘어왔을 경우, DB 조회를 통해 로봇의 실제 소속 region_id 획득
    if not region_id:
        robots_found, _ = db.get_current_robot(robot_ids=[robot_id])
        if robots_found:
            region_id = robots_found[0].region_id
    if not region_id:
        region_id = 1  # 최종 Fallback

    # MQTT_SPEC.md 규격: smartfarm/{region_id}/robot/command/{robot_id}/{command}
    topic = f"smartfarm/{region_id}/robot/command/{robot_id}/{command}"

    connector = app.config.get("MQTT_CONNECTOR")
    if connector:
        # MQTT_SPEC.md 규격: {"data": value}
        success = connector.publish(topic, {"data": value})
        if not success:
            print(f"Failed to publish control command to Robot {robot_id}")


@socketio.on("stream_front")
def handle_cam1(data):
    socketio.emit("render_front", data, include_self=False)


@socketio.on("stream_side")
def handle_cam2(data):
    socketio.emit("render_side", data, include_self=False)


app.register_blueprint(home_bp)
app.register_blueprint(plants_bp)
app.register_blueprint(environment_bp)
app.register_blueprint(robot_bp)


@app.context_processor
def inject_regions_and_robots():
    regions, _ = db.get_all_regions()
    current_region = request.args.get("region", type=int)

    robots, _ = db.get_current_robot()
    current_robot = request.args.get("robot", type=int)

    # 1. 현재 리전에 해당하는 로봇만 필터링
    valid_robots = robots
    if current_region is not None:
        valid_robots = [r for r in robots if r.region_id == current_region]

    # 2. current_robot 유효성 검사 및 기본값 지정 (가장 ID 번호가 빠른 로봇)
    if current_robot is not None:
        matching_robot = next((r for r in valid_robots if r.id == current_robot), None)
        if not matching_robot:
            current_robot = None

    if current_robot is None and valid_robots:
        default_robot = min(valid_robots, key=lambda r: r.id)
        current_robot = default_robot.id

    return dict(
        regions=regions,
        current_region=current_region,
        robots=robots,
        current_robot=current_robot,
    )


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session_local.remove()


if __name__ == "__main__":
    try:
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
            print("Initializing Stateless MQTT Connector and Background Thread...")
            connector = Connector(on_robot_ephemeral_data=relay_robot_ephemeral_data)
            app.config["MQTT_CONNECTOR"] = connector
            connector.run()

        socketio.run(app, host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print(f"Startup Critical Error: {e}")
