#include <Arduino.h>
#include <LiquidCrystal.h>

const int micPin = A0;

const int lcdRs = 12;
const int lcdE  = 11;
const int lcdD4 = 5;
const int lcdD5 = 4;
const int lcdD6 = 3;
const int lcdD7 = 2;
const int alertLed = 8;

LiquidCrystal lcd(lcdRs, lcdE, lcdD4, lcdD5, lcdD6, lcdD7);

const int soundThreshold = 400;

volatile bool  alertTriggered = false;  // set true by ISR when level > threshold
volatile int   isrSoundLevel  = 0;      // most recent raw ADC reading from ISR
volatile uint8_t isrTickCount = 0;      // increments every 10 ms tick

ISR(TIMER1_COMPA_vect) {
  isrSoundLevel = analogRead(micPin);   // read the mic
  isrTickCount++;                        // count ticks for the 100 ms update

  if (isrSoundLevel > soundThreshold) {
    alertTriggered = true;               // flag for loop() to handle the LED
  }
}

const unsigned long ledFlashDuration = 200;  // ms the LED stays on per alert
unsigned long ledOnTime = 0;    // when the LED was last turned on
bool ledFlashing = false;

void setup() {
  Serial.begin(9600);

  pinMode(alertLed, OUTPUT);
  digitalWrite(alertLed, LOW);

  lcd.begin(16, 2);
  lcd.print("Sound Monitor");
  lcd.setCursor(0, 1);
  lcd.print("Initialising...");
  delay(1000);
  lcd.clear();

  noInterrupts();               // disable all interrupts while we configure
  TCCR1A = 0;                   // normal mode
  TCCR1B = 0;
  TCNT1  = 0;                   // reset counter
  OCR1A  = 155;                 // compare match value (see formula above)
  TCCR1B |= (1 << WGM12);      // CTC mode (Clear Timer on Compare match)
  TCCR1B |= (1 << CS12) | (1 << CS10);  // prescaler = 1024
  TIMSK1 |= (1 << OCIE1A);     // enable Timer1 compare interrupt
  interrupts();                 // re-enable interrupts

  Serial.println("STATE=READY");
}

void loop() {

  noInterrupts();
  int   soundLevel = isrSoundLevel;
  uint8_t ticks   = isrTickCount;
  interrupts();

  if (ticks >= 10) {
    noInterrupts();
    isrTickCount = 0;           // reset tick counter inside interrupt guard
    interrupts();

    float soundVolt = soundLevel * 5.0 / 1023.0;

    // ---- LCD Row 0: voltage ----
    lcd.setCursor(0, 0);
    lcd.print("Lvl:");
    lcd.print(soundVolt, 2);
    lcd.print("V       ");      // trailing spaces overwrite old characters

    // ---- LCD Row 1: raw value + status ----
    lcd.setCursor(0, 1);
    lcd.print("Raw:");
    lcd.print(soundLevel);
    lcd.print(soundLevel > soundThreshold ? " LOUD!  " : " OK     ");

    // ---- UART to Python GUI ----
    // Format: level=<raw>,volt=<V>,status=<OK|LOUD>
    Serial.print("level=");
    Serial.print(soundLevel);
    Serial.print(",volt=");
    Serial.print(soundVolt, 2);
    Serial.print(",status=");
    Serial.println(soundLevel > soundThreshold ? "LOUD" : "OK");
  }

  if (alertTriggered) {
    alertTriggered = false;       // clear flag
    digitalWrite(alertLed, HIGH); // turn LED on
    ledOnTime   = millis();       // record the start time
    ledFlashing = true;
  }

  if (ledFlashing && (millis() - ledOnTime >= ledFlashDuration)) {
    digitalWrite(alertLed, LOW);
    ledFlashing = false;
  }

}