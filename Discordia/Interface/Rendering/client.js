// World map client. The server sends the static map as one PNG plus a JSON description of it;
// actors arrive as a small JSON list every couple of seconds and are drawn as sprites on top.
// No build step: this is loaded as a plain script.

const viewport = document.getElementById("viewport");
const stage = document.getElementById("stage");
const bg = document.getElementById("bg");
const actorLayer = document.getElementById("actors");
const info = document.getElementById("info");

let world = null;
let tile = 16;
const structures = new Map(); // "x,y" -> town/wilds record
const actorEls = new Map(); // actor id -> <img>
let actors = [];

const view = { x: 0, y: 0, scale: 1 };

function applyView() {
  stage.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
}

async function loadWorld() {
  world = await (await fetch("/world.json")).json();
  tile = world.tile;
  document.title = world.name;
  document.documentElement.style.setProperty("--tile", tile + "px");
  stage.style.width = world.width * tile + "px";
  stage.style.height = world.height * tile + "px";
  for (const t of world.towns) structures.set(`${t.x},${t.y}`, { kind: "Town", ...t });
  for (const w of world.wilds) structures.set(`${w.x},${w.y}`, { kind: "Wilds", ...w });
  bg.src = "/background.png";
  fitToViewport();
}

function fitToViewport() {
  const r = viewport.getBoundingClientRect();
  view.scale = Math.min(r.width / (world.width * tile), r.height / (world.height * tile));
  view.x = (r.width - world.width * tile * view.scale) / 2;
  view.y = (r.height - world.height * tile * view.scale) / 2;
  applyView();
}

// --- actors ---------------------------------------------------------------

async function pollActors() {
  try {
    actors = (await (await fetch("/actors.json", { cache: "no-store" })).json()).actors;
    const seen = new Set();
    for (const a of actors) {
      seen.add(a.id);
      let el = actorEls.get(a.id);
      if (!el) {
        el = new Image();
        el.className = "actor";
        el.src = a.sprite;
        actorLayer.appendChild(el);
        actorEls.set(a.id, el);
      }
      // Position by transform, not left/top: that's what makes the CSS transition slide.
      el.style.transform = `translate(${a.x * tile}px, ${a.y * tile}px)`;
      el.title = `${a.name} (${a.hp}/${a.hp_max})`;
    }
    for (const [id, el] of actorEls) {
      if (!seen.has(id)) {
        el.remove();
        actorEls.delete(id);
      }
    }
  } catch (err) {
    // Server restarting or mid-save: just try again on the next tick.
  }
  setTimeout(pollActors, 2000);
}

// --- pan, zoom, inspect ---------------------------------------------------

let drag = null;

viewport.addEventListener("pointerdown", (e) => {
  drag = { x: e.clientX, y: e.clientY, moved: 0 };
  viewport.setPointerCapture(e.pointerId);
});

viewport.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x;
  const dy = e.clientY - drag.y;
  view.x += dx;
  view.y += dy;
  drag.moved += Math.abs(dx) + Math.abs(dy);
  drag.x = e.clientX;
  drag.y = e.clientY;
  applyView();
});

viewport.addEventListener("pointerup", (e) => {
  if (drag && drag.moved < 4) inspect(e); // a click, not the end of a drag
  drag = null;
});

viewport.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    const cx = e.clientX - r.left;
    const cy = e.clientY - r.top;
    const next = Math.min(8, Math.max(0.2, view.scale * Math.exp(-e.deltaY / 400)));
    // Keep whatever is under the cursor under the cursor.
    const k = next / view.scale;
    view.x = cx - k * (cx - view.x);
    view.y = cy - k * (cy - view.y);
    view.scale = next;
    applyView();
  },
  { passive: false }
);

function inspect(e) {
  if (!world) return;
  // Read the tile straight off the rendered image, so pan and zoom need no maths of their own.
  const r = bg.getBoundingClientRect();
  const x = Math.floor(((e.clientX - r.left) / r.width) * world.width);
  const y = Math.floor(((e.clientY - r.top) / r.height) * world.height);
  if (x < 0 || y < 0 || x >= world.width || y >= world.height) return;

  const lines = [`<b>(${x}, ${y})</b> &middot; ${world.terrain[y][x]}`];
  const here = structures.get(`${x},${y}`);
  if (here) {
    lines.push(
      here.kind === "Town"
        ? `<b>${here.name}</b> &mdash; town, pop. ${here.population}, ${here.industry}`
        : `<b>${here.name}</b> &mdash; wilds`
    );
  }
  for (const a of actors) {
    if (a.x === x && a.y === y) lines.push(`<b>${a.name}</b> &mdash; ${a.kind}, ${a.hp}/${a.hp_max} hp`);
  }
  info.innerHTML = lines.join("<br>");
}

addEventListener("resize", () => world && fitToViewport());

loadWorld().then(pollActors);
