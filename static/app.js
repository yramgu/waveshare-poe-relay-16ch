'use strict';

const N = 16;
// Hotspot geometry, in pixels of ui/pic1.PNG (873 x 456). Converted to % so it scales.
const IMG_W = 873, IMG_H = 456;
const COL_X = [283, 350, 416, 482, 548, 615, 681, 748];   // channel centres, left -> right
const HOT_W = 62;
const ROW_TOP = { y: 74, h: 68 };      // CH1..CH8  (labels + terminals)
const ROW_BOTTOM = { y: 312, h: 70 };  // CH16..CH9 (labels + terminals)

let states = new Array(N).fill(false);
let names = Array.from({ length: N }, (_, i) => `CH${i + 1}`);
let maps = [];   // [{name, channels: [1-based channel numbers]}] from config.json "maps" dict
let editing = false;

const $ = (sel) => document.querySelector(sel);
const hots = [], cards = [], mapBtns = [];

// ---------- API ----------
async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function setStatus(ok, text) {
  const el = $('#status');
  el.className = 'status ' + (ok ? 'ok' : 'err');
  el.textContent = ok ? 'Connected' : 'Offline';
  el.title = text || '';
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 4000);
}

// Runs a request that returns {states}, updates UI, handles errors.
async function command(method, url, body, busyEls = []) {
  busyEls.forEach((e) => e.classList.add('busy'));
  try {
    const data = await api(method, url, body);
    states = data.states;
    setStatus(true);
  } catch (err) {
    setStatus(false, err.message);
    toast(err.message);
  } finally {
    busyEls.forEach((e) => e.classList.remove('busy'));
    render();
  }
}

// ---------- build UI ----------
function pct(v, total) { return (v / total * 100) + '%'; }

function buildHotspots() {
  const dev = $('#device');
  for (let ch = 1; ch <= N; ch++) {
    const top = ch <= 8;
    const col = top ? ch - 1 : 16 - ch;   // bottom row runs CH16 (left) .. CH9 (right)
    const row = top ? ROW_TOP : ROW_BOTTOM;
    const b = document.createElement('button');
    b.className = 'hot ' + (top ? 'top' : 'bottom');
    b.style.left = pct(COL_X[col] - HOT_W / 2, IMG_W);
    b.style.width = pct(HOT_W, IMG_W);
    b.style.top = pct(row.y, IMG_H);
    b.style.height = pct(row.h, IMG_H);
    b.innerHTML = '<span class="led"></span>';
    b.addEventListener('click', () => toggle(ch));
    dev.appendChild(b);
    hots[ch - 1] = b;
  }
}

function buildCards() {
  const wrap = $('#channels');
  wrap.innerHTML = '';
  // same layout as the board: CH1..CH8 on top, CH16..CH9 below
  const order = Array.from({ length: N }, (_, i) => (i < 8 ? i + 1 : N + 8 - i));
  for (const ch of order) {
    const c = document.createElement('div');
    c.className = 'card';
    c.addEventListener('click', (e) => { if (!editing && e.target.tagName !== 'INPUT') toggle(ch); });
    wrap.appendChild(c);
    cards[ch - 1] = c;
  }
}

function buildMaps() {
  const list = $('#mapList');
  list.innerHTML = '';
  mapBtns.length = 0;
  maps.forEach((m) => {
    const b = document.createElement('button');
    b.className = 'btn map';
    b.textContent = m.name;
    b.addEventListener('click', () => applyMap(m.name, b.classList.contains('active')));
    list.appendChild(b);
    mapBtns.push(b);
  });
  $('#maps').hidden = maps.length === 0;
}

function render() {
  maps.forEach((m, i) => {
    // a map is active when exactly its channels are ON
    const active = states.every((on, ch) => !!on === m.channels.includes(ch + 1));
    mapBtns[i].classList.toggle('active', active);
    const list = m.channels.map((ch) => names[ch - 1]).join(', ') || 'none';
    mapBtns[i].title = active
      ? `Active (ON: ${list}) — click to turn all OFF`
      : `ON: ${list} — all others OFF`;
  });
  let onCount = 0;
  for (let i = 0; i < N; i++) {
    const on = !!states[i];
    if (on) onCount++;
    hots[i].classList.toggle('on', on);
    hots[i].title = `CH${i + 1} – ${names[i]}: ${on ? 'ON (closed)' : 'OFF (open)'} — click to toggle`;
    const c = cards[i];
    c.classList.toggle('on', on);
    if (editing) {
      if (!c.querySelector('input')) {
        c.innerHTML = `<span class="num">CH${i + 1}</span><input maxlength="24">`;
        c.querySelector('input').value = names[i];
      }
    } else {
      c.innerHTML = `<span class="num">CH${i + 1}</span><span class="name"></span>`
        + `<span class="st">${on ? 'ON' : 'OFF'}</span>`;
      c.querySelector('.name').textContent = names[i];
      c.title = `${names[i]} — click to turn ${on ? 'OFF' : 'ON'}`;
    }
  }
  $('#count').textContent = `${onCount} / ${N} ON`;
}

// ---------- actions ----------
function toggle(ch) {
  if (editing) return;
  command('POST', `/api/relay/${ch}`, { on: !states[ch - 1] }, [hots[ch - 1], cards[ch - 1]]);
}

async function bulk(kind) {
  const btns = document.querySelectorAll('.bulk .btn');
  btns.forEach((b) => (b.disabled = true));
  await command('POST', `/api/all/${kind}`, null, [...hots, ...cards]);
  btns.forEach((b) => (b.disabled = false));
}

// Clicking the active map turns it "off" (all relays OFF); otherwise apply it.
async function applyMap(name, active) {
  mapBtns.forEach((b) => (b.disabled = true));
  const url = active ? '/api/all/off' : `/api/map/${encodeURIComponent(name)}`;
  await command('POST', url, null, [...hots, ...cards]);
  mapBtns.forEach((b) => (b.disabled = false));
}

async function refresh() { await command('GET', '/api/state'); }

async function toggleEdit() {
  const btn = $('#editNames');
  if (editing) {
    const newNames = cards.map((c, i) => c.querySelector('input').value.trim() || `CH${i + 1}`);
    try {
      const data = await api('POST', '/api/config', { names: newNames });
      names = data.config.names;
      maps = data.config.maps;   // name-based map entries may resolve differently now
      buildMaps();
    } catch (err) { toast(err.message); return; }
  }
  editing = !editing;
  btn.textContent = editing ? 'Save names' : 'Edit names';
  $('#channels').classList.toggle('editing', editing);
  render();
}

async function connect(e) {
  e.preventDefault();
  try {
    await api('POST', '/api/config', {
      host: $('#host').value, port: $('#port').value, unit: $('#unit').value,
    });
  } catch (err) { toast(err.message); return; }
  refresh();
}

// ---------- init ----------
async function init() {
  buildHotspots();
  buildCards();
  render();
  document.querySelectorAll('[data-bulk]').forEach((b) => b.addEventListener('click', () => bulk(b.dataset.bulk)));
  $('#refresh').addEventListener('click', refresh);
  $('#editNames').addEventListener('click', toggleEdit);
  $('#conn').addEventListener('submit', connect);
  try {
    const cfg = await api('GET', '/api/config');
    $('#host').value = cfg.host; $('#port').value = cfg.port; $('#unit').value = cfg.unit;
    names = cfg.names;
    maps = cfg.maps || [];
    buildMaps();
  } catch (err) { toast(err.message); }
  render();
  refresh();
}
init();
