#include <SPI.h>
#include <MFRC522.h>
#include <Keypad.h>
#include <IRremote.h>

// --- Pin definitions ---
#define RFID_SS   10
#define RFID_RST  A1
#define IR_PIN    A0
#define RED_LED   A3
#define GREEN_LED A2

// --- State machine ---
enum State { WAITING, LOCKED, UNLOCKED };
State currentState = WAITING;

// --- Keypad setup (4x4) ---
const byte ROWS = 4;
const byte COLS = 4;
char keys[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};
byte rowPins[ROWS] = {2, 3, 4, 5};
byte colPins[COLS] = {6, 7, 8, 9};
Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

// --- RFID setup ---
MFRC522 rfid(RFID_SS, RFID_RST);

// --- Code storage ---
char storedCode[5] = "";    // the 4-digit code set by keypad
char inputBuffer[5] = "";   // buffer for current input
int inputIndex = 0;

// --- IR code mapping ---
// These are the NEC command bytes for the Elegoo remote:
uint8_t irMap[10] = {
  0x16,  // 0
  0x0C,  // 1
  0x18,  // 2
  0x5E,  // 3
  0x08,  // 4
  0x1C,  // 5
  0x5A,  // 6
  0x42,  // 7
  0x52,  // 8
  0x4A   // 9
};

// --- LED blink timing ---
unsigned long lastBlink = 0;
bool redOn = false;

// Convert IR hex code to digit character, returns '\0' if not found
char irToDigit(uint8_t cmd) {
  for (int i = 0; i < 10; i++) {
    if (cmd == irMap[i]) return '0' + i;
  }
  return '\0';
}

void setup() {
  Serial.begin(9600);
  
  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);

  // Make sure SS pin is high before SPI starts
  pinMode(RFID_SS, OUTPUT);
  digitalWrite(RFID_SS, HIGH);
  
  SPI.begin();
  SPI.setClockDivider(SPI_CLOCK_DIV8);
  rfid.PCD_Init();

  // Self-test: 0x91 or 0x92 = working, 0x00 or 0xFF = not responding
  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print("RC522_VERSION:0x");
  Serial.println(v, HEX);
  
  // Start IR receiver (needed for LOCKED state)
  IrReceiver.begin(IR_PIN, false);
  
  Serial.println("SYSTEM_READY");
  updateLEDs();
}

void loop() {
  switch (currentState) {
    case WAITING:
      handleWaiting();
      break;
    case LOCKED:
      handleLocked();
      break;
    case UNLOCKED:
      handleUnlocked();
      break;
  }
  updateLEDs();
}

// --- WAITING state: blink red, read keypad ---
void handleWaiting() {
  // Blink red LED
  if (millis() - lastBlink > 500) {
    lastBlink = millis();
    redOn = !redOn;
    digitalWrite(RED_LED, redOn ? HIGH : LOW);
  }
  
  char key = keypad.getKey();
  if (key) {
    // Only accept digits 0-9
    if (key >= '0' && key <= '9') {
      inputBuffer[inputIndex] = key;
      inputIndex++;
      Serial.print("KEY:");
      Serial.println(key);
      
      if (inputIndex == 4) {
        // Code complete - store it and lock
        inputBuffer[4] = '\0';
        strcpy(storedCode, inputBuffer);
        inputIndex = 0;
        memset(inputBuffer, 0, sizeof(inputBuffer));

        currentState = LOCKED;

        // Make sure IR receiver is ready for the LOCKED state
        IrReceiver.start();
        IrReceiver.resume();

        Serial.print("LOCKED:");
        Serial.println(storedCode);
      }
    }
    // Press '#' to clear current input
    else if (key == '#') {
      inputIndex = 0;
      memset(inputBuffer, 0, sizeof(inputBuffer));
      Serial.println("CLEAR");
    }
  }
}

// --- LOCKED state: red solid, read IR remote ---
void handleLocked() {
  if (IrReceiver.decode()) {
    // Skip repeat frames
    if (IrReceiver.decodedIRData.flags & IRDATA_FLAGS_IS_REPEAT) {
      IrReceiver.resume();
      return;
    }

    uint8_t cmd = IrReceiver.decodedIRData.command;
    char digit = irToDigit(cmd);

    if (digit != '\0') {
      inputBuffer[inputIndex] = digit;
      inputIndex++;
      Serial.print("IR:");
      Serial.println(digit);

      if (inputIndex == 4) {
        inputBuffer[4] = '\0';

        if (strcmp(inputBuffer, storedCode) == 0) {
          // Correct code - transition to UNLOCKED
          // CRITICAL: stop IR receiver BEFORE using SPI for RFID
          // IR interrupts can corrupt SPI transactions
          IrReceiver.stop();

          currentState = UNLOCKED;

          // Re-initialize RFID since SPI may have been
          // corrupted by IR interrupts during LOCKED state
          rfid.PCD_Init();
          delay(50);  // give RC522 time to stabilize

          Serial.println("UNLOCKED");
        } else {
          Serial.println("WRONG_CODE");
          // Flash red LED to indicate wrong code
          for (int i = 0; i < 3; i++) {
            digitalWrite(RED_LED, LOW);
            delay(150);
            digitalWrite(RED_LED, HIGH);
            delay(150);
          }
        }

        inputIndex = 0;
        memset(inputBuffer, 0, sizeof(inputBuffer));
      }
    }

    IrReceiver.resume();
  }
}

// --- UNLOCKED state: green solid, read RFID ---
void handleUnlocked() {
  // Check for new RFID card
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;
  
  // Build UID string like "A1:B2:C3:D4"
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (i > 0) uid += ":";
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  
  // Send tag data to PC
  Serial.print("TAG:");
  Serial.println(uid);
  
  // Flash green LED to show successful read
  for (int i = 0; i < 3; i++) {
    digitalWrite(GREEN_LED, LOW);
    delay(100); 
    digitalWrite(GREEN_LED, HIGH);
    delay(100);
  }
  
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

// --- Update LED pattern based on state ---
void updateLEDs() {
  switch (currentState) {
    case WAITING:
      // Red blinks (handled in handleWaiting), green off
      digitalWrite(GREEN_LED, LOW);
      break;
    case LOCKED:
      // Red solid, green off
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
      break;
    case UNLOCKED:
      // Red off, green solid
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
      break;
  }
}