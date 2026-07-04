"""Alert engine.

Two rules from the problem statement:
  1. after_hours  — devices still ON outside 9 AM-5 PM
  2. all_on_2h    — every device in a room ON continuously for > 2 hours

Alerts have a lifecycle: they appear in `active_alerts` when the condition
starts (timestamped), and move to `recent_alerts` when it resolves.
"""

from datetime import datetime, timedelta

from backend import config

AFTER_HOURS = "after_hours"
ALL_ON_2H = "all_on_2h"


def check(store) -> None:
    t = config.now()
    current: dict[str, dict] = {}

    for room_key, room_name in config.ROOMS.items():
        devs = store.room_devices(room_key)
        on_devs = [d for d in devs if d["on"]]

        # Rule 1: anything left on after office hours
        if not config.is_office_hours(t) and on_devs:
            fans = sum(1 for d in on_devs if d["type"] == "fan")
            lights = len(on_devs) - fans
            current[f"{AFTER_HOURS}:{room_key}"] = {
                "type": AFTER_HOURS,
                "room": room_key,
                "message": (
                    f"{room_name}: {fans} fan(s) + {lights} light(s) "
                    f"ON after office hours"
                ),
            }

        # Rule 2: whole room burning for > 2 hours straight
        if devs and all(d["on"] for d in devs):
            all_on_since = max(
                datetime.fromisoformat(d["on_since"]) for d in devs
            )
            if t - all_on_since > timedelta(hours=2):
                hours = (t - all_on_since).total_seconds() / 3600
                current[f"{ALL_ON_2H}:{room_key}"] = {
                    "type": ALL_ON_2H,
                    "room": room_key,
                    "message": (
                        f"{room_name}: all {len(devs)} devices ON "
                        f"for {hours:.1f}h straight"
                    ),
                }

    now_iso = t.isoformat(timespec="seconds")

    # new or still-active conditions
    for key, alert in current.items():
        if key not in store.active_alerts:
            alert["id"] = f"{key}@{now_iso}"
            alert["started"] = now_iso
            store.active_alerts[key] = alert
        else:
            # keep the message fresh (e.g. "2.4h straight" keeps counting)
            store.active_alerts[key]["message"] = alert["message"]

    # resolved conditions
    for key in list(store.active_alerts):
        if key not in current:
            resolved = store.active_alerts.pop(key)
            resolved["resolved"] = now_iso
            store.recent_alerts.appendleft(resolved)
