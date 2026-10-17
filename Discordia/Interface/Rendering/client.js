// World map client. The static map comes a chunk at a time, a PNG plus a JSON description of each,
// fetched only for explored chunks in view; actors arrive as a small JSON list every couple of seconds
// and are drawn as sprites on top. No build step: this is loaded as a plain script.
//
// Everything is placed relative to the spawn, not the map's corner: a big world's far edge is past the
// pixel offsets a browser can lay out precisely.

const $ = (id) => document.getElementById(id);
const viewport = $("viewport");
const stage = $("stage");
const chunkLayer = $("chunks");
const actorLayer = $("actors");
const pick = $("pick");
const cursor = $("cursor");
const info = $("info");
const search = $("search");

let world = null;
let origin = { x: 0, y: 0 }; // the spawn, in squares
let tile = 16;
let towns = [];
const structures = new Map(); // "x,y" -> town/wilds record
const explored = new Set(); // "cx,cy" of every chunk the server has generated
const chunkEls = new Map(); // "cx,cy" -> <img> of a chunk in view
const chunkData = new Map(); // "cx,cy" -> { terrain, wilds }, once fetched
const actorEls = new Map(); // actor id -> element
let actors = [];
let selected = null; // { actor: id } or { x, y }
let me; // your own character from /me.json: undefined until asked, null if you haven't logged in
let follow = false;

const view = { x: 0, y: 0, scale: 1 };
// What's actually drawn: the view, nudged so every chunk edge lands on a whole device pixel. Anywhere
// else, each chunk's anti-aliased edge lets the background through and the map shows a faint grid.
// The view itself stays unrounded, or a slow pinch's small steps would round away to nothing.
const shown = { ...view };

// Names come from Discord, so nothing goes into innerHTML unescaped.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function applyView() {
  const d = devicePixelRatio;
  const span = world ? world.chunk * tile : tile; // a chunk, in map pixels
  shown.scale = Math.max(1, Math.round(span * view.scale * d)) / (span * d);
  // Chunks are placed relative to the spawn, which needn't sit on a chunk edge: snap the grid, not it.
  const gx = world ? (origin.x % world.chunk) * tile * shown.scale : 0;
  const gy = world ? (origin.y % world.chunk) * tile * shown.scale : 0;
  shown.x = Math.round((view.x - gx) * d) / d + gx;
  shown.y = Math.round((view.y - gy) * d) / d + gy;
  stage.style.transform = `translate(${shown.x}px, ${shown.y}px) scale(${shown.scale})`;
  stage.style.setProperty("--inv", 1 / shown.scale);
  document.body.classList.toggle("far", view.scale * tile < 14);
  document.body.classList.toggle("tiny", view.scale * tile < 2);
  queueChunks();
}

// --- chunks ---------------------------------------------------------------

let chunkFrame = 0;
function queueChunks() {
  if (!chunkFrame) chunkFrame = requestAnimationFrame(showChunks);
}
// Add the explored chunks in view (plus a ring of margin) and drop the rest, so panning across a big
// world never holds more than a screenful of chunk images.
function showChunks() {
  chunkFrame = 0;
  if (!world) return;
  const r = viewport.getBoundingClientRect();
  const span = world.chunk * tile * view.scale;
  const cx0 = Math.floor(-view.x / span + origin.x / world.chunk) - 1;
  const cy0 = Math.floor(-view.y / span + origin.y / world.chunk) - 1;
  const cx1 = cx0 + Math.ceil(r.width / span) + 2;
  const cy1 = cy0 + Math.ceil(r.height / span) + 2;
  const inView = (key) => {
    const [cx, cy] = key.split(",").map(Number);
    return cx >= cx0 && cx <= cx1 && cy >= cy0 && cy <= cy1;
  };
  for (const [key, el] of chunkEls) {
    if (!inView(key)) {
      el.remove();
      chunkEls.delete(key);
    }
  }
  // Under 4 screen pixels a square, the 2-pixel overview is at most doubled, and a tenth of the bytes.
  const ext = tile * view.scale < 4 ? "mini.png" : "png";
  for (const key of explored) {
    if (!inView(key)) continue;
    const [cx, cy] = key.split(",").map(Number);
    let el = chunkEls.get(key);
    if (!el) {
      el = new Image();
      el.className = "chunk";
      el.alt = "";
      el.style.width = el.style.height = world.chunk * tile + "px"; // the overview is smaller than its square
      place(el, cx * world.chunk, cy * world.chunk);
      chunkLayer.appendChild(el);
      chunkEls.set(key, el);
    }
    // Crossing the zoom threshold swaps the picture; the old one stays up until the new one loads.
    const src = `/chunk/${cx}/${cy}.${ext}`;
    if (el.getAttribute("src") !== src) el.src = src;
  }
}

async function loadChunkData(key, cx, cy) {
  chunkData.set(key, null); // in flight; don't ask twice
  try {
    const data = await (await fetch(`/chunk/${cx}/${cy}.json`)).json();
    chunkData.set(key, data);
    for (const w of data.wilds) structures.set(`${w.x},${w.y}`, { kind: "Wilds", ...w });
    // Whoever asked was shown a placeholder; fill it in.
    renderInfo();
    if (hover) showHover(hover);
  } catch (err) {
    chunkData.delete(key); // try again next time something asks
  }
}

// Only hover and the info panel need a chunk's description, so it's fetched when one of them asks: a
// zoomed-out view would otherwise pull hundreds of them for nothing.
function terrainAt(x, y) {
  const c = world.chunk;
  const [cx, cy] = [Math.floor(x / c), Math.floor(y / c)];
  const key = `${cx},${cy}`;
  if (!explored.has(key)) return "unexplored";
  if (!chunkData.has(key)) loadChunkData(key, cx, cy);
  return chunkData.get(key)?.terrain[y % c][x % c] ?? "…";
}

// Explored ground only grows, as players walk into new chunks; check every so often.
async function pollExplored() {
  // A background tab draws nothing, so it fetches nothing. The first poll has to happen regardless.
  if (document.hidden && explored.size) return setTimeout(pollExplored, 10000);
  try {
    // no-cache, not no-store: revalidate against the ETag, which only changes when the map grows.
    const data = await (await fetch("/explored.json", { cache: "no-cache" })).json();
    const before = explored.size;
    for (const [cx, cy] of data.chunks) explored.add(`${cx},${cy}`);
    if (data.towns.length !== towns.length) {
      towns = data.towns;
      for (const t of towns) structures.set(`${t.x},${t.y}`, { kind: "Town", ...t });
      // Wilds are hundreds of tiles; labelling them buries the map. Hover and click still name them.
      $("labels").replaceChildren(
        ...towns.map((s) => {
          const el = document.createElement("div");
          el.className = "label";
          el.textContent = s.name;
          el.style.left = (s.x - origin.x + 0.5) * tile + "px";
          el.style.top = (s.y - origin.y) * tile + "px";
          return el;
        })
      );
      renderTowns();
    }
    // Next frame, not now: on the first poll the view isn't fitted yet, and drawing at its default zoom
    // would fetch full-size chunks the fit is about to swap for overviews.
    if (explored.size !== before) queueChunks();
  } catch (err) {
    // pollActors already shows the server as down
  }
  setTimeout(pollExplored, 10000);
}

async function loadWorld() {
  world = await (await fetch("/world.json")).json();
  tile = world.tile;
  document.title = world.name;
  $("world-name").textContent = world.name;
  origin = world.spawn;
  document.documentElement.style.setProperty("--tile", tile + "px");
  await pollExplored();
  fitToViewport();
}

// Fit the explored part of the map: the whole of a big world is mostly nothing yet.
function fitToViewport() {
  const r = viewport.getBoundingClientRect();
  const keys = [...explored].map((k) => k.split(",").map(Number));
  if (!keys.length) return flyTo(origin.x, origin.y, 1);
  const c = world.chunk;
  const xs = keys.map(([cx]) => cx);
  const ys = keys.map(([, cy]) => cy);
  const x0 = Math.min(...xs) * c;
  const x1 = (Math.max(...xs) + 1) * c;
  const y0 = Math.min(...ys) * c;
  const y1 = (Math.max(...ys) + 1) * c;
  cancelAnimationFrame(anim);
  view.scale = Math.min(8, r.width / ((x1 - x0) * tile), r.height / ((y1 - y0) * tile));
  view.x = (r.width - (x1 - x0) * tile * view.scale) / 2 - (x0 - origin.x) * tile * view.scale;
  view.y = (r.height - (y1 - y0) * tile * view.scale) / 2 - (y0 - origin.y) * tile * view.scale;
  applyView();
}

let anim = 0;
function flyTo(x, y, scale = view.scale) {
  const r = viewport.getBoundingClientRect();
  const from = { ...view };
  const to = {
    scale,
    x: r.width / 2 - (x - origin.x + 0.5) * tile * scale,
    y: r.height / 2 - (y - origin.y + 0.5) * tile * scale,
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
  // A fit can go below the 0.2 floor; zooming out from there mustn't jump back in.
  const next = Math.min(8, Math.max(Math.min(0.2, view.scale), view.scale * factor));
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
  const size = tile * shown.scale; // what's drawn, so the square under the pointer is the one you see
  const x = Math.floor((clientX - r.left - shown.x) / size) + origin.x;
  const y = Math.floor((clientY - r.top - shown.y) / size) + origin.y;
  return world && x >= 0 && y >= 0 && x < world.width && y < world.height ? { x, y } : null;
}

const place = (el, x, y) =>
  (el.style.transform = `translate(${(x - origin.x) * tile}px, ${(y - origin.y) * tile}px)`);

// --- actors ---------------------------------------------------------------

async function pollActors() {
  if (document.hidden) return setTimeout(pollActors, 2000);
  try {
    // no-cache: revalidate. Between ticks the server answers 304 and the browser hands back the last list.
    actors = (await (await fetch("/actors.json", { cache: "no-cache" })).json()).actors;
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
    el.className =
      `actor ${a.kind}${a.hp >= a.hp_max ? " full" : ""}` +
      `${selected?.actor === a.id ? " selected" : ""}${me?.id === a.id ? " me" : ""}`;
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
    `Seed ${world.seed} · ${world.width.toLocaleString()}² · ${explored.size} chunks explored · ` +
    `${actors.length - npcs} player${actors.length - npcs === 1 ? "" : "s"} · ${npcs} NPC${npcs === 1 ? "" : "s"}`;
  renderPlayers();
  renderMe();
  renderInfo();
}

// Your own sheet, for whoever's /weblogin session this page is. Polled once a tick: it's tiny, and private,
// so no ETag. A 404 means that session has no character; /register makes one, so keep asking.
async function pollMe() {
  if (!document.hidden) {
    try {
      const r = await fetch("/me.json", { cache: "no-store" });
      const first = me === undefined;
      me = r.ok ? await r.json() : null;
      if (first && me?.location && !selected) selectActor(me.id, true); // open on yourself
      renderMe();
    } catch (err) {
      // pollActors already shows the server as down
    }
  }
  setTimeout(pollMe, 5000);
}

function renderMe() {
  if (me === undefined) return;
  if (!me) {
    $("you").innerHTML = `<div class="empty">No character yet. Use /register in Discord.</div>`;
    return;
  }
  const details = document.createElement("div");
  details.className = "you";
  details.innerHTML =
    `${me.hp}/${me.hp_max} hp · ${me.xp_to_next} XP to level ${me.level + 1}` +
    (me.location ? "" : " · not on the map") +
    `<br>Equipped: ${esc(me.equipment.join(", ") || "nothing")}<br>Carrying: ${esc(me.inventory.join(", ") || "nothing")}`;
  $("you").replaceChildren(
    row(me.sprite, me.name, `Lv ${me.level} ${me.class} · $${me.currency.toLocaleString()}`, hpBar(me),
        selected?.actor === me.id, () => selectActor(me.id, true)),
    details
  );
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
  const shown = towns.filter((t) => matches(t.name)).sort((a, b) => a.name.localeCompare(b.name));
  fill(
    $("towns"),
    shown.map((t) => {
      const b = row(t.sprite, t.name, `Pop. ${t.population} · ${t.industry}`, "", false, () => selectTile(t.x, t.y, true));
      b.dataset.at = `${t.x},${t.y}`;
      return b;
    }),
    "No match."
  );
  markSelectedTown();
}

// A click only moves the highlight. Rebuilding every row for it took a frame or two with a thousand towns.
function markSelectedTown() {
  const at = selected && !selected.actor ? `${selected.x},${selected.y}` : null;
  for (const b of $("towns").children) b.classList.toggle("selected", b.dataset.at === at);
}

function selectActor(id, fly) {
  selected = { actor: id };
  follow = fly;
  pick.style.display = "none";
  renderActors();
  markSelectedTown();
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
  markSelectedTown();
}

function clearSelection() {
  selected = null;
  follow = false;
  pick.style.display = "none";
  renderActors();
  markSelectedTown();
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
  lines.push(`<span class="dim">(${x}, ${y}) &middot; ${esc(terrainAt(x, y))}</span>`);
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

let hover = null; // the tile under the pointer
function showHover(hit) {
  const s = structures.get(`${hit.x},${hit.y}`);
  $("hover").textContent = `(${hit.x}, ${hit.y}) ${terrainAt(hit.x, hit.y)}${s ? " · " + s.name : ""}`;
}

viewport.addEventListener("pointermove", (e) => {
  hover = tileAt(e.clientX, e.clientY);
  cursor.style.display = hover ? "block" : "none";
  if (hover) place(cursor, hover.x, hover.y);
  // Not mid-drag: the map slides under a still pointer, and each chunk it crosses would be fetched.
  if (hover && !drag) showHover(hover);

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
  hover = null;
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

loadWorld().then(pollActors).then(pollMe);
