// World map client, on Leaflet (vendored: leaflet.js). The static map comes a chunk at a time, a PNG per
// explored chunk in view, as a Leaflet tile; actors arrive as a small JSON list every couple of seconds and
// are drawn as markers on top. No build step: this is loaded as a plain script.
//
// Map units are squares, y down: square (x, y) is L.latLng(y, x), and at zoom z a square is 2^z pixels.

const $ = (id) => document.getElementById(id);
const viewport = $("viewport");
const info = $("info");
const search = $("search");

let world = null;
let towns = [];
const residents = new Map(); // "x,y" -> [role, name, line] for each of a town's people, from its chunk's JSON
const structures = new Map(); // "x,y" -> town/wilds record
const explored = new Set(); // "cx,cy" of every chunk the server has generated
const chunkEls = new Map(); // "cx,cy" -> <img> of a chunk on the page
const chunkData = new Map(); // "cx,cy" -> { terrain, wilds }, once fetched
const actorEls = new Map(); // actor id -> its marker
let actors = [];
let selected = null; // { actor: id } or { x, y }
let me; // your own character from /me.json: undefined until asked, null if you haven't logged in
let follow = false;

// A square as players read it, as the bot writes it (World.grid): east/west and north/south of the spawn.
const grid = (x, y) => {
  const [dx, dy] = [x - world.spawn.x, y - world.spawn.y];
  return `${Math.abs(dx)}${dx < 0 ? "W" : "E"} ${Math.abs(dy)}${dy > 0 ? "S" : "N"}`;
};

// Names come from Discord, so nothing goes into innerHTML unescaped.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// Whole zoom levels only: a chunk is then a whole number of pixels at every zoom, so the tiles meet without a
// seam. A square is 2^zoom pixels: from 1/8 (a chunk is 4 pixels) to 128.
const map = L.map(viewport, {
  crs: L.extend({}, L.CRS.Simple, { transformation: new L.Transformation(1, 0, 1, 0) }),
  zoomSnap: 1,
  minZoom: -3,
  maxZoom: 7,
  keyboard: false, // ours, below: WASD, F and / too, and not only while the map has focus
  zoomControl: false,
  attributionControl: false,
});
map.createPane("labels").id = "labels"; // town names, over the chunks
map.createPane("marks"); // the hover cursor and the picked square, under the actors
const at = (x, y) => L.latLng(y, x);
const centre = (x, y) => L.latLng(y + 0.5, x + 0.5);

function onZoom() {
  const z = map.getZoom();
  viewport.style.setProperty("--sq", 2 ** z + "px"); // what overlays size themselves by
  document.body.classList.toggle("far", 2 ** z < 14);
  document.body.classList.toggle("tiny", 2 ** z < 2);
}
map.on("zoom", onZoom);
// An actor slides between the squares a poll moves it across. A zoom moves every marker at once, which
// mustn't slide; Leaflet's own zoom animation still runs.
map.on("zoomstart viewprereset", () => viewport.classList.add("zooming"));
map.on("zoomend viewreset", () =>
  requestAnimationFrame(() => requestAnimationFrame(() => viewport.classList.remove("zooming")))
);

// --- chunks ---------------------------------------------------------------

// One tile is one chunk at every zoom. Leaflet only asks for tiles in view, and drops them once out of it.
const Chunks = L.GridLayer.extend({
  getTileSize() {
    return L.point(1, 1).multiplyBy(world.chunk * 2 ** this._tileZoom);
  },
  // Unexplored chunks 404: the server never generates for the map. (Private, but Leaflet is vendored.)
  _isValidTile(c) {
    return explored.has(`${c.x},${c.y}`);
  },
  createTile(c, done) {
    const img = document.createElement("img");
    img.alt = "";
    img.className = "chunk";
    img.dataset.z = c.z;
    img.onload = () => done(null, img); // the old zoom's picture stays up until the new one has loaded
    img.onerror = (err) => done(err, img);
    // Under 4 pixels a square, the 2-pixel overview is at most doubled, and a tenth of the bytes.
    img.src = `/chunk/${c.x}/${c.y}.${2 ** c.z < 4 ? "mini.png" : "png"}`;
    return img;
  },
});
let chunks = null;

// Edges between device pixels let the background through, a faint grid over the map: at 125% scaling a whole
// CSS pixel isn't a whole device pixel. Every tile sits a whole number of chunks from the others, so nudging
// the pane they share puts them all on the grid. Hit-testing is Leaflet's, off by under a device pixel.
const tilePane = map.getPane("tilePane");
let snapFrame = 0;
const snapTiles = () => (snapFrame ||= requestAnimationFrame(snapNow));
function snapNow() {
  snapFrame = 0;
  tilePane.style.transform = "";
  if (map.getPane("mapPane").classList.contains("leaflet-zoom-anim")) return; // mid-zoom; snaps at its end
  const z = String(map.getZoom());
  const any = [...chunkEls.values()].find((el) => el.dataset.z === z);
  if (!any) return;
  const d = devicePixelRatio;
  const r = any.getBoundingClientRect();
  const off = (v) => (Math.round(v * d) - v * d) / d;
  tilePane.style.transform = `translate(${off(r.left)}px, ${off(r.top)}px)`;
}
map.on("move moveend zoomend viewreset resize", snapTiles);

async function loadChunkData(key, cx, cy) {
  chunkData.set(key, null); // in flight; don't ask twice
  try {
    const data = await (await fetch(`/chunk/${cx}/${cy}.json`)).json();
    chunkData.set(key, data);
    for (const w of data.wilds) structures.set(`${w.x},${w.y}`, { kind: "Wilds", ...w });
    for (const p of data.places) structures.set(`${p.x},${p.y}`, p); // extraction points and caches
    for (const t of data.towns) residents.set(`${t.x},${t.y}`, t.residents);
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

const labels = L.layerGroup();

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
      labels.clearLayers();
      for (const t of towns) {
        const icon = L.divIcon({ className: "label", html: `<span>${esc(t.name)}</span>`, iconSize: null });
        labels.addLayer(L.marker(at(t.x + 0.5, t.y), { icon, pane: "labels", interactive: false, keyboard: false }));
      }
      renderTowns();
    }
    if (explored.size !== before) chunks?._update(); // new chunks in view get their tiles (private, as above)
  } catch (err) {
    // pollActors already shows the server as down
  }
  setTimeout(pollExplored, 10000);
}

async function loadWorld() {
  world = await (await fetch("/world.json")).json();
  document.title = world.name;
  $("world-name").textContent = world.name;
  map.setView(centre(world.spawn.x, world.spawn.y), 4); // a square at its drawn size, until the fit
  onZoom();
  labels.addTo(map);
  await pollExplored();
  fitToViewport();
  // After the fit: added at the first view, it would fetch full-size chunks the fit is about to swap out.
  chunks = new Chunks({ keepBuffer: 1 })
    .on("tileloadstart", (e) => chunkEls.set(`${e.coords.x},${e.coords.y}`, e.tile))
    .on("tileunload", (e) => {
      const key = `${e.coords.x},${e.coords.y}`;
      if (chunkEls.get(key) === e.tile) chunkEls.delete(key); // not if the next zoom's tile took its place
    })
    .on("tileloadstart", snapTiles)
    .addTo(map);
}

// Fit the explored part of the map: the whole of a big world is mostly nothing yet.
function fitToViewport() {
  const keys = [...explored].map((k) => k.split(",").map(Number));
  if (!keys.length) return map.setView(centre(world.spawn.x, world.spawn.y), 4);
  const c = world.chunk;
  const xs = keys.map(([cx]) => cx);
  const ys = keys.map(([, cy]) => cy);
  const corner = at(Math.min(...xs) * c, Math.min(...ys) * c);
  map.fitBounds(L.latLngBounds(corner, at((Math.max(...xs) + 1) * c, (Math.max(...ys) + 1) * c)), { animate: false });
}

function flyTo(x, y, zoom = map.getZoom()) {
  map.setView(centre(x, y), zoom, { animate: true });
}

// The square under a point on screen, or null off the map.
function tileAt(clientX, clientY) {
  return squareAt(map.mouseEventToLatLng({ clientX, clientY }));
}
function squareAt(latlng) {
  const x = Math.floor(latlng.lng);
  const y = Math.floor(latlng.lat);
  return world && x >= 0 && y >= 0 && x < world.width && y < world.height ? { x, y } : null;
}

// The hover cursor and the picked square: an outline the size of a square.
const box = (className) =>
  L.marker([0, 0], { icon: L.divIcon({ className, iconSize: null }), pane: "marks", interactive: false, keyboard: false });
const cursor = box("cursor");
const pick = box("pick");

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
    let marker = actorEls.get(a.id);
    if (!marker) {
      const icon = L.divIcon({
        className: `actor ${a.kind}`,
        html: `<div class="tag"><span class="name"></span><div class="bar"><i></i></div></div><img alt="">`,
        iconSize: null,
      });
      marker = L.marker(at(a.x, a.y), { icon, interactive: false, keyboard: false }).addTo(map);
      marker.getElement().querySelector("img").src = a.sprite;
      marker.getElement().querySelector(".name").textContent = a.name;
      actorEls.set(a.id, marker);
    } else {
      marker.setLatLng(at(a.x, a.y)); // a transform, which the CSS transition slides
    }
    const el = marker.getElement();
    const pct = a.hp_max ? (100 * a.hp) / a.hp_max : 0;
    el.querySelector(".bar i").style.width = pct + "%";
    el.querySelector(".bar").classList.toggle("low", pct <= 30);
    el.classList.toggle("full", a.hp >= a.hp_max);
    el.classList.toggle("selected", selected?.actor === a.id);
    el.classList.toggle("me", me?.id === a.id);
    el.classList.toggle("intown", structures.get(`${a.x},${a.y}`)?.kind === "Town"); // tag clears the town's name
    marker.setZIndexOffset(selected?.actor === a.id ? 100000 : 0); // Leaflet stacks markers by row otherwise
  }
  for (const [id, marker] of actorEls) {
    if (!seen.has(id)) {
      marker.remove();
      actorEls.delete(id);
    }
  }

  const followed = selected?.actor && actors.find((a) => a.id === selected.actor);
  if (followed && follow) flyTo(followed.x, followed.y);
  const npcs = actors.filter((a) => a.kind === "npc").length;
  const players = actors.filter((a) => a.kind === "player").length; // the rest are remains
  $("meta").textContent =
    `Seed ${world.seed} · ${world.width.toLocaleString()}² · ${explored.size} chunks explored · ` +
    `${players} player${players === 1 ? "" : "s"} · ${npcs} NPC${npcs === 1 ? "" : "s"}`;
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
  renderPlay();
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
    `<br>Equipped: ${esc(me.equipment.join(", ") || "nothing")}<br>Carrying: ${esc(me.inventory.join(", ") || "nothing")}` +
    `<br><a href="/me">Character sheet</a>`;
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
    .filter((a) => a.kind === "player" && a.id !== me?.id && matches(a.name)) // you have your own row
    .sort((a, b) => a.name.localeCompare(b.name));
  fill(
    $("players"),
    players.map((p) =>
      row(p.sprite, p.name, `Lv ${p.level} ${p.class} · ${grid(p.x, p.y)}`, hpBar(p), selected?.actor === p.id, () =>
        selectActor(p.id, true)
      )
    ),
    search.value ? "No match." : me ? "No one else is out there yet." : "No one is out there yet."
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
  pick.remove();
  renderActors();
  markSelectedTown();
  const a = actors.find((a) => a.id === id);
  if (fly && a) flyTo(a.x, a.y, Math.max(map.getZoom(), 5));
}

function stopFollow() {
  if (follow) {
    follow = false;
    renderInfo();
  }
}

function selectTile(x, y, fly) {
  selected = { x, y };
  follow = false;
  pick.setLatLng(at(x, y)).addTo(map);
  if (fly) flyTo(x, y, Math.max(map.getZoom(), 5));
  renderActors();
  markSelectedTown();
}

function clearSelection() {
  selected = null;
  follow = false;
  pick.remove();
  renderActors();
  markSelectedTown();
}

const PLACES = { Extract: "a ride to the nearest town, raid over", Cache: "loot, restocked every few hours" };

// The name is a button: a click (below, on the panel) picks that actor out of a crowd and follows it.
function describeActor(a) {
  const name = `<button class="who" data-actor="${esc(a.id)}">${esc(a.name)}</button>`;
  if (a.kind === "remains") return `${name} <span class="dim">&mdash; dropped on death, free to take</span><br>${esc(a.contents)}`;
  const what = a.kind === "player" ? `Level ${a.level} ${esc(a.class)}` : "NPC";
  return `${name} <span class="dim">&mdash; ${what}</span><br>${a.hp}/${a.hp_max} hp`;
}

info.addEventListener("click", (e) => {
  const who = e.target.closest("[data-actor]");
  if (!who) return;
  document.body.classList.remove("open"); // phones: as a list row does
  selectActor(who.dataset.actor, true);
});

// The panel is a console: each pick's description stays above the next, oldest scrolled off past INFO_LOG.
// Only the bottom entry is live, redrawn every poll; the rest are what they said when the pick moved on.
const INFO_LOG = 50;
const infoLog = []; // frozen HTML, oldest first
let infoKey = null; // what the live entry describes: an actor id, "x,y", or null for the hint
let infoLive = "";

function showInfo(key, html, note = "") {
  if (key !== infoKey && infoKey !== null) infoLog.push(infoLive);
  infoLog.splice(0, infoLog.length - INFO_LOG);
  [infoKey, infoLive] = [key, html];
  const atBottom = info.scrollTop + info.clientHeight >= info.scrollHeight - 4; // not if you've scrolled up to read
  info.innerHTML = [...infoLog.map((h) => `<div class="entry old">${h}</div>`), `<div class="entry">${html}${note}</div>`].join("");
  if (atBottom) info.scrollTop = info.scrollHeight;
}

function renderInfo() {
  if (!world) return;
  if (!selected) return showInfo(null, `<span class="dim">Click a tile or a name. Arrows pan, +/- zoom, F fits, / searches.</span>`);
  let x, y;
  const lines = [];
  if (selected.actor) {
    const a = actors.find((a) => a.id === selected.actor);
    if (!a) return showInfo(selected.actor, `<span class="dim">Gone from the map.</span>`);
    ({ x, y } = a);
    lines.push(describeActor(a));
  } else {
    ({ x, y } = selected);
    for (const a of actors) if (a.x === x && a.y === y) lines.push(describeActor(a));
  }
  const here = structures.get(`${x},${y}`);
  if (here) {
    lines.unshift(
      here.kind === "Town"
        ? `<b>${esc(here.name)}</b> <span class="dim">&mdash; town, pop. ${here.population}, ${esc(here.industry)}</span>`
        : `<b>${esc(here.name)}</b> <span class="dim">&mdash; ${PLACES[here.kind] ?? "wilds"}</span>`
    );
    const people = residents.get(`${x},${y}`) ?? []; // the town's own, under its name
    lines.splice(1, 0, ...people.map(([role, name, line]) => `${esc(name)}, the ${esc(role)}: <span class="dim">&ldquo;${esc(line)}&rdquo;</span>`));
  }
  lines.push(`<span class="dim">${grid(x, y)} &middot; ${esc(terrainAt(x, y))}</span>`);
  // "Following" is only true of the live entry: it stays out of what goes up into the log.
  const note = selected.actor && follow ? `<br><span class="dim">Following &middot; drag to stop</span>` : "";
  showInfo(selected.actor ?? `${x},${y}`, lines.join("<br>"), note);
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

// Leaflet pans and zooms (drag, wheel, pinch); a click it didn't take for a drag is an inspect.
// The map is made of <img>s, and pressing on one starts the browser's own image drag, which cancels the
// pointer and with it the pan. Leaflet only stops that mid-drag; this stops it from the first press.
viewport.addEventListener("dragstart", (e) => e.preventDefault());
map.on("dragstart", stopFollow);

let hover = null; // the square under the pointer
function showHover(hit) {
  const s = structures.get(`${hit.x},${hit.y}`);
  $("hover").textContent = `${grid(hit.x, hit.y)} ${terrainAt(hit.x, hit.y)}${s ? " · " + s.name : ""}`;
}

map.on("mousemove", (e) => {
  hover = squareAt(e.latlng);
  if (hover) cursor.setLatLng(at(hover.x, hover.y)).addTo(map);
  else cursor.remove();
  // Not mid-drag: the map slides under a still pointer, and each chunk it crosses would be fetched.
  if (hover && !map.dragging.moving()) showHover(hover);
});
map.on("mouseout", () => {
  hover = null;
  cursor.remove();
  $("hover").textContent = "";
});

map.on("click", (e) => {
  const hit = squareAt(e.latlng);
  if (!hit) return clearSelection();
  const here = actors.filter((a) => a.x === hit.x && a.y === hit.y);
  // A lone actor is what you meant; a crowd, or an empty square, gets the square's view.
  if (here.length === 1) selectActor(here[0].id, false);
  else selectTile(hit.x, hit.y, false);
});

addEventListener("keydown", (e) => {
  if (e.target === search || e.ctrlKey || e.metaKey || !world) return;
  const pan = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
                a: [-1, 0], d: [1, 0], w: [0, -1], s: [0, 1] }[e.key];
  if (pan) {
    stopFollow();
    map.panBy([pan[0] * 80, pan[1] * 80]);
  } else if (e.key === "+" || e.key === "=") map.zoomIn();
  else if (e.key === "-") map.zoomOut();
  else if (e.key === "f" || e.key === "0") fitToViewport();
  else if (e.key === "Escape") clearSelection();
  else if (e.key === "/") {
    e.preventDefault();
    document.body.classList.add("open");
    search.focus();
  } else return;
  e.preventDefault();
});

$("zoom-in").onclick = () => map.zoomIn();
$("zoom-out").onclick = () => map.zoomOut();
$("fit").onclick = () => fitToViewport();
$("toggle").onclick = () => document.body.classList.toggle("open");

// --- play ------------------------------------------------------------------

// Orders go through the same queue as slash commands: each one waits for the next tick, and a second one
// before then replaces the first. The request stays open until the tick answers it.
const play = $("play");
let mode = "move";
let pending = 0; // orders still waiting on their tick
const results = []; // { t, text } of this page's own orders, newest first

function setMode(next) {
  mode = next;
  play.classList.toggle("attack", mode === "attack");
  for (const b of play.querySelectorAll("[data-mode]")) b.setAttribute("aria-pressed", b.dataset.mode === mode);
  renderPlay();
}

async function act(order) {
  pending++;
  renderPlay();
  let text;
  try {
    const r = await fetch("/act", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(order),
    });
    text = (await r.json()).text;
  } catch (err) {
    text = "Lost the server. Try again in a moment.";
  }
  pending--;
  results.unshift({ t: Date.now() / 1000, text });
  results.length = Math.min(results.length, 10);
  // Show the world as the tick left it now, not at the next poll.
  try {
    const r = await fetch("/me.json", { cache: "no-store" });
    if (r.ok) me = await r.json();
  } catch (err) {}
  renderMe();
}

function renderPlay() {
  const playing = Boolean(me?.location);
  play.hidden = !playing;
  if (!playing) return;
  play.classList.toggle("waiting", pending > 0);
  play.querySelector(".hub").textContent = pending ? "next tick…" : mode === "move" ? "move" : "attack";
  const encounter = $("encounter");
  encounter.hidden = !me.encounter;
  if (me.encounter) encounter.querySelector("p").textContent = me.encounter;
  // Your orders and the world's news, together, newest first.
  const entries = [...results, ...me.news.map((n) => ({ ...n, news: true }))].sort((a, b) => b.t - a.t).slice(0, 4);
  $("log").replaceChildren(
    ...entries.map((e) => {
      const li = document.createElement("li");
      li.textContent = e.text;
      if (e.news) li.className = "news";
      return li;
    })
  );
}

for (const b of play.querySelectorAll("[data-mode]")) b.onclick = () => setMode(b.dataset.mode);
for (const b of play.querySelectorAll("[data-dir]")) {
  b.title = `${b.getAttribute("aria-label")} (${"7 8 9 4 6 1 2 3".split(" ")[["nw", "n", "ne", "w", "e", "sw", "s", "se"].indexOf(b.dataset.dir)]})`;
  b.onclick = () => act({ action: mode, direction: b.dataset.dir });
}
for (const b of play.querySelectorAll("[data-choice]")) b.onclick = () => act({ action: "choose", choice: b.dataset.choice });

// Keys lay out like a numpad: 8 is north, 7 northwest. Arrows and WASD already pan the map.
const KEY_DIRECTIONS = { 7: "nw", 8: "n", 9: "ne", 4: "w", 6: "e", 1: "sw", 2: "s", 3: "se" };
addEventListener("keydown", (e) => {
  if (play.hidden || e.target === search || e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.code.startsWith("Numpad") ? e.code.slice(6) : e.key;
  if (KEY_DIRECTIONS[key]) act({ action: mode, direction: KEY_DIRECTIONS[key] });
  else if (e.key === "t") setMode(mode === "move" ? "attack" : "move");
  else return;
  e.preventDefault();
});

loadWorld().then(pollActors).then(pollMe);
