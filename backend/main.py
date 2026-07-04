"""WattWatch backend — FastAPI.

One process owns everything:
  * the in-memory Store (single source of truth)
  * the simulator loop (background task)
  * REST API   -> consumed by the Discord bot (and anyone with curl)
  * WebSocket  -> pushes a full snapshot to the dashboard on every tick
  * static files -> serves the dashboard itself at /

Run from the project root:  uvicorn backend.main:app --reload
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import config, simulator
from backend.store import STORE

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulator.run(STORE))
    yield
    task.cancel()


app = FastAPI(title="WattWatch backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- REST -----------------------------------------------------------------
@app.get("/api/state")
async def full_state():
    """Everything: devices, per-room totals, energy, alerts."""
    return STORE.snapshot()


@app.get("/api/usage")
async def usage():
    snap = STORE.snapshot()
    return {
        "ts": snap["ts"],
        "total_watts": snap["total_watts"],
        "today_kwh": snap["today_kwh"],
        "rooms": snap["rooms"],
    }


@app.get("/api/rooms/{room}")
async def room_state(room: str):
    key = config.normalize_room(room)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown room '{room}'. Try: drawing, work1, work2",
        )
    devices = STORE.room_devices(key)
    return {
        "key": key,
        "name": config.ROOMS[key],
        "watts": sum(d["watts"] for d in devices if d["on"]),
        "on_count": sum(1 for d in devices if d["on"]),
        "device_count": len(devices),
        "devices": devices,
    }


@app.get("/api/alerts")
async def alerts_state():
    return STORE.snapshot()["alerts"]


# ---- WebSocket (dashboard live feed) ---------------------------------------
@app.websocket("/ws")
async def ws_feed(websocket: WebSocket):
    await websocket.accept()
    queue = STORE.subscribe()
    try:
        await websocket.send_json(STORE.snapshot())  # instant first paint
        while True:
            snap = await queue.get()
            await websocket.send_json(snap)
    except WebSocketDisconnect:
        pass
    finally:
        STORE.unsubscribe(queue)


# ---- dashboard static files (mounted last so /api and /ws win) -------------
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")


if __name__ == "__main__":  # convenience: python -m backend.main
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
