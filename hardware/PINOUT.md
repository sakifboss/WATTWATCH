# Hardware concept — WattWatch room node

This folder contains a **representative circuit for one room** (Work Room 1),
as the problem statement allows. The same node design repeats for the other
two rooms.

## The idea

Every light and fan in the office sits behind its own wall switch. The ESP32
taps the **switched side** of each line, so it reads exactly what the device
sees: line HIGH means the device is powered. In the Wokwi simulation the
"device" is an LED (Wokwi has no ceiling-fan part, so the two fans are red
indicator LEDs on their switched lines).

```
3V3 ──► wall switch ──┬──► 220 Ω ──► LED (the load) ──► GND
                      └──► ESP32 GPIO (INPUT_PULLDOWN)
```

Flip a switch: the LED lights up **and** the GPIO reads 1 — one wire, two
jobs, which is why the schematic is physically sensible rather than an LED
decoratively tied to a pin.

## Pin map

| Device  | ESP32 pin | GPIO | Wokwi part        |
|---------|-----------|------|-------------------|
| Light 1 | D32       | 32   | yellow LED        |
| Light 2 | D33       | 33   | yellow LED        |
| Light 3 | D25       | 25   | yellow LED        |
| Fan 1   | D26       | 26   | red LED (fan)     |
| Fan 2   | D27       | 27   | red LED (fan)     |

All five inputs use `INPUT_PULLDOWN`, so an open switch reads a clean LOW
without external pull resistors. Pins 32/33/25/26/27 were chosen because
they are plain input-capable GPIOs with internal pulls (unlike GPIO 34-39,
which have no internal pull resistors).

## Try it in Wokwi

1. Go to wokwi.com → **New Project** → *ESP32*.
2. Open the `diagram.json` tab and replace its content with the
   `diagram.json` from this folder.
3. Replace the sketch with `sketch.ino`.
4. Press play, flip the slide switches, and watch the serial monitor print
   the same JSON shape the backend simulator produces:

```json
{"room":"work1","lights":[1,0,1],"fans":[1,0],"watts":90}
```

In a real deployment that line becomes an HTTP POST over WiFi to the
FastAPI backend (a future `/api/ingest` endpoint) — the rest of the system
would not change at all, which is the point of the layered architecture.

## How this maps to a real 220 V office

You never hang an ESP32 GPIO on mains. The 3V3 line in the simulation
stands in for the sensing side of one of these:

* **Optocoupler (e.g. PC817) + rectifier/divider** across each device's
  switched line — the isolated transistor side feeds the GPIO. Cheapest way
  to answer "is it on?".
* **ACS712 / SCT-013 current sensor** on the device's live wire — gives an
  analog signal proportional to current, so you can measure *actual* watts
  instead of assuming 60 W / 15 W.
* **Smart relay modules** (Sonoff-style) if the boss later wants to switch
  devices off remotely, not just watch them.

The 220 Ω resistor plays the role of the load's current limiting in the
LED stand-in; the fan/light wattages (60 W / 15 W) are configured in
`backend/config.py` and used consistently by the simulator, dashboard,
and bot.
