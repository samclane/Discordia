// World map client. The server sends the static map as one PNG plus a JSON description of it;
// actors arrive as a small JSON list every couple of seconds and are drawn as sprites on top.
// No build step: this is loaded as a plain script.

const $ = (id) => document.getElementById(id);
const viewport = $("viewport");
const stage = $("stage");
const bg = $("bg");
const actorLayer = $("actors");
const pick = $("pick");
const cursor = $("cursor");
const info = $("info");
const search = $("search");

let world = null;
let tile = 16;
const structures = new Map(); // "x,y" -> town/wilds record
const actorEls = new Map(); // actor id -> element
let actors = [];
let selected = null; // { actor: id } or { x, y }
let follow = false;

const view = { x: 0, y: 0, scale: 1 };

// Names come from Discord, so nothing goes into innerHTML unescaped.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function applyView() {
  stage.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  stage.style.setProperty("--inv", 1 / view.scale);
  document.body.classList.toggle("far", view.scale * tile < 14);
}

async function loadWorld() {
  world = await (await fetch("/world.json")).json();
  tile = world.tile;
  document.title = world.name;
  $("world-name").textContent = world.name;
  document.documentElement.style.setProperty("--tile", tile + "px");
  stage.style.width = world.width * tile + "px";
  stage.style.height = world.height * tile + "px";
  for (const t of world.towns) structures.set(`${t.x},${t.y}`, { kind: "Town", ...t });
  for (const w of world.wilds) structures.set(`${w.x},${w.y}`, { kind: "Wilds", ...w });
  // Wilds are hundreds of tiles; labelling them buries the map. Hover and click still name them.
  for (const s of world.towns) {
    const el = document.createElement("div");
    el.className = "label";
    el.textContent = s.name;
    el.style.left = (s.x + 0.5) * tile + "px";
    el.style.top = s.y * tile + "px";
    $("labels").appendChild(el);
  }
  bg.src = "/background.png";
  fitToViewport();
  renderTowns();
}

function fitToViewport() {
  const r = viewport.getBoundingClientRect();
  view.scale = Math.min(r.width / (world.width * tile), r.height / (world.height * tile));
  view.x = (r.width - world.width * tile * view.scale) / 2;
  view.y = (r.height - world.height * tile * view.scale) / 2;
  applyView();
}

let anim = 0;
function flyTo(x, y, scale = view.scale) {
  const r = viewport.getBoundingClientRect();
  const from = { ...view };
  const to = {
    scale,
    x: r.width / 2 - (x + 0.5) * tile * scale,
    y: r.height / 2 - (y + 0.5) * tile * scale,
  };
  const start = performance.now();
  cancelAnimationFrame(anim);
  const step = (now) => {
    const t = Math.min(1, (now - start) / 350);
    const e = t * (2 - t);
    for (const k of ["x", "y", "scale"]) view[k] = from[k] + (to[k] - from[k]) * e;
    applyView();
    if (t < 1) anim = requestAnimationFrame(step);
  };
  anim = requestAnimationFrame(step);
}

function zoomAt(cx, cy, factor) {
  cancelAnimationFrame(anim);
  const next = Math.min(8, Math.max(0.2, view.scale * factor));
  // Keep whatever is under the cursor under the cursor.
  const k = next / view.scale;
  view.x = cx - k * (cx - view.x);
  view.y = cy - k * (cy - view.y);
  view.scale = next;
  applyView();
}

function zoomCenter(factor) {
  const r = viewport.getBoundingClientRect();
  zoomAt(r.width / 2, r.height / 2, factor);
}

function tileAt(clientX, clientY) {
  const r = viewport.getBoundingClientRect();
  const size = tile * view.scale;
  const x = Math.floor((clientX - r.left - view.x) / size);
  const y = Math.floor((clientY - r.top - view.y) / size);
  return world && x >= 0 && y >= 0 && x < world.width && y < world.height ? { x, y } : null;
}

const place = (el, x, y) => (el.style.transform = `translate(${x * tile}px, ${y * tile}px)`);

// --- actors ---------------------------------------------------------------

async function pollActors() {
  try {
    actors = (await (await fetch("/actors.json", { cache: "no-store" })).json()).actors;
    $("status").className = "live";
    $("status").title = "Live";
    renderActors();
  } catch (err) {
    // Server restarting or mid-save: just try again on the next tick.
    $("status").className = "down";
    $("status").title = "Reconnecting";
  }
  setTimeout(pollActors, 2000);
}

function hpBar(a) {
  const pct = a.hp_max ? Math.round((100 * a.hp) / a.hp_max) : 0;
  return `<div class="bar${pct <= 30 ? " low" : ""}"><i style="width:${pct}%"></i></div>`;
}

function renderActors() {
  const seen = new Set();
  for (const a of actors) {
    seen.add(a.id);
    let el = actorEls.get(a.id);
    if (!el) {
      el = document.createElement("div");
      el.innerHTML = `<div class="tag"><span class="name"></span><div class="bar"><i></i></div></div><img alt="">`;
      el.querySelector("img").src = a.sprite;
      el.querySelector(".name").textContent = a.name;
      actorLayer.appendChild(el);
      actorEls.set(a.id, el);
    }
    // Position by transform, not left/top: that's what makes the CSS transition slide.
    place(el, a.x, a.y);
    const pct = a.hp_max ? (100 * a.hp) / a.hp_max : 0;
    el.querySelector(".bar i").style.width = pct + "%";
    el.querySelector(".bar").classList.toggle("low", pct <= 30);
    el.className = `actor ${a.kind}${a.hp >= a.hp_max ? " full" : ""}${selected?.actor === a.id ? " selected" : ""}`;
  }
  for (const [id, el] of actorEls) {
    if (!seen.has(id)) {
      el.remove();
      actorEls.delete(id);
    }
  }

  const followed = selected?.actor && actors.find((a) => a.id === selected.actor);
  if (followed && follow) flyTo(followed.x, followed.y);
  const npcs = actors.filter((a) => a.kind === "npc").length;
  $("meta").textContent =
    `Seed ${world.seed} · ${world.width}×${world.height} · ` +
    `${actors.length - npcs} player${actors.length - npcs === 1 ? "" : "s"} · ${npcs} NPC${npcs === 1 ? "" : "s"}`;
  renderPlayers();
  renderInfo();
}

// --- sidebar --------------------------------------------------------------

const matches = (name) => name.toLowerCase().includes(search.value.trim().toLowerCase());

function row(sprite, title, sub, extra, isSelected, onClick) {
  const b = document.createElement("button");
  b.className = "row" + (isSelected ? " selected" : "");
  b.innerHTML =
    `<img src="${esc(sprite)}" alt=""><div class="main"><div class="title">${esc(title)}</div>` +
    `<div class="sub">${esc(sub)}</div></div>${extra}`;
  b.onclick = () => {
    document.body.classList.remove("open"); // phones: get the drawer out of the way of what was picked
    onClick();
  };
  return b;
}

function fill(container, rows, emptyText) {
  container.replaceChildren(...rows);
  if (!rows.length) container.innerHTML = `<div class="empty">${esc(emptyText)}</div>`;
}

function renderPlayers() {
  const players = actors
    .filter((a) => a.kind === "player" && matches(a.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  fill(
    $("players"),
    players.map((p) =>
      row(p.sprite, p.name, `Lv ${p.level} ${p.class} · (${p.x}, ${p.y})`, hpBar(p), selected?.actor === p.id, () =>
        selectActor(p.id, true)
      )
    ),
    search.value ? "No match." : "No one is out there yet."
  );
}

function renderTowns() {
  const towns = world.towns.filter((t) => matches(t.name)).sort((a, b) => a.name.localeCompare(b.name));
  fill(
    $("towns"),
    towns.map((t) =>
      row(t.sprite, t.name, `Pop. ${t.population} · ${t.industry}`, "", selected?.x === t.x && selected?.y === t.y, () =>
        selectTile(t.x, t.y, true)
      )
    ),
    "No match."
  );
}

function selectActor(id, fly) {
  selected = { actor: id };
  follow = fly;
  pick.style.display = "none";
  renderActors();
  renderTowns();
  const a = actors.find((a) => a.id === id);
  if (fly && a) flyTo(a.x, a.y, Math.max(view.scale, 2));
}

function stopFollow() {
  cancelAnimationFrame(anim);
  if (follow) {
    follow = false;
    renderInfo();
  }
}

function selectTile(x, y, fly) {
  selected = { x, y };
  follow = false;
  pick.style.display = "block";
  place(pick, x, y);
  if (fly) flyTo(x, y, Math.max(view.scale, 2));
  renderActors();
  renderTowns();
}

function clearSelection() {
  selected = null;
  follow = false;
  pick.style.display = "none";
  renderActors();
  renderTowns();
}

function describeActor(a) {
  const what = a.kind === "player" ? `Level ${a.level} ${esc(a.class)}` : "NPC";
  return `<b>${esc(a.name)}</b> <span class="dim">&mdash; ${what}</span><br>${a.hp}/${a.hp_max} hp`;
}

function renderInfo() {
  if (!world) return;
  if (!selected) {
    info.innerHTML = `<span class="dim">Click a tile or a name. Arrows pan, +/- zoom, F fits, / searches.</span>`;
    return;
  }
  let x, y;
  const lines = [];
  if (selected.actor) {
    const a = actors.find((a) => a.id === selected.actor);
    if (!a) {
      info.innerHTML = `<span class="dim">Gone from the map.</span>`;
      return;
    }
    ({ x, y } = a);
    lines.push(describeActor(a));
    if (follow) lines.push(`<span class="dim">Following &middot; drag to stop</span>`);
  } else {
    ({ x, y } = selected);
    for (const a of actors) if (a.x === x && a.y === y) lines.push(describeActor(a));
  }
  const here = structures.get(`${x},${y}`);
  if (here) {
    lines.unshift(
      here.kind === "Town"
        ? `<b>${esc(here.name)}</b> <span class="dim">&mdash; town, pop. ${here.population}, ${esc(here.industry)}</span>`
        : `<b>${esc(here.name)}</b> <span class="dim">&mdash; wilds</span>`
    );
  }
  lines.push(`<span class="dim">(${x}, ${y}) &middot; ${esc(world.terrain[y][x])}</span>`);
  info.innerHTML = lines.join("<br>");
}

search.addEventListener("input", () => {
  renderPlayers();
  renderTowns();
});
search.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    $("lists").querySelector(".row")?.click();
    search.blur(); // hand the keys back to the map
  }
  if (e.key === "Escape") search.blur();
});

// --- pan, zoom, inspect ---------------------------------------------------

const pointers = new Map(); // pointerId -> {x, y}
let drag = null;

viewport.addEventListener("pointerdown", (e) => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  drag = { moved: pointers.size > 1 ? Infinity : 0 }; // a pinch is never a click
  viewport.setPointerCapture(e.pointerId);
  viewport.classList.add("dragging");
});

viewport.addEventListener("pointermove", (e) => {
  const hit = tileAt(e.clientX, e.clientY);
  cursor.style.display = hit ? "block" : "none";
  if (hit) {
    place(cursor, hit.x, hit.y);
    const s = structures.get(`${hit.x},${hit.y}`);
    $("hover").textContent = `(${hit.x}, ${hit.y}) ${world.terrain[hit.y][hit.x]}${s ? " · " + s.name : ""}`;
  }

  const prev = pointers.get(e.pointerId);
  if (!prev || !drag) return;
  if (pointers.size === 2) {
    const other = [...pointers].find(([id]) => id !== e.pointerId)[1];
    const before = Math.hypot(prev.x - other.x, prev.y - other.y);
    const after = Math.hypot(e.clientX - other.x, e.clientY - other.y);
    const r = viewport.getBoundingClientRect();
    if (before > 0) zoomAt((e.clientX + other.x) / 2 - r.left, (e.clientY + other.y) / 2 - r.top, after / before);
  }
  // Two fingers pan by half each, so the midpoint tracks.
  const share = 1 / pointers.size;
  const dx = (e.clientX - prev.x) * share;
  const dy = (e.clientY - prev.y) * share;
  if (dx || dy) stopFollow();
  view.x += dx;
  view.y += dy;
  drag.moved += Math.abs(dx) + Math.abs(dy);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  applyView();
});

function endPointer(e) {
  pointers.delete(e.pointerId);
  if (!pointers.size) {
    if (drag && drag.moved < 4 && e.type === "pointerup") inspect(e); // a click, not the end of a drag
    drag = null;
    viewport.classList.remove("dragging");
  }
}
viewport.addEventListener("pointerup", endPointer);
viewport.addEventListener("pointercancel", endPointer);
viewport.addEventListener("pointerleave", () => {
  cursor.style.display = "none";
  $("hover").textContent = "";
});

viewport.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY / 400));
  },
  { passive: false }
);

function inspect(e) {
  const hit = tileAt(e.clientX, e.clientY);
  if (!hit) return clearSelection();
  const here = actors.filter((a) => a.x === hit.x && a.y === hit.y);
  // A lone actor is what you meant; a crowd, or an empty tile, gets the tile view.
  if (here.length === 1) selectActor(here[0].id, false);
  else selectTile(hit.x, hit.y, false);
}

addEventListener("keydown", (e) => {
  if (e.target === search || e.ctrlKey || e.metaKey || !world) return;
  const pan = { ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1],
                a: [1, 0], d: [-1, 0], w: [0, 1], s: [0, -1] }[e.key];
  if (pan) {
    stopFollow();
    view.x += pan[0] * 80;
    view.y += pan[1] * 80;
    applyView();
  } else if (e.key === "+" || e.key === "=") zoomCenter(1.25);
  else if (e.key === "-") zoomCenter(0.8);
  else if (e.key === "f" || e.key === "0") fitToViewport();
  else if (e.key === "Escape") clearSelection();
  else if (e.key === "/") {
    e.preventDefault();
    document.body.classList.add("open");
    search.focus();
  } else return;
  e.preventDefault();
});

$("zoom-in").onclick = () => zoomCenter(1.25);
$("zoom-out").onclick = () => zoomCenter(0.8);
$("fit").onclick = () => fitToViewport();
$("toggle").onclick = () => document.body.classList.toggle("open");

loadWorld().then(pollActors);
