/*
  Arduino / ESP32 Conveyor Gate Controller
  Nhận tín hiệu từ Python Conveyor Dashboard qua Serial (Baudrate: 9600)
  
  Giao thức:
  - "CMD:GATE_1\n"      -> Kích hoạt Cổng 1 (Táo tươi - Servo 1 mở 90 độ)
  - "CMD:GATE_2\n"      -> Kích hoạt Cổng 2 (Chuối tươi - Servo 2 mở 90 độ)
  - "CMD:GATE_3\n"      -> Kích hoạt Cổng 3 (Cam tươi - Servo 3 mở 90 độ)
  - "CMD:GATE_REJECT\n" -> Kích hoạt Tay gạt quả hỏng (Piston/Relay đẩy ra thùng loại)
*/

#include <Servo.h>

// Định nghĩa chân cắm Servo / Relay
const int PIN_SERVO_1 = 3;       // Cổng 1: Táo tươi
const int PIN_SERVO_2 = 5;       // Cổng 2: Chuối tươi
const int PIN_SERVO_3 = 6;       // Cổng 3: Cam tươi
const int PIN_REJECT_RELAY = 8;  // Tay gạt quả hỏng (Relay/Solenoid)
const int PIN_LED_STATUS = 13;   // Đèn LED báo hiệu

Servo servo1, servo2, servo3;

unsigned long gate1_timer = 0;
unsigned long gate2_timer = 0;
unsigned long gate3_timer = 0;
unsigned long reject_timer = 0;
const unsigned long ACTION_DURATION_MS = 1500; // Giữ cần gạt mở trong 1.5s

void setup() {
  Serial.begin(9600);
  
  servo1.attach(PIN_SERVO_1);
  servo2.attach(PIN_SERVO_2);
  servo3.attach(PIN_SERVO_3);

  // Vị trí mặc định: Đóng cần gạt (0 độ)
  servo1.write(0);
  servo2.write(0);
  servo3.write(0);

  pinMode(PIN_REJECT_RELAY, OUTPUT);
  pinMode(PIN_LED_STATUS, OUTPUT);
  digitalWrite(PIN_REJECT_RELAY, LOW);
  digitalWrite(PIN_LED_STATUS, LOW);

  Serial.println("[MCU] He thong phan loai san sang!");
}

void loop() {
  // 1. Đọc lệnh từ Python qua Serial
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    digitalWrite(PIN_LED_STATUS, HIGH);

    if (cmd == "CMD:GATE_1") {
      servo1.write(90); // Mở cổng 1
      gate1_timer = millis();
      Serial.println("[ACK] Cong 1 da mo (Tao tuoi)");
    } 
    else if (cmd == "CMD:GATE_2") {
      servo2.write(90); // Mở cổng 2
      gate2_timer = millis();
      Serial.println("[ACK] Cong 2 da mo (Chuoi tuoi)");
    } 
    else if (cmd == "CMD:GATE_3") {
      servo3.write(90); // Mở cổng 3
      gate3_timer = millis();
      Serial.println("[ACK] Cong 3 da mo (Cam tuoi)");
    } 
    else if (cmd == "CMD:GATE_REJECT") {
      digitalWrite(PIN_REJECT_RELAY, HIGH); // Kích hoạt xi lanh gạt quả hỏng
      reject_timer = millis();
      Serial.println("[ACK] Da gat qua hong vao thung loai");
    }
  }

  // 2. Tự động đóng cần gạt sau khi hết thời gian ACTION_DURATION_MS
  unsigned long now = millis();

  if (gate1_timer > 0 && (now - gate1_timer >= ACTION_DURATION_MS)) {
    servo1.write(0);
    gate1_timer = 0;
  }

  if (gate2_timer > 0 && (now - gate2_timer >= ACTION_DURATION_MS)) {
    servo2.write(0);
    gate2_timer = 0;
  }

  if (gate3_timer > 0 && (now - gate3_timer >= ACTION_DURATION_MS)) {
    servo3.write(0);
    gate3_timer = 0;
  }

  if (reject_timer > 0 && (now - reject_timer >= ACTION_DURATION_MS)) {
    digitalWrite(PIN_REJECT_RELAY, LOW);
    reject_timer = 0;
  }

  // Tắt đèn LED nếu không có cổng nào đang hoạt động
  if (gate1_timer == 0 && gate2_timer == 0 && gate3_timer == 0 && reject_timer == 0) {
    digitalWrite(PIN_LED_STATUS, LOW);
  }
}
