import os

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

BT_ADDR = os.getenv("BT_ADDR")
BT_PORT = os.getenv("BT_PORT")
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = os.getenv("MQTT_PORT")


def on_connect(client, userdata, flags, reason_code, properties):
    print("연결 성공")


def main():
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.on_connect = on_connect
    # mqttc.on_message = on_message

    mqttc.connect("localhost", 1883, 60)

    mqttc.loop_forever()
    mqttc.connect("mqtt.eclipseprojects.io", 1883, 60)


if __name__ == "__main__":
    main()
