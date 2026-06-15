import rclpy
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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


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
def inject_regions():
    regions, _ = db.get_all_regions()
    current_region = request.args.get("region", type=int)
    return dict(regions=regions, current_region=current_region)


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session_local.remove()


if __name__ == "__main__":
    try:
        # app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print(f"Startup Critical Error: {e}")
    finally:
        if rclpy.ok():
            rclpy.shutdown()
