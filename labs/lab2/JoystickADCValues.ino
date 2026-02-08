int xPin = A0;
int yPin = A1;
int buttonPin = 2;
int xVal;
int yVal;
int buttonState;

void setup() {
  Serial.begin(9600);
  pinMode(xPin, INPUT);
  pinMode(yPin, INPUT);
  pinMode(buttonPin, INPUT_PULLUP);
}

void loop () {
  xVal = analogRead(xPin);
  yVal = analogRead(yPin);
  buttonState = digitalRead(buttonPin);

  Serial.print("X:   ");
  Serial.print(xVal);
  Serial.print("   | Y:   ");
  Serial.print(yVal);
  Serial.print("   | Button:   ");
  Serial.println(buttonState);

  delay(100);
}