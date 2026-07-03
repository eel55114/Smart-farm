import base64
import json
import os
import queue
import threading
import cv2
import numpy as np
import time
from ultralytics import YOLO
import dotenv
import paho.mqtt.client as mqtt
from db_manager import datatype
from db_manager.manager import DBManager
from paho.mqtt.enums import CallbackAPIVersion
from queue import Queue


class Connector:
    def __init__(self, on_robot_ephemeral_data=None) -> None:
        dotenv.load_dotenv()

        mqtt_host = os.getenv("MQTT_HOST")
        mqtt_port = os.getenv("MQTT_PORT")
        url = os.getenv("DATABASE_URL")

        try:
            assert mqtt_host is not None
            assert mqtt_port is not None
            assert url is not None
        except AssertionError:
            print("환경 변수 인식 실패")
            return
        model_path = r"C:\python-opencv\best04291048.pt"
        try:
            self.model = YOLO(model_path)
            print("YOLO 모델 로드 성공!")
        except Exception as e:
            print(f"모델 로드 실패! 경로를 확인하세요: {e}")
        self.mqtt_host = mqtt_host
        self.mqtt_port = int(mqtt_port)
        self.mqttc = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect

        self.db = DBManager(url)
        self.queue = queue.Queue()

        self.analysis_duration = 3.0
        self.is_analyzing = False
        self.start_time = None
        self.current_plant_id = None

        self.max_objects_count = -1
        self.best_frame_ripeness_list = []
        self.best_frame_has_disease = False

        self.image_queue = Queue()
        self._is_running = False
        self._db_thread = None
        self.on_robot_ephemeral_data = on_robot_ephemeral_data

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"Connected with result code {reason_code}")

        client.subscribe("smartfarm/+/plant/img/#")

        self.mqttc.message_callback_add(
            "smartfarm/+/plant/img/captured_img", self.on_plnat_img
        )

    def on_plnat_img(self, client, userdata, msg):
        topic = msg.topic.split("/")

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            plant_id = int(payload["id"])
            msg_time = int(payload["time"])
            img_base64 = payload["img"]

            print(f"📩 [MQTT 수신] ID: {plant_id} | 시간: {msg_time} | 이미지 크기(Base64): {len(img_base64)} bytes")

        except json.JSONDecodeError:
            print("MQTT Payload JSON 파싱 에러")
            return
        except KeyError as e:
            print(e)
            return

        try:
            # 이미지 바이너리
            img_bytes = base64.b64decode(img_base64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_np is None:
                print("이미지 디코딩 실패")
                return
        except Exception as e:
            print(f"이미지 변환 에러: {e}")
            return
        except Exception as e:
            print(f"Base64 디코딩 실패: {e}")
            return
        if not self.is_analyzing:
        # @@@ 여기에 분석 코드를 작성 @@@
            self.max_objects_count = -1
            self.best_frame_ripeness_list = []
            self.best_frame_has_disease = False
            self.current_plant_id = plant_id

            while not self.image_queue.empty():
                self.image_queue.get()

            self.start_time = time.time()
            self.is_analyzing = True
            self.image_queue.put(img_np)
        else:
            if self.current_plant_id == plant_id:
                if time.time() - self.start_time <= self.analysis_duration:
                    self.image_queue.put(img_np)
            else:
                print(f"⚠️ 경고: [ID: {self.current_plant_id}] 처리 중 새 ID({plant_id}) 유입됨.")

    def analysis_worker(self):
        """별도 스레드: 큐에 쌓인 프레임을 YOLO로 분석하고 베스트 프레임을 찾음"""
        while self._is_running:
            if not self.is_analyzing:
                time.sleep(0.1)
                continue

            # 큐에서 프레임 꺼내기
            try:
                # timeout을 주어 무한 대기 방지 (0.1초마다 타이머 체크 가능하도록)
                frame = self.image_queue.get(timeout=0.1)

                # YOLO 추론
                results = self.model(frame, stream=True, conf=0.4, verbose=False)

                for result in results:
                    boxes = result.boxes
                    current_count = len(boxes)

                    temp_ripeness = []
                    temp_disease = False
                    for box in boxes:
                        cls = int(box.cls[0])
                        name = self.model.names[cls]
                        if name == 'disease':
                            temp_disease = True
                        elif name in ['green', 'half_ripened', 'fully_ripened']:
                            temp_ripeness.append(name)

                    # [핵심] 객체가 가장 많이 탐지된 프레임을 베스트로 갱신
                    if current_count >= self.max_objects_count:
                        self.max_objects_count = current_count
                        self.best_frame_ripeness_list = temp_ripeness
                        self.best_frame_has_disease = temp_disease

                self.image_queue.task_done()

            except queue.Empty:
                # 큐가 비어있고, 3초(+0.5초 여유)가 지났다면 최종 결과 처리
                if self.start_time and (time.time() - self.start_time > self.analysis_duration + 0.5):
                    self.process_final_result()
                    self.is_analyzing = False
                    self.start_time = None
                    self.current_plant_id = None

    def process_final_result(self):
        """3초 분석이 끝나면 최종 결과를 계산하여 DB 큐에 넣음"""
        if self.max_objects_count <= 0:
            print(f"⚠️ [ID: {self.current_plant_id}] 인식된 객체 없음.")
            return

        score_map = {'green': 0, 'half_ripened': 0.5, 'fully_ripened': 1}
        scores = [score_map[n] for n in self.best_frame_ripeness_list if n in score_map]

        # ----------------------------------------------------
        # 원하시는 직관적인 변수명으로 매핑
        plant_id = self.current_plant_id
        maturity = sum(scores) / len(scores) if scores else 0.0
        is_disease = self.best_frame_has_disease
        # ----------------------------------------------------

        print("-" * 40)
        print(f"📊 [ID: {plant_id} 분석 완료]")
        print(f"▶ 최적 프레임 객체 수: {self.max_objects_count}개")
        print(f"▶ 평균 성숙도: {maturity * 100:.1f}%")
        print(f"▶ 병해 여부: {'탐지됨' if is_disease else '정상'}")
        print("-" * 40)


        data = datatype.Plant(id=plant_id, maturity=maturity, is_disease=is_disease)
        self.queue.put(data)

    def _db_loop(self):
        while self._is_running:
            plant = self.queue.get()

            with self.db.session_scope():
                err = self.db.update_plant([plant])
                if err:
                    print("작물 정보 업데이트 중 오류 발생:", err)

    def run(self):
        self._is_running = True
        self._worker_thread = threading.Thread(target=self.analysis_worker, daemon=True)
        self._worker_thread.start()

        self._db_thread = threading.Thread(target=self._db_loop, daemon=True)
        self._db_thread.start()

        self.mqttc.connect(self.mqtt_host, self.mqtt_port)
        self.mqttc.loop_start()

    def stop(self):
        self.mqttc.loop_stop()
        self._is_running = False


if __name__ == "__main__":
    c = Connector()
    c.run()
    try:
        while True: time.sleep(1) # 프로그램이 즉시 종료되지 않게 유지
    except KeyboardInterrupt:
        c.stop()