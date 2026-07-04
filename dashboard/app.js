/* WattWatch dashboard client.
   One WebSocket -> full snapshot every tick -> targeted DOM updates.
   The DOM is built once from the first snapshot, then only classes and
   text change, so CSS animations (fan spin) never restart mid-frame. */

const $ = (sel) => document.querySelector(sel);

const FAN_IC = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 10.2c.5 0 1 .1 1.4.3.9-1.3 1.5-2.9 1.3-4.3C14.5 4 13.4 3 12 3s-2.5 1-2.7 3.2c-.1 1.4.4 3 1.3 4.3.4-.2.9-.3 1.4-.3zm7.8 4.5c1.4-.2 2.4-1.3 2.4-2.7s-1-2.5-3.2-2.7c-1.4-.1-3 .4-4.3 1.3.3.4.4.9.4 1.4s-.1 1-.3 1.4c1.3.9 2.9 1.4 4.3 1.3h.7zM12 13.8c-.5 0-1-.1-1.4-.3-.9 1.3-1.4 2.9-1.3 4.3.2 2.2 1.3 3.2 2.7 3.2s2.5-1 2.7-3.2c.1-1.4-.4-3-1.3-4.3-.4.2-.9.3-1.4.3zm-4.7-3.5C6 9.4 4.4 8.9 3 9.1.8 9.3-.2 10.4-.2 11.8s1 2.5 3.2 2.7c1.4.1 3-.4 4.3-1.3-.2-.4-.3-.9-.3-1.4s.1-1 .3-1.5z" transform="translate(.7 .2) scale(.95)"/><circle cx="12" cy="12" r="1.6"/></svg>`;
const LIGHT_IC = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V18h6v-1.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2zM9.5 20a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-.5h-5v.5z"/></svg>`;

let ws;
let reconnectDelay = 1000;
let built = false;
const roomMax = {}; // room key -> max possible watts (derived from devices)

/* ---------------- connection ---------------- */
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setStatus(true);
    reconnectDelay = 1000;
  };
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => {
    setStatus(false);
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.7, 8000);
  };
  ws.onerror = () => ws.close();
}

function setStatus(ok) {
  $("#ws-status").classList.toggle("ok", ok);
  $("#ws-status").classList.toggle("bad", !ok);
  $("#ws-label").textContent = ok ? "live" : "reconnecting\u2026";
}

/* ---------------- one-time DOM build ---------------- */
function build(state) {
  const roomsWrap = $("#rooms");
  const barsWrap = $("#room-bars");

  for (const [key, meta] of Object.entries(state.rooms)) {
    const devs = state.devices.filter((d) => d.room === key);
    roomMax[key] = devs.reduce((sum, d) => sum + d.watts, 0);

    // room card with device chips
    const fans = devs.filter((d) => d.type === "fan").length;
    const lights = devs.length - fans;
    const card = document.createElement("section");
    card.className = "room-card";
    card.innerHTML = `
      <header><h3>${meta.name}</h3>
      <span class="room-sub">${fans} fans \u00b7 ${lights} lights</span></header>
      <div class="chips"></div>`;
    const chips = card.querySelector(".chips");
    for (const d of devs) {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.id = `chip-${d.id}`;
      chip.innerHTML = `
        <span class="chip-dot"></span>
        <span class="chip-ic">${d.type === "fan" ? FAN_IC : LIGHT_IC}</span>
        <span class="chip-name">${d.name}</span>
        <span class="chip-watts"></span>`;
      chips.appendChild(chip);
    }
    roomsWrap.appendChild(card);

    // per-room power bar
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span class="bar-name">${meta.name}</span>
      <div class="bar"><i id="bar-${key}"></i></div>
      <span class="bar-watts mono" id="bar-watts-${key}"></span>
      <span class="bar-count" id="bar-count-${key}"></span>`;
    barsWrap.appendChild(row);
  }
}

/* ---------------- per-tick update ---------------- */
function render(state) {
  if (!built) {
    build(state);
    built = true;
  }

  // header
  $("#clock").textContent = state.ts.slice(11, 19);
  const badge = $("#office-badge");
  badge.textContent = state.office_hours ? "office hours" : "after hours";
  badge.classList.toggle("after", !state.office_hours);

  // power
  tween($("#total-watts"), state.total_watts);
  $("#today-kwh").textContent = state.today_kwh.toFixed(2);
  for (const [key, room] of Object.entries(state.rooms)) {
    const pct = roomMax[key] ? Math.round((100 * room.watts) / roomMax[key]) : 0;
    $(`#bar-${key}`).style.width = pct + "%";
    $(`#bar-watts-${key}`).textContent = room.watts + "W";
    $(`#bar-count-${key}`).textContent = `${room.on_count}/${room.device_count} on`;
    const fpw = document.getElementById(`fp-watts-${key}`);
    if (fpw) fpw.textContent = room.watts + "W";
  }

  // devices: chips + floor plan
  for (const d of state.devices) {
    const chip = document.getElementById(`chip-${d.id}`);
    if (chip) {
      chip.classList.toggle("on", d.on);
      chip.querySelector(".chip-watts").textContent = d.on ? d.watts + "W" : "off";
      chip.title = `${d.name} \u00b7 last changed ${d.last_changed.slice(11, 16)}`;
    }
    const fp = document.getElementById(`fp-${d.id}`);
    if (fp) fp.classList.toggle("on", d.on);
  }

  renderAlerts(state.alerts);
}

function renderAlerts(alerts) {
  const list = $("#alerts-list");
  if (!alerts.active.length) {
    list.innerHTML = `<div class="alert-empty">All clear \u2014 nothing left on where it shouldn't be.</div>`;
  } else {
    list.innerHTML = alerts.active
      .map(
        (a) => `
        <div class="alert-item">
          <span class="alert-ic">\u26a0</span>
          <div>
            <div class="alert-msg">${a.message}</div>
            <div class="alert-time mono">since ${a.started.slice(11, 16)}</div>
          </div>
        </div>`
      )
      .join("");
  }
  $("#alerts-recent").innerHTML = alerts.recent
    .slice(0, 3)
    .map((a) => `<div class="alert-resolved">\u2713 resolved ${a.resolved.slice(11, 16)} \u2014 ${a.message}</div>`)
    .join("");
}

/* ---------------- helpers ---------------- */
function tween(el, target) {
  const from = parseInt(el.dataset.v || "0", 10);
  if (from === target) return;
  const t0 = performance.now();
  const DUR = 450;
  function step(t) {
    const k = Math.min(1, (t - t0) / DUR);
    el.textContent = Math.round(from + (target - from) * k);
    if (k < 1) requestAnimationFrame(step);
    else el.dataset.v = target;
  }
  requestAnimationFrame(step);
}

connect();
