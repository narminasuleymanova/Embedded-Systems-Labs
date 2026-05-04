#include <Servo.h>
#include <Stepper.h>

// ── Pin assignments ──────────────────────────────────────────
const int BTN1_PIN   = 2;
const int BTN2_PIN   = 3;
const int STEP_IN1   = 4;   // ULN2003 IN1
const int STEP_IN2   = 5;   // ULN2003 IN2
const int STEP_IN3   = 6;   // ULN2003 IN3
const int STEP_IN4   = 7;   // ULN2003 IN4
const int BUZZER_PIN = 8;
const int SERVO_PIN  = 9;

// ── Motor constants ──────────────────────────────────────────
const int STEPS_PER_REV  = 2048;  // 28BYJ-48 half-step = 2048 per rev
const int STEPPER_RPM    = 12;    // keep <= 15 for 28BYJ-48
const int STEP_PER_POINT = 256;   // stepper steps per tug-of-war position (~45 deg)
const int SERVO_P1       = 0;     // servo angle declared for P1 wins
const int SERVO_P2       = 180;   // servo angle declared for P2 wins
const int SERVO_NEUTRAL  = 90;

// ── Tug-of-war constants ─────────────────────────────────────
// 7 positions: 0,1,2,3,4,5,6 — start at 3 (centre)
// P1 wins by reaching 0 (left), P2 wins by reaching 6 (right)
const int TOW_START    = 3;
const int TOW_P1_GOAL  = 0;   // P1 wins when position reaches this
const int TOW_P2_GOAL  = 6;   // P2 wins when position reaches this

// ── Buzzer tone frequencies (Hz) ─────────────────────────────
const int TICK_FREQ      = 880;   // A5 — countdown tick
const int BUZZ_FREQ      = 1400;  // main buzzer "GO!" tone
const int PENALTY_FREQ   = 330;   // E4 — low penalty beep

// ── Objects ──────────────────────────────────────────────────
Servo   servo;
// Pin order for 28BYJ-48 via ULN2003: IN1, IN3, IN2, IN4
// This gives the correct half-step firing sequence
Stepper stepper(STEPS_PER_REV, STEP_IN1, STEP_IN3, STEP_IN2, STEP_IN4);

// ── Game state variables ─────────────────────────────────────
bool          handshakeDone  = false;
bool          roundActive    = false;
bool          buzzFired      = false;
bool          p1Pressed      = false;
bool          p2Pressed      = false;
unsigned long buzzTime       = 0;
unsigned long p1Time         = 0;
unsigned long p2Time         = 0;
int           stepperPos     = 0;  // cumulative stepper steps from centre (for motor tracking)
int           towPos         = TOW_START;  // tug-of-war logical position (0–6)

// ── Non-blocking countdown state (FIX #3) ────────────────────
bool          inCountdown    = false;
int           countdownTotal = 0;
int           countdownLeft  = 0;
unsigned long countdownStart = 0;
bool          tickPlayed     = false;

const unsigned long REACTION_TIMEOUT = 5000; // ms to wait after buzz

// ── Debounce to avoid electrical noise false triggers ────────
const unsigned long DEBOUNCE_MS = 50;
unsigned long lastBtn1Read = 0;
unsigned long lastBtn2Read = 0;

// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  randomSeed(analogRead(A0));

  pinMode(BTN1_PIN,   INPUT);
  pinMode(BTN2_PIN,   INPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  servo.attach(SERVO_PIN);
  servo.write(SERVO_NEUTRAL);
  stepper.setSpeed(STEPPER_RPM);
}

// ─────────────────────────────────────────────────────────────
void loop() {

  // ── Read and dispatch serial commands ────────────────────
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "HELLO") {
      handshakeDone = true;
      Serial.println("ARDUINO_READY");
      return;
    }

    if (!handshakeDone) return;

    if (cmd == "START" && !roundActive) {
      startRound();

    } else if (cmd.startsWith("SPIN:")) {
      int player = cmd.substring(5).toInt();
      doVictorySpin(player);

    } else if (cmd == "RESET") {
      resetAll();
    }
  }

  // ── Active round processing ────────────────────────────────
  if (!roundActive) return;

  // ── PHASE 1: Non-blocking countdown ────────────────────────
  if (inCountdown) {
    unsigned long elapsed = millis() - countdownStart;

    if (!tickPlayed) {
      tone(BUZZER_PIN, TICK_FREQ, 80);
      tickPlayed = true;
    }

    // Check for false starts DURING countdown
    if (buttonPressed(BTN1_PIN, lastBtn1Read)) { handleFalseStart(1); return; }
    if (buttonPressed(BTN2_PIN, lastBtn2Read)) { handleFalseStart(2); return; }

    if (elapsed >= 1000) {
      countdownLeft--;
      if (countdownLeft <= 0) {
        inCountdown = false;
        fireBuzzer();
      } else {
        countdownStart = millis();
        tickPlayed = false;
      }
    }
    return;
  }

  // ── PHASE 2: Post-buzz — record reaction times ────────────
  if (buzzFired) {
    if (!p1Pressed && buttonPressed(BTN1_PIN, lastBtn1Read)) {
      p1Time    = millis() - buzzTime;
      p1Pressed = true;
      Serial.print("P1:");
      Serial.println(p1Time);
    }
    if (!p2Pressed && buttonPressed(BTN2_PIN, lastBtn2Read)) {
      p2Time    = millis() - buzzTime;
      p2Pressed = true;
      Serial.print("P2:");
      Serial.println(p2Time);
    }

    if (p1Pressed && p2Pressed) {
      decideWinner();
      return;
    }

    if (millis() - buzzTime > REACTION_TIMEOUT) {
      roundActive = false;
      if (p1Pressed && !p2Pressed) {
        p2Time = REACTION_TIMEOUT;
        decideWinner();
      } else if (p2Pressed && !p1Pressed) {
        p1Time = REACTION_TIMEOUT;
        decideWinner();
      } else {
        Serial.println("TIMEOUT");
      }
    }
  }
}

// ─────────────────────────────────────────────────────────────
bool buttonPressed(int pin, unsigned long &lastRead) {
  if (digitalRead(pin) == HIGH) {
    unsigned long now = millis();
    if (now - lastRead > DEBOUNCE_MS) {
      lastRead = now;
      return true;
    }
  }
  return false;
}

// ─────────────────────────────────────────────────────────────
void startRound() {
  roundActive  = true;
  buzzFired    = false;
  p1Pressed    = false;
  p2Pressed    = false;
  inCountdown  = true;
  tickPlayed   = false;

  countdownTotal = random(1, 21);
  countdownLeft  = countdownTotal;
  countdownStart = millis();

  Serial.print("COUNTDOWN:");
  Serial.println(countdownTotal);
}

// ─────────────────────────────────────────────────────────────
void fireBuzzer() {
  tone(BUZZER_PIN, BUZZ_FREQ, 600);
  delay(600);
  noTone(BUZZER_PIN);

  buzzTime  = millis();
  buzzFired = true;
  Serial.println("BUZZ");
}

// ─────────────────────────────────────────────────────────────
void handleFalseStart(int player) {
  roundActive = false;
  inCountdown = false;
  noTone(BUZZER_PIN);
  int winner  = (player == 1) ? 2 : 1;

  for (int i = 0; i < 3; i++) {
    tone(BUZZER_PIN, PENALTY_FREQ, 150);
    delay(250);
  }
  noTone(BUZZER_PIN);

  Serial.print("FALSE_START:");
  Serial.println(player);

  // Update tug-of-war position and move motors
  updateTowPosition(winner);
}

// ─────────────────────────────────────────────────────────────
void decideWinner() {
  roundActive = false;
  int winner  = (p1Time <= p2Time) ? 1 : 2;

  // Update tug-of-war position and move motors
  updateTowPosition(winner);
}

// ─────────────────────────────────────────────────────────────
// updateTowPosition: move the tug-of-war marker one step toward
// the winner's side, report position, and check for match win.
// ─────────────────────────────────────────────────────────────
void updateTowPosition(int winner) {
  // Move position: P1 wins → position decreases, P2 wins → position increases
  if (winner == 1) {
    towPos--;
  } else {
    towPos++;
  }

  // Clamp just in case (shouldn't be needed)
  if (towPos < TOW_P1_GOAL) towPos = TOW_P1_GOAL;
  if (towPos > TOW_P2_GOAL) towPos = TOW_P2_GOAL;

  // Move the physical motors
  moveMotors(winner);

  // Report the current tug-of-war position to Python
  Serial.print("POS:");
  Serial.println(towPos);

  // Report the round winner
  Serial.print("WINNER:");
  Serial.println(winner);

  // Check if someone reached their goal (match over)
  if (towPos <= TOW_P1_GOAL) {
    Serial.println("MATCH:1");
  } else if (towPos >= TOW_P2_GOAL) {
    Serial.println("MATCH:2");
  }
}

// ─────────────────────────────────────────────────────────────
// moveMotors: servo snaps to winner's side, stepper drifts
// Detach servo before stepping to avoid Timer1 conflict
// ─────────────────────────────────────────────────────────────
void moveMotors(int winner) {
  servo.write(winner == 1 ? SERVO_P1 : SERVO_P2);
  delay(500);

  servo.detach();
  delay(50);

  int steps = (winner == 1) ? -STEP_PER_POINT : STEP_PER_POINT;
  stepper.step(steps);
  stepperPos += steps;

  servo.attach(SERVO_PIN);
  delay(50);
}

// ─────────────────────────────────────────────────────────────
// doVictorySpin: full 360 spin then return to neutral
// ─────────────────────────────────────────────────────────────
void doVictorySpin(int winner) {
  int dir = (winner == 1) ? -1 : 1;

  servo.detach();
  delay(50);

  stepper.step(dir * STEPS_PER_REV);
  delay(300);
  stepper.step(-stepperPos - (dir * STEPS_PER_REV));
  stepperPos = 0;

  servo.attach(SERVO_PIN);
  delay(50);
  servo.write(SERVO_NEUTRAL);

  // Reset tug-of-war position for next game
  towPos = TOW_START;

  Serial.println("SPIN_DONE");
}

// ─────────────────────────────────────────────────────────────
// resetAll: return everything to neutral position
// ─────────────────────────────────────────────────────────────
void resetAll() {
  servo.detach();
  delay(50);
  stepper.step(-stepperPos);
  stepperPos = 0;
  servo.attach(SERVO_PIN);
  delay(50);
  servo.write(SERVO_NEUTRAL);
  towPos = TOW_START;
}
