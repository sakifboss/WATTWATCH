"""Device simulator.

No real hardware, so this plays the role of the office: devices drift
toward a time-of-day occupancy pattern instead of flipping randomly.

  * 9 AM-5 PM  — work rooms busy (~75% on), drawing room light use (~35%)
  * 1-2 PM     — lunch dip
  * 8-9 AM / 5-7 PM — people arriving / stragglers leaving
  * night      — mostly off, but someone occasionally "forgets" a device,
                 which is exactly what feeds the after-hours alert rule

On startup it also:
  * backfills a realistic kWh figure for "today so far" (integrating the
    expected load curve since midnight), so the usage counter never starts
    at a silly 0.001 kWh
  * seeds Work Room 2 as fully ON since 2h15m ago (demo of the 2-hour
    rule) and holds it for 10 minutes so judges can actually see it
"""

import asyncio
import random
from datetime import timedelta

from backend import alerts, config

RECONSIDER_PROB = 0.06  # per device per tick — keeps the office feeling alive
DEMO_HOLD_MINUTES = 10


def target_on_probability(room_key: str, t) -> float:
    """How likely a device in this room *should* be on at this moment."""
    h = t.hour + t.minute / 60.0
    if config.OFFICE_START <= h < config.OFFICE_END:
        base = 0.35 if room_key == "drawing" else 0.75
        if 13 <= h < 14:  # lunch
            base *= 0.6
        return base
    if 8 <= h < 9 or 17 <= h < 19:  # edges of the day
        return 0.30
    return 0.05  # night — the "forgot to switch off" zone


def seed(store) -> None:
    """Give every device a plausible starting state."""
    t = config.now()
    for d in store.devices.values():
        if random.random() < target_on_probability(d["room"], t):
            store.set_state(d["id"], True, t - timedelta(minutes=random.randint(5, 90)))

    if config.SEED_ALERT_DEMO:
        # Work Room 2 "forgotten" fully on since 2h15m ago -> triggers rule 2
        since = (t - timedelta(hours=2, minutes=15)).isoformat(timespec="seconds")
        hold_until = t + timedelta(minutes=DEMO_HOLD_MINUTES)
        for d in store.room_devices("work2"):
            d["on"] = True
            d["on_since"] = since
            d["last_changed"] = since
            store.demo_hold[d["id"]] = hold_until


def backfill_energy(store) -> None:
    """Estimate kWh burned since midnight using the expected load curve."""
    t = config.now()
    cursor = t.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=15)
    room_full_watts = (
        config.FANS_PER_ROOM * config.FAN_WATTS
        + config.LIGHTS_PER_ROOM * config.LIGHT_WATTS
    )
    wh = 0.0
    while cursor < t:
        for room_key in config.ROOMS:
            expected_watts = room_full_watts * target_on_probability(room_key, cursor)
            wh += expected_watts * step.total_seconds() / 3600.0
        cursor += step
    store.energy_wh_today = wh


async def run(store) -> None:
    seed(store)
    backfill_energy(store)
    alerts.check(store)
    await store.publish()

    while True:
        await asyncio.sleep(config.TICK_SECONDS)
        t = config.now()

        for d in store.devices.values():
            hold = store.demo_hold.get(d["id"])
            if hold and t < hold:
                continue  # demo devices stay put for a few minutes
            if random.random() < RECONSIDER_PROB:
                want_on = random.random() < target_on_probability(d["room"], t)
                store.set_state(d["id"], want_on, t)

        store.add_energy(config.TICK_SECONDS)
        alerts.check(store)
        await store.publish()
