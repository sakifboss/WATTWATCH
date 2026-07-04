"""In-memory device store — the single source of truth.

Both the web dashboard (via WebSocket) and the Discord bot (via REST)
read from this one object, so they can never disagree.
"""

import asyncio
from collections import deque
from datetime import datetime

from backend import config


class Store:
    def __init__(self) -> None:
        self.devices: dict[str, dict] = {}
        self.energy_wh_today: float = 0.0
        self.energy_date = config.now().date()

        self.active_alerts: dict[str, dict] = {}   # alert key -> alert
        self.recent_alerts: deque = deque(maxlen=20)  # resolved alerts

        # device_id -> datetime; the simulator won't touch these devices
        # until the hold expires (used to keep the demo alert visible).
        self.demo_hold: dict[str, datetime] = {}

        self._subscribers: set[asyncio.Queue] = set()
        self._build_devices()

    # ---- devices ---------------------------------------------------------
    def _build_devices(self) -> None:
        for room_key in config.ROOMS:
            for i in range(1, config.FANS_PER_ROOM + 1):
                self._add(room_key, "fan", i, config.FAN_WATTS)
            for i in range(1, config.LIGHTS_PER_ROOM + 1):
                self._add(room_key, "light", i, config.LIGHT_WATTS)

    def _add(self, room: str, dtype: str, idx: int, watts: int) -> None:
        device_id = f"{room}-{dtype}-{idx}"
        ts = config.now().isoformat(timespec="seconds")
        self.devices[device_id] = {
            "id": device_id,
            "room": room,
            "type": dtype,
            "name": f"{'Fan' if dtype == 'fan' else 'Light'} {idx}",
            "watts": watts,
            "on": False,
            "last_changed": ts,
            "on_since": None,
        }

    def set_state(self, device_id: str, on: bool, ts: datetime | None = None) -> bool:
        """Flip a device. Returns True if the state actually changed."""
        d = self.devices[device_id]
        if d["on"] == on:
            return False
        stamp = (ts or config.now()).isoformat(timespec="seconds")
        d["on"] = on
        d["last_changed"] = stamp
        d["on_since"] = stamp if on else None
        return True

    def room_devices(self, room_key: str) -> list[dict]:
        return [d for d in self.devices.values() if d["room"] == room_key]

    # ---- aggregates ------------------------------------------------------
    def totals(self) -> tuple[int, dict]:
        per_room: dict[str, dict] = {}
        total = 0
        for key, name in config.ROOMS.items():
            devs = self.room_devices(key)
            watts = sum(d["watts"] for d in devs if d["on"])
            per_room[key] = {
                "name": name,
                "watts": watts,
                "on_count": sum(1 for d in devs if d["on"]),
                "device_count": len(devs),
            }
            total += watts
        return total, per_room

    def add_energy(self, dt_seconds: float) -> None:
        """Integrate power draw into today's kWh counter."""
        today = config.now().date()
        if today != self.energy_date:  # midnight rollover
            self.energy_date = today
            self.energy_wh_today = 0.0
        total, _ = self.totals()
        self.energy_wh_today += total * dt_seconds / 3600.0

    # ---- snapshot (what every interface consumes) --------------------------
    def snapshot(self) -> dict:
        t = config.now()
        total, per_room = self.totals()
        return {
            "ts": t.isoformat(timespec="seconds"),
            "office_hours": config.is_office_hours(t),
            "devices": sorted(
                self.devices.values(),
                key=lambda d: (d["room"], d["type"], d["name"]),
            ),
            "rooms": per_room,
            "total_watts": total,
            "today_kwh": round(self.energy_wh_today / 1000.0, 3),
            "alerts": {
                "active": sorted(
                    self.active_alerts.values(),
                    key=lambda a: a["started"],
                    reverse=True,
                ),
                "recent": list(self.recent_alerts),
            },
        }

    # ---- pub/sub for WebSocket push ---------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self) -> None:
        snap = self.snapshot()
        for q in list(self._subscribers):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                # slow client — drop its oldest frame, push the newest
                try:
                    q.get_nowait()
                    q.put_nowait(snap)
                except Exception:
                    pass


STORE = Store()
