const uint8_t LED1 = 8;
const uint8_t LED2 = 9;
const uint8_t LED3 = 10;

void setup() {
  pinMode(LED1, OUTPUT);
  pinMode(LED2, OUTPUT);
  pinMode(LED3, OUTPUT);
}

void loop() {
  digitalWrite(LED1, HIGH);
  delay(300);
  digitalWrite(LED1, LOW);

  digitalWrite(LED2, HIGH);
  delay(300);
  digitalWrite(LED2, LOW);
}