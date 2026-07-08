    #include "DHT.h"
    #include <ThreeWire.h>  // DS1302용 3선 통신 라이브러리
    #include <RtcDS1302.h>  // DS1302 RTC 라이브러리
    #include <string.h>

    #define DHTTYPE DHT11

    // ==========================================
    // ⏰ [시간 설정] 소등 모드 시간 세팅 (분 단위)
    // ==========================================
    // 17시 09분부터 소등 시작
    const int OFF_START_HOUR = 20;  
    const int OFF_START_MIN  = 00;   

    // 05시 59분까지 소등 유지 (06:00부터 보광 시작)
    const int OFF_END_HOUR   = 06;   
    const int OFF_END_MIN    = 00;    
    // ==========================================

    const int dht_pin = 7;        // 온습도 핀

    // ⚠️ 하드웨어 인터럽트 사용을 위해 불꽃감지 핀을 5번에서 2번으로 변경 (아두이노 메가 인터럽트 핀: 2,3,18~21)
    const int fire_pin = 2;       

    // led 핀 (화분 1~4)
    const int led1 = 8;          
    const int led2 = 9;            
    const int led3 = 6;           // 🆕 3번 화분 LED
    const int led4 = 4;           // 🆕 4번 화분 LED

    // 조도값 필터링용 변수
    float filtered_photo1 = 0;
    float filtered_photo2 = 0;
    float filtered_photo3 = 0;    // 🆕 3번 조도
    float filtered_photo4 = 0;    // 🆕 4번 조도

    float lightPercent1 = 0;
    float lightPercent2 = 0;
    float lightPercent3 = 0;
    float lightPercent4 = 0;

    int ledBrightness1 = 0;
    int ledBrightness2 = 0;
    int ledBrightness3 = 0;       // 🆕 3번 LED 밝기
    int ledBrightness4 = 0;       // 🆕 4번 LED 밝기

    // 모터 핀     
    const int INA = 12;          
    const int INB = 13;                

    // 릴레이모듈 핀 (워터펌프)
    const int relayPin = 10;     // 1번 워터펌프
    const int relayPin2 = 11;    // 2번 워터펌프
    bool pump1_state = 1;         // 1번 펌프 상태
    bool pump2_state = 1;        // 2번 펌프 상태
    bool motor_state = 0;

    int led_state = 0;            // 💡 1: 강제 최대 밝기 고정, 0: 자동(빛+타이머) 모드

    // ⚠️ 인터럽트 서비스 루틴(ISR) 내부에서 값이 변경되는 변수이므로 volatile 선언 필수
    volatile int fire_state = 0;  
    bool fire_led_toggle = false;

    // 보광등 역할용 조도값 쓰레쉬홀드값


    // 온습도 센서 관련 변수 선언
    float tem = 0.0;
    float hum = 0.0;
    float hum_revalue = 0.0;

    //예외처리용 온습도 센서값
    float prev_tem = 0.0;
    float prev_hum = 0.0;
    const int D = 0.33;  

    float target_photo1 = 0.54;
    float target_photo2 = 0.54;
    float target_photo3 = 0.54;
    float target_photo4 = 0.54;

    float strawberry_target_soil = 0.6;
    float tomato_target_soil = 0.6;

    float target_hum = 0.65;
    float target_tem = 30;
  
    float target_stop_hum = target_hum - 0.1;
    float target_stop_tem = target_tem - 3;

    const int main_interrupt = 5000;            
    const int fire_interrupt = 1000;             // 화재감지시 led 깜박임 주기
    const unsigned long LOOP_INTERVAL = 200;    
    unsigned long previousMillis = 0;
    unsigned long fire_blink_prevMillis = 0;
    unsigned long prevLoopMillis = 0;

    unsigned long pump1_start_time = 0;
    unsigned long pump2_start_time = 0;
    bool is_pumping1 = false;  
    bool is_pumping2 = false;
    const unsigned long PUMP_RUN_TIME = 2000;   // 2초간 물 주기
    const unsigned long PUMP_COOLDOWN = 180000;  // 3분간 스며들기 대기

    DHT dht(dht_pin, DHTTYPE);

    // DS1302 핀 설정: ThreeWire(DAT, CLK, RST)
    ThreeWire myWire(30, 32, 34);
    RtcDS1302<ThreeWire> Rtc(myWire);

    // ✨ 화재 감지 인터럽트 서비스 루틴 (ISR)
    // 센서 상태가 바뀔 때마다 하드웨어 단에서 즉시 이 함수를 실행하여 fire_state 갱신
    void fireInterrupt() {
      fire_state = digitalRead(fire_pin);
    }

    void setup() {
      pinMode(fire_pin, INPUT);
      
      // ✨ 하드웨어 인터럽트 연결 (2번 핀의 상태가 CHANGE 될 때마다 fireInterrupt 함수 실행)
      attachInterrupt(digitalPinToInterrupt(fire_pin), fireInterrupt, CHANGE);

      pinMode(led1, OUTPUT);
      pinMode(led2, OUTPUT);
      pinMode(led3, OUTPUT); // 🆕
      pinMode(led4, OUTPUT); // 🆕
      pinMode(INA, OUTPUT);
      pinMode(INB, OUTPUT);
      
      pinMode(relayPin, OUTPUT);
      digitalWrite(relayPin, pump1_state);

      pinMode(relayPin2, OUTPUT);
      digitalWrite(relayPin2, pump2_state);

      Serial.begin(9600);
      Serial1.begin(9600);
      dht.begin();

      // RTC 초기화
      Rtc.Begin();
      Rtc.SetIsWriteProtected(false);
      Rtc.SetIsRunning(true);

      RtcDateTime compiled = RtcDateTime(__DATE__, __TIME__);
      
      // ✨ RTC 시간이 깨졌거나, 현재 RTC 시간이 컴파일 시간보다 과거일 때만 업데이트
      if (!Rtc.IsDateTimeValid() || Rtc.GetDateTime() < compiled) {
        Serial.println("RTC 시간을 컴파일 시간으로 업데이트합니다.");
        Rtc.SetDateTime(compiled);
      }

      // 부팅 시 깜박임 방지를 위한 조도 초기값 세팅
      filtered_photo1 = (analogRead(A15) + 100) / 1023.0;  
      filtered_photo2 = analogRead(A14) / 1023.0;  
      filtered_photo3 = analogRead(A13) / 1023.0;   // 🆕 3번 조도
      filtered_photo4 = analogRead(A12) / 1023.0; // 🆕
    }

    void loop() {
      unsigned long currentMillis = millis();

      // ✨ [코드 최적화] 루프 최상단에서 센서 값 1회 읽기
      float photo1 = (analogRead(A15) + 100) / 1023.0;  
      float photo2 = analogRead(A14) / 1023.0;  
      float photo3 = analogRead(A13) / 1023.0;   // 🆕 3번 조도
      float photo4 = analogRead(A12) / 1023.0;    // 🆕 4번 조도
      
      int soil1 = analogRead(A0);      // 1번 토양 수분
      int soil2 = analogRead(A1);     // 2번 토양 수분
      int soil3 = analogRead(A2);     // 🆕 3번 토양 수분
      int soil4 = analogRead(A3);     // 🆕 4번 토양 수분
      
      // (삭제됨) fire_state = digitalRead(fire_pin); <- 인터럽트가 처리하므로 loop 안에서 지속적으로 읽을 필요 없음

      // 토양 수분 측정 및 변환 (건조할수록 값 증가)
      float soil1_revalue = map(soil1, 250, 680, 0, 1000);
      soil1_revalue = constrain(soil1_revalue, 0, 1000) / 1000.0;
      float soil2_revalue = map(soil2, 250, 680, 0, 1000);
      soil2_revalue = constrain(soil2_revalue, 0, 1000) / 1000.0;
      float soil3_revalue = map(soil3, 250, 680, 0, 1000); // 🆕
      soil3_revalue = constrain(soil3_revalue, 0, 1000) / 1000.0;
      float soil4_revalue = map(soil4, 250, 680, 0, 1000); // 🆕
      soil4_revalue = constrain(soil4_revalue, 0, 1000) / 1000.0;

      // RTC 시간 측정
      RtcDateTime now = Rtc.GetDateTime();
      int current_hour = now.Hour();
      int current_min = now.Minute();

      // 1. 블루투스 수동 수신 제어
      if (fire_state == 0 && Serial1.available()) {
        String read_msg = Serial1.readStringUntil('\n');
        read_msg.trim();
        
        // 기존 LED 강제/자동 제어 로직 유지 (엔터 쳤을 때 강제 켜기 등)
        if (read_msg == "") {
          led_state = 1;
        } else if (read_msg == "0") {
          led_state = 0;  
        } 
        // 대시보드 데이터 수신 (ID+TYPE+VALUE)
        else {
          char buffer[30]; 
          read_msg.toCharArray(buffer, sizeof(buffer));

          // '+'를 기준으로 문자열 자르기
          char* id_str = strtok(buffer, "+");
          char* type_str = strtok(NULL, "+");
          char* val1_str = strtok(NULL, "+"); // 기존 값1 (rx_value)
          char* val2_str = strtok(NULL, "+"); // 🆕 값2 (팬모터용 습도값, 없으면 NULL)

          // 필수 토큰 3개가 정상적으로 분리되었을 때만 실행
          if (id_str != NULL && type_str != NULL && val1_str != NULL) {
            int rx_id = atoi(id_str);
            int rx_type = atoi(type_str);
            
            // 기존의 rx_value 대신 값1, 값2로 분리
            float rx_value1 = atof(val1_str); 
            float rx_value2 = 0.0;
            
            // 4번째 값이 들어왔을 때만 변환 (다른 액추에이터는 이 안으로 안 들어옴)
            if (val2_str != NULL) {
              rx_value2 = atof(val2_str);
            }

            // ✨ Type이 0(센서)일 때 수신된 값을 목표값으로 덮어씌움
              if (rx_type == 1) {
                switch (rx_id) {
                  case 1: // 딸기 조도 목표값 변경
                    target_photo1 = constrain(rx_value1, D + 0.01, 1.0);
                    break;

                  case 2: // 딸기 조도 목표값 변경
                    target_photo2 = constrain(rx_value1, D + 0.01, 1.0);
                    break;
                  
                  case 3: // 토마토 조도 목표값 변경
                    target_photo3 = constrain(rx_value1, D + 0.01, 1.0);
                    break;

                  case 4: // 토마토 조도 목표값 변경
                    target_photo4 = constrain(rx_value1, D + 0.01, 1.0);
                    break;

                  case 5: // 토양습도 목표값 변경 (딸기)
                    strawberry_target_soil = constrain(rx_value1, 0.0, 1.0); 
                    break;

                  case 7: // 토양습도 목표값 변경 (토마토)
                    tomato_target_soil = constrain(rx_value1, 0.0, 1.0); 
                    break;

                  case 9: // 🆕 팬모터 온도/습도 목표값 동시 할당
                    // 대시보드 송신 예시: "9+1+25.0+60.0" (ID + Type + 온도 + 습도)
                    target_tem = rx_value1;            // 3번째 토큰(온도)
                    target_stop_tem = target_tem - 3; 

                    // 4번째 토큰(습도)이 같이 날아왔는지 안전 확인 후 할당
                    if (val2_str != NULL) {
                      target_hum = rx_value2;          
                      target_stop_hum = target_hum - 0.1; 
                    }
                    break;
                    
                  // case 10은 팬모터(ID 9)로 통합되었으므로 삭제
                }
              }
            // 만약 Type이 1(모듈)로 들어오는 신호를 추가로 제어하고 싶다면 여기에 else if (rx_type == 1) 블록을 추가하면 됩니다.
          }
        }
      }

      // 2. 화재감지 모드 (최상위 비상 상황)
      if (fire_state == 1) {
        if (currentMillis - fire_blink_prevMillis >= fire_interrupt) {
          fire_blink_prevMillis = currentMillis;
          fire_led_toggle = !fire_led_toggle;
          motor_state = 1;
          digitalWrite(led1, fire_led_toggle);
          digitalWrite(led2, fire_led_toggle);
          digitalWrite(led3, fire_led_toggle); // 🆕 화재 시 모든 LED 깜빡임
          digitalWrite(led4, fire_led_toggle);
          digitalWrite(INA, LOW);
          digitalWrite(INB, LOW);
        }                    
      }

      // 3. 온습도 제어 및 블루투스 데이터 송신 (5초 주기)
      if (currentMillis - previousMillis >= main_interrupt) {
        previousMillis = currentMillis;
        prev_tem = tem;
        prev_hum = hum;
        tem = dht.readTemperature();
        hum = dht.readHumidity();
        hum_revalue = hum / 100;
        if (isnan(tem) || isnan(hum)) {
          tem = prev_tem;
          hum = prev_hum;  
        }

        Serial1.print("1+"); Serial1.print("0+"); Serial1.println(lightPercent1, 2);
        Serial1.print("1+"); Serial1.print("1+"); Serial1.println(ledBrightness1 / 255.0, 2);
        
        Serial1.print("2+"); Serial1.print("0+"); Serial1.println(lightPercent2, 2);
        Serial1.print("2+"); Serial1.print("1+"); Serial1.println(ledBrightness2 / 255.0, 2);
        
        Serial1.print("3+"); Serial1.print("0+"); Serial1.println(lightPercent3, 3);
        Serial1.print("3+"); Serial1.print("1+"); Serial1.println(ledBrightness3 / 255.0, 2);
        
        Serial1.print("4+"); Serial1.print("0+"); Serial1.println(lightPercent4, 4);
        Serial1.print("4+"); Serial1.print("1+"); Serial1.println(ledBrightness4 / 255.0, 2);

        Serial1.print("5+"); Serial1.print("0+"); Serial1.println(soil1_revalue);
        Serial1.print("5+"); Serial1.print("1+"); Serial1.println(pump1_state);

        Serial1.print("6+"); Serial1.print("0+"); Serial1.println(soil2_revalue);

        Serial1.print("7+"); Serial1.print("0+"); Serial1.println(soil3_revalue);
        Serial1.print("7+"); Serial1.print("1+"); Serial1.println(pump2_state);

        Serial1.print("8+"); Serial1.print("0+"); Serial1.println(soil4_revalue);

        Serial1.print("9+"); Serial1.print("0+"); Serial1.println(tem);
        Serial1.print("9+"); Serial1.print("1+"); Serial1.println(motor_state);
        Serial1.print("10+"); Serial1.print("0+"); Serial1.println(hum_revalue);
      
        Serial1.print("11+"); Serial1.print("0+"); Serial1.println(fire_state);
      }

      // 4. 조도 필터링 및 수동/자동 LED 통합 제어 (0.2초 주기)
      if (currentMillis - prevLoopMillis >= LOOP_INTERVAL) {
        prevLoopMillis = currentMillis;

        // 조도 필터링 연산
        filtered_photo1 = (filtered_photo1 * 0.9) + (photo1 * 0.1);
        filtered_photo2 = (filtered_photo2 * 0.9) + (photo2 * 0.1);
        filtered_photo3 = (filtered_photo3 * 0.9) + (photo3 * 0.1); // 🆕
        filtered_photo4 = (filtered_photo4 * 0.9) + (photo4 * 0.1); // 🆕

        float ratio1 = constrain((filtered_photo1 - D) / (target_photo1 - D), 0.0, 1.0);
        float ratio2 = constrain((filtered_photo2 - D) / (target_photo2 - D), 0.0, 1.0);
        float ratio3 = constrain((filtered_photo3 - D) / (target_photo3 - D), 0.0, 1.0);
        float ratio4 = constrain((filtered_photo4 - D) / (target_photo4 - D), 0.0, 1.0);

        ledBrightness1 = 255.0 - (ratio1 * 255.0);
        ledBrightness2 = 255.0 - (ratio2 * 255.0);
        ledBrightness3 = 255.0 - (ratio3 * 255.0);
        ledBrightness4 = 255.0 - (ratio4 * 255.0);

        lightPercent1 = ratio1;
        lightPercent2 = ratio2;
        lightPercent3 = ratio3;
        lightPercent4 = ratio4;

        // ✨ 팬, 펌프, LED 모두 화재가 아닐 때(0)만 정상 작동
        if (fire_state == 0) {
          
          // 🔄 1. 모터(팬) 작동 조건 판별 (습도/온도 기반)
          // 습도 65% 이상 또는 온도 25도 이상일 때 가동
          if (hum_revalue >= target_hum || tem >= target_tem) {
            motor_state = 1;
          } 
          // 습도 60% 이하 및 온도 22도 이하로 모두 떨어졌을 때만 중지
          else if (hum_revalue <= target_stop_hum && tem <= target_stop_tem) {
            motor_state = 0;
          }

          if (motor_state == 1) {
            // 습도 오차 비율 (65~75 구간을 0.0 ~ 1.0으로 매핑)
            float hum_ratio = (hum_revalue - target_hum) / 0.1;
            hum_ratio = constrain(hum_ratio, 0.0, 1.0);

            // 온도 오차 비율 (25~30 구간을 0.0 ~ 1.0으로 매핑)
            float tem_ratio = (tem - target_tem) / 3.0;
            tem_ratio = constrain(tem_ratio, 0.0, 1.0);

            // 둘 중 더 큰 오차 비율을 선택
            float max_ratio = max(hum_ratio, tem_ratio);

            // 속도 계산: 최저 속도 50, 최대 속도 255
            int pwm_speed = 50 + (max_ratio * (255.0 - 50.0));
            pwm_speed = constrain(pwm_speed, 50, 255);

            analogWrite(INA, pwm_speed); // PWM 속도 제어
            digitalWrite(INB, LOW);
          } else {
            digitalWrite(INA, LOW);
            digitalWrite(INB, LOW);
          }

          // 🔄 2-1. 1번 워터펌프 제어 (1번 OR 2번 토양 건조 시)
          if (!is_pumping1) {
            if ((soil1_revalue >= strawberry_target_soil || soil2_revalue >= strawberry_target_soil) && (currentMillis - pump1_start_time >= PUMP_COOLDOWN)) {
              pump1_state = 0; // 물 주기 (ON)
              digitalWrite(relayPin, pump1_state);
              is_pumping1 = true;
              pump1_start_time = currentMillis;
            }
          } else {
            if (currentMillis - pump1_start_time >= PUMP_RUN_TIME) {
              pump1_state = 1; // 멈춤 (OFF)
              digitalWrite(relayPin, pump1_state);
              is_pumping1 = false;
              pump1_start_time = currentMillis;
            }
          }

          // 🔄 2-2. 2번 워터펌프 제어 (3번 OR 4번 토양 건조 시)
          if (!is_pumping2) {
            if ((soil3_revalue >= tomato_target_soil || soil4_revalue >= tomato_target_soil) && (currentMillis - pump2_start_time >= PUMP_COOLDOWN)) {
              pump2_state = 0; // 물 주기 (ON)
              digitalWrite(relayPin2, pump2_state);
              is_pumping2 = true;
              pump2_start_time = currentMillis;
            }
          } else {
            if (currentMillis - pump2_start_time >= PUMP_RUN_TIME) {
              pump2_state = 1; // 멈춤 (OFF)
              digitalWrite(relayPin2, pump2_state);
              is_pumping2 = false;
              pump2_start_time = currentMillis;
            }
          }

          // 3. LED 조명 제어
          if (led_state == 1) {
              analogWrite(led1, 255);
              analogWrite(led2, 255);
              analogWrite(led3, 255); // 🆕
              analogWrite(led4, 255); // 🆕
          } else {
              if (current_hour == 0 && current_min == 0 && !now.IsValid()) {
                  analogWrite(led1, ledBrightness1);  
                  analogWrite(led2, ledBrightness2);
                  analogWrite(led3, ledBrightness3); // 🆕
                  analogWrite(led4, ledBrightness4); // 🆕
              } else {
                bool isNightMode = false;
                // 소등 시간이 날을 넘기는 경우
                if (OFF_START_HOUR > OFF_END_HOUR || (OFF_START_HOUR == OFF_END_HOUR && OFF_START_MIN > OFF_END_MIN)) {
                    if ((current_hour > OFF_START_HOUR) ||
                        (current_hour == OFF_START_HOUR && current_min >= OFF_START_MIN) ||
                        (current_hour < OFF_END_HOUR) ||
                        (current_hour == OFF_END_HOUR && current_min <= OFF_END_MIN)) {
                        isNightMode = true;
                    }
                }
                // 소등 시간이 당일에 끝나는 경우
                else {
                    if ((current_hour > OFF_START_HOUR || (current_hour == OFF_START_HOUR && current_min >= OFF_START_MIN)) &&
                        (current_hour < OFF_END_HOUR || (current_hour == OFF_END_HOUR && current_min <= OFF_END_MIN))) {
                        isNightMode = true;
                    }
                }

                // 판별 결과에 따른 제어
                if (isNightMode) {
                    analogWrite(led1, 0);  
                    analogWrite(led2, 0);
                    analogWrite(led3, 0); // 🆕
                    analogWrite(led4, 0); // 🆕
                } else {
                    analogWrite(led1, ledBrightness1);  
                    analogWrite(led2, ledBrightness2);
                    analogWrite(led3, ledBrightness3); // 🆕
                    analogWrite(led4, ledBrightness4); // 🆕
                }
              }
          }
        }
        // 🔥 화재 발생 시 (안전을 위해 펌프 전원 강제 차단)
        else {
            pump1_state = 1;
            pump2_state = 1;
            digitalWrite(relayPin, pump1_state);
            digitalWrite(relayPin2, pump2_state);
        }

        // 시리얼 모니터 PC 디버깅 출력 (센서가 많아져서 보기 좋게 축약)
        
        Serial.print("[Time: "); if(now.Hour()<10) Serial.print("0"); Serial.print(now.Hour());
        Serial.print(":"); if(now.Minute()<10) Serial.print("0"); Serial.print(now.Minute());
        Serial.print(", Mode:");     Serial.print(led_state == 1 ? "Manual" : "Auto");
        Serial.print(", P1:");       Serial.print(lightPercent1, 2);
        Serial.print(", P2:");       Serial.print(lightPercent2, 2);
        Serial.print(", P3:");       Serial.print(lightPercent3, 2);
        Serial.print(", P4:");       Serial.print(lightPercent4, 2);
        Serial.print(", LED1:");     Serial.print(ledBrightness1 / 255.0, 2);
        Serial.print(", LED2:");     Serial.print(ledBrightness2 / 255.0, 2);
        Serial.print(", LED3:");     Serial.print(ledBrightness3 / 255.0, 2);
        Serial.print(", LED4:");     Serial.print(ledBrightness4 / 255.0, 2);
        Serial.print(", Temp:");     Serial.print(tem, 1);
        Serial.print(", Hum:");      Serial.print(hum_revalue, 1);
        Serial.print(", Motor:");    Serial.print(motor_state);
        Serial.print(", Soil1:");    Serial.print(soil1_revalue);
        Serial.print(", Soil2:");    Serial.print(soil2_revalue);
        Serial.print(", Soil3:");    Serial.print(soil3_revalue);
        Serial.print(", Soil4:");    Serial.print(soil4_revalue);
        Serial.print(", Pump1:");    Serial.print(pump1_state == 0 ? "ON" : "OFF");
        Serial.print(", Pump2:");    Serial.print(pump2_state == 0 ? "ON" : "OFF");
        Serial.println("]");

        Serial.print("목표조도1: ");    Serial.println(target_photo1);
        Serial.print("목표조도2: ");    Serial.println(target_photo2);
        Serial.print("목표조도3: ");    Serial.println(target_photo3);
        Serial.print("목표조도4: ");    Serial.println(target_photo4);

        Serial.print("딸기 목표토양");    Serial.println(strawberry_target_soil);
        Serial.print("토마토 목표토양");    Serial.println(tomato_target_soil);
        Serial.print("목표온도");    Serial.println(target_tem);
        Serial.print("목표습도");    Serial.println(target_hum);

        Serial.print("목표정지온도");    Serial.println(target_stop_tem);
        Serial.print("목표정지습도");    Serial.println(target_stop_hum);
      }
    }
