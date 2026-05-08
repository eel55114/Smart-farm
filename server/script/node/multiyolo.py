import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import numpy as np
from ultralytics import YOLO
import time
from . import datatype
from .manager import DBManager
import re
import threading
from queue import Queue


class TomatoBestFrameNode(Node):
    def __init__(self):
        super().__init__('tomato_best_frame_node')

        # DB 및 모델 초기화
        url = DBManager.make_url(database="farm", host="192.168.0.28")
        self.db = DBManager(url)
        self.model = YOLO('/home/kim/cc_ws/src/my_bot/my_bot/best04291048.pt')

        # 분석 상태 관리 변수
        self.analysis_duration = 3.0
        self.is_analyzing = False
        self.start_time = None
        self.current_marker_id = 1

        # 베스트 결과 저장 변수
        self.max_objects_count = -1
        self.best_frame_ripeness_list = []
        self.best_frame_has_disease = False

        # --- 쓰레딩 및 큐 설정 ---
        # 분석할 프레임을 담는 대기열 (유실 방지를 위해 maxsize 미설정 또는 크게 설정)
        self.image_queue = Queue()
        self.worker_thread = threading.Thread(target=self.analysis_worker, daemon=True)
        self.worker_thread.start()
        # -----------------------

        # 구독 설정
        self.raw_sub = self.create_subscription(
            CompressedImage,
            '/image_raw/compressed',
            self.image_callback,
            10
        )

        self.trigger_sub = self.create_subscription(
            CompressedImage,
            '/captured_image/compressed',
            self.trigger_callback,
            10
        )

        self.get_logger().info('Tomato Analysis Node (Accurate Mode) Ready.')

    def trigger_callback(self, msg):
        """도착 신호를 받으면 분석 모드 활성화"""
        if not self.is_analyzing:
            # Marker ID 파싱
            frame_id_str = msg.header.frame_id
            match = re.search(r'Marker ID:\s*(\d+)', frame_id_str)
            self.current_marker_id = int(match.group(1)) if match else 1

            self.get_logger().info(f'📍 Marker {self.current_marker_id} 도착. 3초간 프레임 수집 시작...')

            # 이전 데이터 초기화
            self.max_objects_count = -1
            self.best_frame_ripeness_list = []
            self.best_frame_has_disease = False

            # 큐 비우기 (이전 구역의 잔여 프레임 제거)
            while not self.image_queue.empty():
                self.image_queue.get()

            self.start_time = time.time()
            self.is_analyzing = True
        else:
            self.get_logger().warn('이미 분석이 진행 중입니다.')

    def image_callback(self, msg):
        """실시간 영상을 큐에 담음 (분석 중일 때만)"""
        if self.is_analyzing:
            try:
                np_arr = np.frombuffer(msg.data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None:
                    # 분석 시간(3초) 내에 들어온 프레임은 모두 큐에 추가
                    if time.time() - self.start_time <= self.analysis_duration:
                        self.image_queue.put(frame)
                    else:
                        # 3초가 지났음을 표시 (worker에게 알림)
                        pass
            except Exception as e:
                self.get_logger().error(f'이미지 수신 에러: {e}')

    def analysis_worker(self):
        """별도 스레드: 큐에 쌓인 모든 프레임을 순차적으로 YOLO 분석"""
        while rclpy.ok():
            if not self.is_analyzing:
                time.sleep(0.1)
                continue

            # 큐에서 프레임 꺼내기
            if not self.image_queue.empty():
                frame = self.image_queue.get()

                # YOLO 추론
                results = self.model(frame, stream=True, conf=0.4, verbose=False)

                for result in results:
                    boxes = result.boxes
                    current_count = len(boxes)

                    # 현재 프레임의 정보 추출
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

            else:
                # 큐가 비어있는데 3초가 지났다면 최종 결과 처리
                if self.start_time and (time.time() - self.start_time > self.analysis_duration + 0.5):
                    # 약간의 여유 시간(+0.5초)을 두어 마지막 프레임까지 처리 보장
                    self.process_final_result()
                    self.is_analyzing = False
                    self.start_time = None
                else:
                    time.sleep(0.01)

    def process_final_result(self):
        """최종 결과 DB 저장 및 로그 출력"""
        if self.max_objects_count <= 0:
            self.get_logger().warn(f"⚠️ Marker {self.current_marker_id}: 인식된 데이터 없음.")
            return

        score_map = {'green': 0, 'half_ripened': 50, 'fully_ripened': 100}
        scores = [score_map[n] for n in self.best_frame_ripeness_list if n in score_map]
        avg_maturity = sum(scores) / len(scores) if scores else 0.0

        target_plant = datatype.Plant(
            id=self.current_marker_id,
            maturity=avg_maturity,
            is_disease=self.best_frame_has_disease
        )

        with self.db.session_scope() as session:
            try:
                self.db.update_plant([target_plant])
            except Exception as e:
                self.get_logger().error(f"DB 저장 에러: {e}")

        self.get_logger().info("----------------------------------------------")
        self.get_logger().info(f"📊 [Marker {self.current_marker_id} 분석 완료]")
        self.get_logger().info(f"▶ 최적 프레임 객체 수: {self.max_objects_count}개")
        self.get_logger().info(f"▶ 평균 성숙도: {avg_maturity:.1f}%")
        self.get_logger().info(f"▶ 병해 여부: {'탐지됨' if self.best_frame_has_disease else '정상'}")
        self.get_logger().info("----------------------------------------------")


def main(args=None):
    rclpy.init(args=args)
    node = TomatoBestFrameNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()