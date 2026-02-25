#include <Arduino.h>

const int xPin = A0;
const int yPin = A1;

const int upLed = 10;
const int downLed = 9;
const int leftLed = 11;
const int rightLed = 6;

bool running = false;
unsigned long lastSend = 0;
const unsigned long interval = 50;  // 20 Hz sample rate

// Set this based on wiring:
// - false: PIN -> resistor -> LED -> GND (active-HIGH, recommended)
// - true : +5V -> resistor -> LED -> PIN (active-LOW)
const bool LED_ACTIVE_LOW = false;

inline void ledOn(int pin)  { digitalWrite(pin, LED_ACTIVE_LOW ? LOW  : HIGH); }
inline void ledOff(int pin) { digitalWrite(pin, LED_ACTIVE_LOW ? HIGH : LOW ); }

inline void allOff() {
  ledOff(upLed);
  ledOff(downLed);
  ledOff(leftLed);
  ledOff(rightLed);
}

void setup() {
  Serial.begin(9600);

  pinMode(xPin, INPUT);
  pinMode(yPin, INPUT);

  pinMode(upLed, OUTPUT);
  pinMode(downLed, OUTPUT);
  pinMode(leftLed, OUTPUT);
  pinMode(rightLed, OUTPUT);

  // idle = all LEDs off
  allOff();

  Serial.println("SYSTEM READY");
}

void loop() {
  // ---- START / STOP command from GUI ----
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "START") {
      running = true;
      Serial.println("STATE=RUNNING");
    }
    if (cmd == "STOP") {
      running = false;
      allOff();                 // idle must be off
      Serial.println("STATE=STOPPED");
    }
  }

  // ---- IDLE: keep LEDs off, do nothing else ----
  if (!running) {
    allOff();
    return;
  }

  // ---- Sample rate control (20 Hz) ----
  unsigned long now = millis();
  if (now - lastSend < interval) return;
  lastSend = now;

  // ---- Read joystick ----
  int xVal = analogRead(xPin);
  int yVal = analogRead(yPin);

  // Convert to voltage (0–5V)
  float xVolt = xVal * 5.0 / 1023.0;
  float yVolt = yVal * 5.0 / 1023.0;

  // ---- Reset LEDs ----
  allOff();

  // ---- Direction logic exactly as you gave it ----
  String direction = "CENTER";

  if (yVal <= 510) {
    ledOn(upLed);
    direction = "UP";
  }
  else if (yVal >= 525) {
    ledOn(downLed);
    direction = "DOWN";
  }
  else if (xVal <= 505) {
    ledOn(leftLed);
    direction = "LEFT";
  }
  else if (xVal >= 515) {
    ledOn(rightLed);
    direction = "RIGHT";
  }

  // ---- Structured data for GUI ----
  Serial.print("x=");
  Serial.print(xVolt, 2);
  Serial.print(",y=");
  Serial.print(yVolt, 2);
  Serial.print(",dir=");
  Serial.println(direction);
}