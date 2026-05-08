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

class TomatoBestFrameNode(Node):
    def __init__(self):
        super().__init__('tomato_best_frame_node')

        url = DBManager.make_url(database="farm", host="192.168.0.28")
        self.db = DBManager(url)

        # YOLO 모델 로드
        self.model = YOLO('/home/kim/cc_ws/src/my_bot/my_bot/best04291048.pt')

        # 설정 및 상태 관리
        self.analysis_duration = 3.0  # 분석 지속 시간
        self.start_time = None        # 트리거 시점 저장
        self.is_analyzing = False     # 현재 분석 중인지 여부
        self.current_marker_id = 1
        # 데이터 저장 변수
        self.max_objects_count = -1
        self.best_frame_ripeness_list = []
        self.best_frame_has_disease = False

        # [구독 1] 실시간 영상 스트리밍용 (뷰어)

        self.raw_sub = self.create_subscription(
            CompressedImage,
            '/image_raw/compressed',
            self.image_callback,
            10
        )

        # [구독 2] 분석 시작 트리거용 (터틀봇 도착 신호)
        self.trigger_sub = self.create_subscription(
            CompressedImage,
            '/captured_image/compressed',
            self.trigger_callback,
            10
        )

        self.get_logger().info('Tomato Analysis Node Ready. Waiting for Trigger...')

    def trigger_callback(self, msg):
        """/captured_image/compressed 토픽이 오면 호출됩니다."""
        if not self.is_analyzing:
            # 1. frame_id 파싱 (예: 'WP: 1, Marker ID: 4 DONE')
            frame_id_str = msg.header.frame_id

            try:
                # 정규표현식으로 "Marker ID: 숫지" 패턴에서 숫자만 추출
                match = re.search(r'Marker ID:\s*(\d+)', frame_id_str)
                if match:
                    self.current_marker_id = int(match.group(1))
                    self.get_logger().info(f'📍 Detected Marker ID: {self.current_marker_id}')
                else:
                    self.current_marker_id = 1  # 추출 실패 시 기본값
                    self.get_logger().warn(f'Failed to parse Marker ID from: {frame_id_str}')
            except Exception as e:
                self.get_logger().error(f'ID Parsing Error: {e}')
                self.current_marker_id = 1
            self.get_logger().info('🚀 Destination reached! Starting 3s analysis...')
            self.is_analyzing = True
            self.start_time = time.time()
            # 변수 초기화
            self.max_objects_count = -1
            self.best_frame_ripeness_list = []
            self.best_frame_has_disease = False
        else:
            self.get_logger().warn('Already analyzing. Trigger ignored.')

    def image_callback(self, msg):
        try:
            # 1. 공통: 이미지 디코딩
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                return

            # 2. 분석 모드일 때만 YOLO 실행
            if self.is_analyzing:
                elapsed_time = time.time() - self.start_time

                if elapsed_time <= self.analysis_duration:
                    # YOLO 추론 실행
                    results = self.model(frame, stream=True, conf=0.4, verbose=False)

                    current_frame_ripeness = []
                    current_frame_has_disease = False
                    current_objects_count = 0

                    for result in results:
                        boxes = result.boxes
                        current_objects_count = len(boxes)
                        for box in boxes:
                            cls = int(box.cls[0])
                            name = self.model.names[cls]
                            if name == 'disease':
                                current_frame_has_disease = True
                            elif name in ['green', 'half_ripened', 'fully_ripened']:
                                current_frame_ripeness.append(name)

                    # 베스트 프레임 갱신
                    if current_objects_count >= self.max_objects_count:
                        self.max_objects_count = current_objects_count
                        self.best_frame_ripeness_list = current_frame_ripeness
                        self.best_frame_has_disease = current_frame_has_disease

                else:
                    # 3초 경과 시 결과 출력 및 상태 해제
                    self.process_final_result()
                    self.is_analyzing = False
                    self.start_time = None
                    self.get_logger().info('✅ Analysis finished. Waiting for next trigger...')

            #cv2.imshow('Tomato Monitoring', frame)
            #cv2.waitKey(1)

        except Exception as e:
            self.get_logger().error(f'Callback Error: {e}')

    def process_final_result(self):
        """최종 통계 계산 및 출력"""
        if self.max_objects_count <= 0:
            self.get_logger().warn("⚠️ 분석 구간 동안 인식된 토마토가 없습니다.")
            return

        score_map = {'green': 0, 'half_ripened': 0.5, 'fully_ripened': 1}
        scores = [score_map[name] for name in self.best_frame_ripeness_list if name in score_map]

        ripeness_percent = sum(scores) / len(scores) if scores else 0.0
        final_disease = self.best_frame_has_disease

        target_plant = datatype.Plant(
            id=self.current_marker_id,
            maturity=ripeness_percent,
            is_disease=final_disease
        )

        with self.db.session_scope() as session:
            try:
                # 1. 식물 정보 업데이트
                self.db.update_plant([target_plant])
            except Exception as e:
                self.get_logger().error(f"DB 작업 중 오류 발생: {e}")

        self.get_logger().info("==============================================")
        self.get_logger().info(f"📊 [지점 분석 보고서] 완료")
        self.get_logger().info(f"▶ 인식된 최대 열매 수: {self.max_objects_count}개")
        self.get_logger().info(f"▶ 해당 구역 성숙도  : {ripeness_percent:.1f}%")
        self.get_logger().info(f"▶ 병해충 위험 여부  : {'[위험] 탐지됨' if final_disease else '[안전] 없음'}")
        self.get_logger().info("==============================================")

def main(args=None):
    rclpy.init(args=args)
    node = TomatoBestFrameNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()