"""Central configuration for WattWatch.

NOTE on device count: the problem statement says "2 fans and 3 lights"
per room, which is 5 devices/room = 15 total — but it also says
"6 devices per room, 18 devices total". The two statements contradict
each other (its own layout legend counts 6 fans + 9 lights = 15).
We honor the explicit per-room spec (2 fans + 3 lights) and keep the
counts configurable via env vars, so a one-line change (FANS_PER_ROOM=3)
gives 18 total if the organizers clarify the other way.
"""

import os
from datetime import datetime, timedelta

try:  # .env support is optional at import time
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# ---- office layout -------------------------------------------------------
ROOMS = {
    "drawing": "Drawing Room",
    "work1": "Work Room 1",
    "work2": "Work Room 2",
}

FANS_PER_ROOM = int(os.getenv("FANS_PER_ROOM", "2"))
LIGHTS_PER_ROOM = int(os.getenv("LIGHTS_PER_ROOM", "3"))

FAN_WATTS = 60   # a typical ceiling fan
LIGHT_WATTS = 15  # a typical LED tube/bulb

# ---- office hours (problem statement: 9 AM - 5 PM) -----------------------
OFFICE_START = 9
OFFICE_END = 17

# ---- simulation ----------------------------------------------------------
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "3"))

# Shift the simulated clock, e.g. SIM_CLOCK_OFFSET_HOURS=13 makes the
# system believe it is night time — handy for demoing after-hours alerts.
CLOCK_OFFSET_HOURS = float(os.getenv("SIM_CLOCK_OFFSET_HOURS", "0"))

# Seed one room as "forgotten on for 2h15m" at startup so the alerts
# panel has something to show immediately. Set SEED_ALERT_DEMO=0 to disable.
SEED_ALERT_DEMO = os.getenv("SEED_ALERT_DEMO", "1") == "1"


def now() -> datetime:
    """The office's wall clock (respects the demo offset)."""
    return datetime.now() + timedelta(hours=CLOCK_OFFSET_HOURS)


def is_office_hours(t: datetime | None = None) -> bool:
    t = t or now()
    return OFFICE_START <= t.hour < OFFICE_END


def normalize_room(raw: str) -> str | None:
    """Map user-typed room names ('Work Room 1', 'wr2'...) to a room key."""
    s = raw.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    aliases = {
        "drawing": "drawing",
        "drawingroom": "drawing",
        "waiting": "drawing",
        "work1": "work1",
        "workroom1": "work1",
        "wr1": "work1",
        "work2": "work2",
        "workroom2": "work2",
        "wr2": "work2",
    }
    return aliases.get(s)
