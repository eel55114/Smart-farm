#include "DHT.h"
#include <SoftwareSerial.h>

#define DHTTYPE DHT11
#define led_pin 6
#define fire_pin 4

int led_state = 0;
int fire_state = 0;
unsigned long previousMillis = 0;
unsigned long fire_blink_prevMillis = 0;
bool fire_led_toggle = false;
const int main_interrupt = 2000;
const int fire_interrupt = 200;

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

  if (fire_state == 1 ) {
    if (currentMillis - fire_blink_prevMillis >= fire_interrupt) {
      fire_blink_prevMillis = currentMillis;
      fire_led_toggle = !fire_led_toggle;
      digitalWrite(led_pin, fire_led_toggle);
    }                        
  }

  if (currentMillis - previousMillis >= main_interrupt) {
    previousMillis = currentMillis;

    bluetooth.print("3");
    bluetooth.print("+");
    bluetooth.println(String(fire_state));

    if (isnan(tem)) {
    }

    else {
      bluetooth.print("2");
      bluetooth.print("+");
      bluetooth.println(String(tem));
    }

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

    if (fire_state == 0) {
      if (led_state == 0)
      {
        if (photo > 150) {
          digitalWrite(6, 1);
        }
        else {
          digitalWrite(6, 0);
        }
      }
    }
  }
}
