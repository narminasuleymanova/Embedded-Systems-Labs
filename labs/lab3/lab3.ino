#include <Wire.h>
#include <RTClib.h>
#include <LedControl.h>

// MAX7219 pins (to IN header of the module)
const int DIN_PIN = 11;
const int CLK_PIN = 13;
const int CS_PIN  = 10;

// IO pins
const int BUTTON_PIN = 2;
const int LED_PIN = 7;

// Game settings
const int TARGET_VALUE = 10;  // number you must react to
const int WINDOW = 500;       // ±500 ms

// Objects
RTC_DS1307 rtc;
LedControl lc(DIN_PIN, CLK_PIN, CS_PIN, 1);

// State variables
int state = 0;         // 0 = idle, 1 = counting, 2 = wait reaction
int counter = 0;
int lastSecond = -1;
unsigned long targetTime = 0;
int lastButton = HIGH;

// 8x8 digit patterns (each byte is one row; 1 bits = LEDs ON)
const byte DIGITS[11][8] = {
  {B00111100,B01100110,B01101110,B01110110,B01100110,B01100110,B00111100,B00000000}, // 0
  {B00011000,B00111000,B00011000,B00011000,B00011000,B00011000,B00111100,B00000000}, // 1
  {B00111100,B01100110,B00000110,B00001100,B00110000,B01100000,B01111110,B00000000}, // 2
  {B00111100,B01100110,B00000110,B00011100,B00000110,B01100110,B00111100,B00000000}, // 3
  {B00001100,B00011100,B00101100,B01001100,B01111110,B00001100,B00001100,B00000000}, // 4
  {B01111110,B01100000,B01111100,B00000110,B00000110,B01100110,B00111100,B00000000}, // 5
  {B00111100,B01100110,B01100000,B01111100,B01100110,B01100110,B00111100,B00000000}, // 6
  {B01111110,B01100110,B00000110,B00001100,B00011000,B00011000,B00011000,B00000000}, // 7
  {B00111100,B01100110,B01100110,B00111100,B01100110,B01100110,B00111100,B00000000}, // 8
  {B00111100,B01100110,B01100110,B00111110,B00000110,B01100110,B00111100,B00000000}, // 9
  {B00000000,B01001111,B01001001,B01001001,B01001001,B01001111,B11100000,B00000000}  // 10
};

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  lc.shutdown(0, false);
  lc.setIntensity(0, 8);
  lc.clearDisplay(0);

  Wire.begin();
  rtc.begin();

  displayNumber(0);
}

void loop() {
  int button = digitalRead(BUTTON_PIN);
  bool pressed = (lastButton == HIGH && button == LOW); // falling-edge detect
  lastButton = button;

  DateTime now = rtc.now();
  int sec = now.second();

  if (state == 0) {
    // IDLE
    if (pressed) {
      counter = 0;
      displayNumber(counter);
      lastSecond = sec;
      state = 1;
    }
  }
  else if (state == 1) {
    // COUNTING (DS1307 seconds)
    if (sec != lastSecond) {
      lastSecond = sec;
      counter++;
      if (counter > 10) counter = 10;

      displayNumber(counter);

      if (counter == TARGET_VALUE) {
        targetTime = millis();  // time when target was displayed
        state = 2;              // wait for reaction
      }
    }
  }
  else if (state == 2) {
    // WAIT_FOR_REACTION
    if (pressed) {
      unsigned long nowMs = millis();
      unsigned long diff = (nowMs >= targetTime) ? (nowMs - targetTime) : (targetTime - nowMs);

      bool success = (diff <= (unsigned long)WINDOW);
      showFeedback(success);

      counter = 0;
      displayNumber(counter);
      state = 0;
    }
  }
}

// Draw a pattern (0–10) on the 8x8 matrix
void drawDigit(int d) {
  lc.clearDisplay(0);
  for (int row = 0; row < 8; row++) {
    lc.setRow(0, row, DIGITS[d][row]);
  }
}

// Show 0–10 on 8x8 matrix
void displayNumber(int value) {
  if (value >= 0 && value <= 10) {
    drawDigit(value);
  }
}

// Simple LED feedback
void showFeedback(bool success) {
  if (success) {
    digitalWrite(LED_PIN, HIGH);
    delay(1000);
    digitalWrite(LED_PIN, LOW);
  } else {
    for (int i = 0; i < 10; i++) {
      digitalWrite(LED_PIN, HIGH);
      delay(120);
      digitalWrite(LED_PIN, LOW);
      delay(120);
    }
  }
}