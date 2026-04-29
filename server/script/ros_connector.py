import roslibpy
import numpy as np
import cv2
import base64
import threading

# 최신 이미지를 담을 변수와 Lock
image_lock = threading.Lock()
latest_img = None


def compressed_image_callback(message):
    global latest_img
    try:
        # 1. 디코딩만 빠르게 수행
        data = base64.b64decode(message['data'])
        np_arr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if img is not None:
            with image_lock:
                latest_img = img  # 최신 프레임으로 교체 (덮어쓰기)
    except Exception as e:
        print(f"Decoding error: {e}")


client = roslibpy.Ros(host='192.168.0.130', port=9090)
listener = roslibpy.Topic(client, '/usb/image_raw/compressed', 'sensor_msgs/CompressedImage')

# 중요: queue_length를 1로 설정하여 밀린 메시지를 버림
listener.subscribe(compressed_image_callback)
client.run()  # 비동기 실행

try:
    print("Watching for images...")
    while client.is_connected:
        # 2. 메인 스레드에서 화면 갱신
        with image_lock:
            if latest_img is not None:
                cv2.imshow('ROS Bridge Stream', latest_img)
                # 갱신 후 변수를 비우지 않고 유지하면 마지막 프레임이 계속 보임

        if cv2.waitKey(30) & 0xFF == ord('q'):
            break
finally:
    client.terminate()
    cv2.destroyAllWindows()