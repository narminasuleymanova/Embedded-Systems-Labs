int xPin = A0;
int yPin = A1;

int xVal;
int yVal;

int upLed = 10;
int downLed = 9;
int leftLed = 11;
int rightLed = 6;

void setup() {
  Serial.begin(9600);
  pinMode(xPin, INPUT);
  pinMode(yPin, INPUT);
  pinMode(upLed, OUTPUT);
  pinMode(downLed, OUTPUT);
  pinMode(leftLed, OUTPUT);
  pinMode(rightLed, OUTPUT);
}

void loop() {
  xVal = analogRead(xPin);
  yVal = analogRead(yPin);

  if (yVal <= 510) {
    digitalWrite(upLed, HIGH);
    Serial.println("Direction: UP");
  } else {
    digitalWrite(upLed, LOW);
  }

  if (yVal >= 525) {
    digitalWrite(downLed, HIGH);
    Serial.println("Direction: DOWN");
  } else {
    digitalWrite(downLed, LOW);
  }

  if (xVal <= 505) {
    digitalWrite(leftLed, HIGH);
    Serial.println("Direction: LEFT");
  } else {
    digitalWrite(leftLed, LOW);
  }

  if (xVal >= 515) {
    digitalWrite(rightLed, HIGH);
    Serial.println("Direction: RIGHT");
  } else {
    digitalWrite(rightLed, LOW);
  }

  delay(150);
}