import threading


class FrameStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.images = dict()

    def get_image_frame(self, id: int, side: str):
        with self.lock:
            robot_frames = self.images.get(id)
            if robot_frames is None:
                return None
            return robot_frames.get(side)

    def update_frame(self, id: int, side: str, frame: bytes):
        with self.lock:
            if id not in self.images:
                self.images[id] = {}
            self.images[id][side] = frame


class RobotStateStore:
    pass
