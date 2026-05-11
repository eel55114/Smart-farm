#include "DHT.h"
#include <SoftwareSerial.h>

#define DHTTYPE DHT11
#define led_pin 6
#define fire_pin 4

int led_state = 0;
int fire_state = 0;
unsigned long previousMillis = 0;
const int main_interrupt = 2000;

SoftwareSerial bluetooth(2, 3);
DHT dht(7, DHTTYPE);

void setup() {
  pinMode(led_pin, OUTPUT);
  pinMode(fire_pin, INPUT);
  Serial.begin(9600);
  bluetooth.begin(9600);
  dht.begin();
}

void loop() {
  unsigned long currentMillis = millis();

  fire_state = digitalRead(fire_pin);
  int photo = analogRead(A0);
  float tem = dht.readTemperature();
  float photo2 = photo / 1024.0;

  float hum = dht.readHumidity();

  if (fire_state == 0) {
    if (bluetooth.available()) {
      String read_msg = bluetooth.readStringUntil('\n');
      read_msg.trim();

      if (read_msg == "light_on") {
        led_state = 1;
        digitalWrite(6, led_state);
      }

      else if (read_msg == "light_off") {
        led_state = 0;
        digitalWrite(6, led_state);
      }
    }
  }

  if (currentMillis - previousMillis >= main_interrupt) {
    previousMillis = currentMillis;

    bluetooth.print("3");
    bluetooth.print("+");
    bluetooth.println(String(fire_state));

    // 온도센서 값 블루투스 전송
    if (isnan(tem)) {
    }

    else {
      bluetooth.print("2");
      bluetooth.print("+");
      bluetooth.println(String(tem));
    }


    //습도 센서값 블루투스 전송
    if (isnan(hum)) {
    }

    else {
      bluetooth.print("1");
      bluetooth.print("+");
      bluetooth.println(String(hum));
    }

    if (isnan(photo)) {
      }

    else{
    bluetooth.print("0");
    bluetooth.print("+");
    bluetooth.println(String(photo2));
    }

    if (led_state == 0)
    {
      if (photo > 150) {
        digitalWrite(6, 1);
      }

      else {
        led_state = 0;
        digitalWrite(6, 0);
      }
    }
  }
}
