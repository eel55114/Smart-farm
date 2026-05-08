import socket
import time
import requests
from db_manager.manager import DBManager
from db_manager import datatype
from dotenv import load_dotenv
load_dotenv()
import os

PORT = 1
BD_ADDR = "98:DA:60:0C:E7:DC"

def main():

    # 블루투스 RFCOMM 소켓 생성
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)

    print(f"{BD_ADDR}에 연결 시도 중...")
    conn_url = os.getenv('DATABASE_URL')
    db = DBManager(conn_url)
    try:
        sock.connect((BD_ADDR, PORT))
        print("연결 성공")

        sock.settimeout(0.5)  # 블로킹 방지를 위한 타임아웃 설정
        buffer = ""

        while True:
            try:
                # 데이터 수신
                data = sock.recv(1024).decode("utf-8")
                if data:
                    buffer += data
                    if "\n" in buffer:
                        lines = buffer.split("\n")
                        for line in lines[:-1]:
                            msg = line.rstrip()
                            print(msg)
                            sensor_id, *values = msg.split("+")

                            try:
                                sensor_id = int(sensor_id)
                                value = float(values[0])

                            except Exception as e:
                                print(e)
                                continue

                            try:
                                sensor_data = datatype.Sensor(sensor_id, value)
                                err = db.update_sensor_data([sensor_data])

                                if err is not None:
                                    print(err)
                            except Exception as e:
                                print(e)
                                continue

                        buffer = lines[-1]
            except socket.timeout:
                pass
            except Exception as e:
                print(f"통신 중 오류 발생: {e}")
                break

            time.sleep(0.1)

    except Exception as e:
        print(f"연결 실패: {e}")
    finally:
        sock.close()
        print("소켓 종료됨")
        db.session_local.remove()
        print("DB 연결 종료")


if __name__ == "__main__":
    main()
