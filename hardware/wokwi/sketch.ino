// WattWatch — one-room sensing node (representative circuit, Wokwi)
//
// Concept: each device sits behind its wall switch. The ESP32 taps the
// SWITCHED side of the line, so it reads exactly what the device sees:
// line HIGH -> device powered (LED lights up as the "load"), GPIO reads 1.
//
// In real life the same GPIO would sit behind an optocoupler (PC817) or
// an ACS712 current sensor on the mains line — never directly on 220 V.
// See hardware/PINOUT.md for the real-world mapping.
//
// Wokwi has no motor part, so the two fans are represented by red
// indicator LEDs on their switched lines.

const int LIGHT_PINS[3] = {32, 33, 25};
const int FAN_PINS[2]   = {26, 27};

bool lastLight[3] = {false, false, false};
bool lastFan[2]   = {false, false};
unsigned long lastHeartbeat = 0;

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 3; i++) pinMode(LIGHT_PINS[i], INPUT_PULLDOWN);
  for (int i = 0; i < 2; i++) pinMode(FAN_PINS[i], INPUT_PULLDOWN);
  Serial.println("WattWatch room node up. Flip the switches!");
}

void report(bool force) {
  bool l[3], f[2];
  bool changed = false;

  for (int i = 0; i < 3; i++) {
    l[i] = digitalRead(LIGHT_PINS[i]);
    if (l[i] != lastLight[i]) changed = true;
  }
  for (int i = 0; i < 2; i++) {
    f[i] = digitalRead(FAN_PINS[i]);
    if (f[i] != lastFan[i]) changed = true;
  }
  if (!changed && !force) return;

  memcpy(lastLight, l, sizeof(l));
  memcpy(lastFan, f, sizeof(f));

  int watts = 0;
  for (int i = 0; i < 3; i++) watts += l[i] ? 15 : 0;  // LED light ~15 W
  for (int i = 0; i < 2; i++) watts += f[i] ? 60 : 0;  // ceiling fan ~60 W

  // Same JSON shape the backend simulator produces. In a deployment this
  // line becomes an HTTP POST over WiFi to the FastAPI backend.
  Serial.printf(
    "{\"room\":\"work1\",\"lights\":[%d,%d,%d],\"fans\":[%d,%d],\"watts\":%d}\n",
    l[0], l[1], l[2], f[0], f[1], watts);
}

void loop() {
  report(false);                              // instant on any change
  if (millis() - lastHeartbeat > 2000) {      // heartbeat every 2 s
    report(true);
    lastHeartbeat = millis();
  }
  delay(50);
}
