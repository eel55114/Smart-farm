import gevent.monkey

gevent.monkey.patch_all()

from db_instance import db
from dotenv import load_dotenv
from flask import Flask, request
from flask_bootstrap import Bootstrap5
from flask_socketio import SocketIO
from routes.environment import environment_bp
from routes.home import home_bp
from routes.plants import plants_bp
from routes.robot import robot_bp

load_dotenv()

app = Flask(__name__)
bootstrap = Bootstrap5(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")


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
        # app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print(f"Startup Critical Error: {e}")
