"""WattWatch Discord bot.

Deliberately decoupled from the backend's Python code: it only talks to
the REST API over HTTP, exactly like the dashboard talks to the
WebSocket. One source of truth, two thin clients.

Commands:  !status  !room <name>  !usage  !alerts  !help
Bonus:     polls /api/alerts every 30 s and posts NEW alerts to the
           channel in ALERT_CHANNEL_ID.

Replies are humanized. If ANTHROPIC_API_KEY is set, an LLM rewrites the
facts conversationally (the problem statement strongly encourages this);
otherwise friendly built-in templates are used. Either way the numbers
come straight from the backend — never invented.

Run from the project root:  python -m bot.bot
"""

import os
import random

import discord
import httpx
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

intents = discord.Intents.default()
intents.message_content = True  # must also be enabled in the Dev Portal!
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ---------------------------------------------------------------- backend
async def api(path: str) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{BACKEND}{path}")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- humanizer
SYSTEM_PROMPT = (
    "You are WattWatch, a friendly office-electricity bot on Discord. "
    "Rewrite the given facts as ONE short, warm, human message "
    "(max 3 sentences, at most 1 emoji). Use exactly the numbers given — "
    "never invent or round them differently."
)


async def humanize(facts: str, fallback: str) -> str:
    """LLM-polish the reply if a key is configured; otherwise use templates."""
    if not ANTHROPIC_API_KEY:
        return fallback
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "max_tokens": 300,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": facts}],
                },
            )
            r.raise_for_status()
            blocks = r.json().get("content", [])
            text = "".join(
                b.get("text", "") for b in blocks if b.get("type") == "text"
            ).strip()
            return text or fallback
    except Exception:
        return fallback  # LLM is a nice-to-have, never a point of failure


# ---------------------------------------------------------------- commands
@bot.command()
async def status(ctx):
    """Whole office at a glance."""
    snap = await api("/api/state")
    parts = []
    for key, room in snap["rooms"].items():
        devs = [d for d in snap["devices"] if d["room"] == key]
        fans_on = sum(1 for d in devs if d["type"] == "fan" and d["on"])
        lights_on = sum(1 for d in devs if d["type"] == "light" and d["on"])
        if fans_on == 0 and lights_on == 0:
            parts.append(f"{room['name']}: all off")
        else:
            parts.append(f"{room['name']}: {fans_on} fan(s) + {lights_on} light(s) ON")
    opener = random.choice(["Quick sweep of the floor \U0001F440 — ", "Office right now: ", "Here's how things look: "])
    fallback = opener + ". ".join(parts) + f". Total draw: **{snap['total_watts']}W**."
    facts = "Office status: " + " | ".join(parts) + f" | total draw {snap['total_watts']}W"
    await ctx.send(await humanize(facts, fallback))


@bot.command()
async def room(ctx, *, name: str = ""):
    """Status of one room, e.g. !room work1"""
    if not name:
        await ctx.send("Which room? Try `!room drawing`, `!room work1`, or `!room work2`.")
        return
    try:
        data = await api(f"/api/rooms/{name}")
    except httpx.HTTPStatusError:
        await ctx.send(f"Hmm, I don't know a room called **{name}**. I've got: drawing, work1, work2.")
        return
    listing = ", ".join(f"{d['name']} {'ON' if d['on'] else 'off'}" for d in data["devices"])
    fallback = (
        f"**{data['name']}** — {data['on_count']}/{data['device_count']} devices on, "
        f"pulling **{data['watts']}W**. ({listing})"
    )
    facts = (
        f"{data['name']}: {data['on_count']} of {data['device_count']} devices on, "
        f"drawing {data['watts']}W. Detail: {listing}"
    )
    await ctx.send(await humanize(facts, fallback))


@bot.command()
async def usage(ctx):
    """Current watts + today's estimated kWh."""
    u = await api("/api/usage")
    per_room = ", ".join(f"{r['name']} {r['watts']}W" for r in u["rooms"].values())
    fallback = (
        f"\u26A1 Right now we're burning **{u['total_watts']}W** ({per_room}). "
        f"Today's estimated usage so far: **{u['today_kwh']} kWh**."
    )
    facts = (
        f"Total power right now: {u['total_watts']}W. Per room: {per_room}. "
        f"Today's estimated usage: {u['today_kwh']} kWh."
    )
    await ctx.send(await humanize(facts, fallback))


@bot.command()
async def alerts(ctx):
    """Anything left on that shouldn't be."""
    a = await api("/api/alerts")
    if not a["active"]:
        await ctx.send("All clear \u2705 — nothing left on where it shouldn't be.")
        return
    lines = [f"\u26A0\uFE0F {al['message']} (since {al['started'][11:16]})" for al in a["active"]]
    await ctx.send("\n".join(lines))


@bot.command(name="help")
async def help_cmd(ctx):
    await ctx.send(
        "**WattWatch commands**\n"
        "`!status` — whole office at a glance\n"
        "`!room <name>` — one room (drawing / work1 / work2)\n"
        "`!usage` — current watts + today's kWh\n"
        "`!alerts` — anything left on that shouldn't be"
    )


# ------------------------------------------------- bonus: proactive alerts
seen_alert_ids: set[str] = set()
first_poll = True


@tasks.loop(seconds=30)
async def alert_watch():
    global first_poll
    if not ALERT_CHANNEL_ID:
        return
    try:
        a = await api("/api/alerts")
    except Exception:
        return  # backend briefly down — try again next loop

    if first_poll:
        # don't spam alerts that pre-date the bot coming online
        seen_alert_ids.update(al["id"] for al in a["active"])
        first_poll = False
        return

    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if channel is None:
        return
    for al in a["active"]:
        if al["id"] not in seen_alert_ids:
            seen_alert_ids.add(al["id"])
            await channel.send(
                f"\u26A0\uFE0F Heads up! {al['message']} — since {al['started'][11:16]}. "
                f"Did someone forget to switch off?"
            )


@bot.event
async def on_ready():
    print(f"[bot] logged in as {bot.user} — backend: {BACKEND}")
    if not alert_watch.is_running():
        alert_watch.start()


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN missing. Copy .env.example to .env and fill it in."
        )
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
