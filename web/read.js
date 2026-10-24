'use strict';

import { prepareSvg, rejectedNotice, wire, draft, mountLightbox } from './lib/diagram.mjs';
import { parseStem, stemOf, ghRaw, ghBlob, listZips, loadIndex, loadState, saveStateItem, stateItem, removeEntry, specRows, categoryLabel, STATE_TEXT, TRIED } from './lib/library.mjs';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const lightbox = mountLightbox($('lightbox'));

// Coupled with app.js: same localStorage key and shape.
function loadCfg() {
  try { return JSON.parse(localStorage.getItem('repobox.cfg')) || null; } catch { return null; }
}

function showMessage(text) {
  for (const id of ['tblock', 'read']) $(id).hidden = true;
  $('msg').replaceChildren(el('p', null, text));
  $('msg').hidden = false;
  document.title = 'GitHub Box';
}

const pad = (n) => String(n).padStart(2, '0');
function day(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function lastSeen(rec) {
  const times = (Array.isArray(rec.sightings) ? rec.sightings : []).map((s) => s && s.at).filter(Boolean);
  if (times.length) return times.reduce((a, b) => (Date.parse(b) > Date.parse(a) ? b : a));
  return rec.last_seen || rec.analyzed_at || '';
}
const list = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string' && x) : []);
const text = (v) => (typeof v === 'string' ? v : '');

function cell(label, value) { const d = el('div', 'cell'); d.append(el('span', 'lbl', label), el('span', 'val', value)); return d; }
function section(title, ...kids) { const s = el('section', 'sec'); s.append(el('h2', null, title), ...kids); return s; }

function specTable(lines) {
  const t = el('table', 'spec'); const body = el('tbody'); t.append(body);
  for (const [label, value] of specRows(lines)) {
    const tr = el('tr');
    if (label) tr.append(el('th', null, label), el('td', null, value));
    else { const td = el('td', null, value); td.colSpan = 2; tr.append(td); }
    body.append(tr);
  }
  return t;
}

function tabs(rec) {
  const views = {};
  const highlights = list(rec.highlights), stack = list(rec.stack), summary = text(rec.summary);
  if (highlights.length) views['值得借鏡'] = () => { const ul = el('ul'); highlights.forEach((h) => ul.append(el('li', null, h))); return ul; };
  if (summary) views['技術摘要'] = () => el('p', null, summary);
  if (stack.length) views['技術棧'] = () => { const d = el('div', 'stack'); stack.forEach((s) => d.append(el('span', null, s))); return d; };
  const names = Object.keys(views);
  if (!names.length) return null;
  const box = el('div', 'more'); const seg = el('div', 'seg'); seg.setAttribute('role', 'tablist');
  const panel = el('div', 'panel'); panel.setAttribute('role', 'tabpanel');
  const fade = () => panel.classList.toggle('has-more', panel.scrollTop + panel.clientHeight < panel.scrollHeight - 4);
  panel.addEventListener('scroll', fade);
  const show = (name) => {
    panel.replaceChildren(views[name]());
    panel.scrollTop = 0;
    seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', String(b.textContent === name)));
    requestAnimationFrame(fade);
  };
  for (const name of names) {
    const b = el('button', null, name); b.type = 'button'; b.setAttribute('role', 'tab'); b.onclick = () => show(name);
    seg.append(b);
  }
  box.append(seg, panel);
  show(names[0]);
  return box;
}

const SRC_RE = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._\/-]{1,200}$/;

function link(href, label) { const a = el('a', null, label); a.href = href; a.target = '_blank'; a.rel = 'noopener'; return a; }

function ulOf(nodes) { const ul = el('ul', 'plain'); for (const n of nodes) { const li = el('li'); li.append(n); ul.append(li); } return ul; }

// 我的標記: 是否已試過 and 確認安裝, saved to state.json; 確認安裝 only for repos that hold a Claude plugin or skill.
function markSection(cfg, stem, rec, mark) {
  const box = el('div', 'marks');
  const msg = el('span', 'mmsg');
  const seg = el('div', 'tried'); seg.setAttribute('role', 'radiogroup'); seg.setAttribute('aria-label', '是否已試過');
  const repoName = text(rec.repo) || stem;
  const save = async (patch, btn) => {
    box.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    msg.textContent = '儲存中…';
    try {
      Object.assign(mark, await saveStateItem(cfg, stem, patch, repoName));
      msg.textContent = patch.install === true ? '已送出，約 1–3 分鐘後 INSTALL.md 與 zip 會更新。' : '已儲存。';
    } catch (e) {
      msg.textContent = e.status === 403 ? '儲存失敗：token 沒有寫入權限。' : `儲存失敗（${e.status || '連線'}），稍後再試。`;
    }
    paint();
  };
  const installable = rec.installable && typeof rec.installable === 'object' && rec.installable.kind;
  const inst = el('button', 'inst'); inst.type = 'button';
  const paint = () => {
    seg.querySelectorAll('button').forEach((b) => { b.disabled = false; b.setAttribute('aria-checked', String(b.textContent === mark.tried)); });
    inst.disabled = !installable;
    inst.textContent = !installable ? '不是 Claude 外掛／skill' : mark.install ? '✓ 已確認安裝（按一下取消）' : '確認安裝到 Claude';
    inst.setAttribute('aria-pressed', String(mark.install));
  };
  for (const t of TRIED) {
    const b = el('button', null, t); b.type = 'button'; b.setAttribute('role', 'radio');
    b.onclick = () => { if (t !== mark.tried) save({ tried: t }, b); };
    seg.append(b);
  }
  inst.onclick = () => {
    if (!mark.install && !confirm(`確認安裝 ${repoName}？\n會加進你的 Claude Code 套件清單，並打包給 Claude Chat／Cowork 上傳的 zip。第三方程式碼請先自己看過。`)) return;
    save({ install: !mark.install }, inst);
  };
  paint();
  box.append(el('span', 'lbl', '是否已試過'), seg, inst, msg);
  return section('我的標記', box);
}

async function zipSection(cfg, stem) {
  const zips = await listZips(cfg, stem);
  if (!zips.length) return null;
  const btns = zips.map((path) => {
    const b = el('button', 'linkish', `下載 ${path.split('/').pop()}`); b.type = 'button';
    b.onclick = async () => {
      const r = await ghBlob(cfg, path);
      if (!r.blob) { alert(`下載失敗（${r.status || '連線'}）`); return; }
      const a = document.createElement('a'); a.href = URL.createObjectURL(r.blob); a.download = path.split('/').pop();
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    };
    return b;
  });
  const p = el('p', 'note', '到 claude.ai › 設定 › Capabilities › Skills 上傳，Chat 與 Cowork 都能用。');
  return section('給 Claude Chat／Cowork', ulOf(btns), p);
}

function sourceSection(rec) {
  const full = text(rec.repo);
  if (!/^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+$/.test(full)) return null;
  const links = [link(`https://github.com/${full}`, `${full}（GitHub 首頁）`)];
  for (const p of list(rec.sources).filter((x) => SRC_RE.test(x))) links.push(link(`https://github.com/${full}/blob/HEAD/${p}`, p));
  for (const s of Array.isArray(rec.sightings) ? rec.sightings : []) {
    if (s && typeof s.page === 'string' && /^https:\/\//.test(s.page)) links.push(link(s.page, `在這裡看到的（${day(s.at)}）`));
  }
  return section('原始出處（回頭核對用）', ulOf(links));
}

function relatedSection(idx, stem) {
  if (!idx || !Array.isArray(idx.entries)) return null;
  const me = idx.entries.find((e) => e && stemOf(e.md) === stem);
  const rel = me && Array.isArray(me.related) ? me.related : [];
  const byMd = new Map(idx.entries.filter((e) => e && typeof e.md === 'string').map((e) => [e.md, e]));
  const links = rel.map((md) => byMd.get(md)).filter((e) => e && stemOf(e.md)).map((e) => {
    const a = el('a', null, `${e.repo}${typeof e.tagline === 'string' && e.tagline ? ` — ${e.tagline}` : ''}`);
    a.href = `read.html#${stemOf(e.md)}`;
    return a;
  });
  return links.length ? section('相關收藏', ulOf(links)) : null;
}

function renderText(rec, legacy, extras = []) {
  const parts = [];
  const intro = text(rec.intro), examples = list(rec.examples), reqs = list(rec.requirements);
  const purpose = text(rec.purpose), scenarios = list(rec.scenarios);
  if (purpose || scenarios.length) {
    const kids = [];
    if (purpose) kids.push(el('p', 'lead', purpose));
    if (scenarios.length) { const ul = el('ul', 'plain'); scenarios.forEach((x) => ul.append(el('li', null, x))); kids.push(el('b', 'sublbl', '適用情境'), ul); }
    parts.push(section('用途', ...kids));
  }
  if (intro) {
    // Long intros clamp to four lines and only the first example shows (user call 2026-10-19), so the tabs keep room.
    const lead = el('p', 'lead clamp', intro);
    const kids = [lead];
    const more = el('button', 'linkish', '展開'); more.type = 'button'; more.hidden = true;
    more.onclick = () => { lead.classList.remove('clamp'); more.hidden = true; };
    kids.push(more);
    const measure = () => { if (lead.classList.contains('clamp')) more.hidden = lead.scrollHeight <= lead.clientHeight + 1; };
    new ResizeObserver(measure).observe(lead);
    if (examples.length) {
      const p = el('p', 'eg'); p.append(el('b', null, '例如'), el('span', null, examples[0]));
      const egs = el('div', 'egs'); egs.append(p);
      kids.push(egs);
    }
    parts.push(section('這是什麼', ...kids));
  }
  if (reqs.length) parts.push(section('使用門檻', specTable(reqs)));
  const t = legacy ? null : tabs(rec);
  if (t) parts.push(t);
  if (legacy || (!intro && !t)) parts.push(el('p', 'note', '這筆是舊格式，重新分析後會有完整內容。'));
  $('col').replaceChildren(...parts, ...extras.filter(Boolean));
}

function renderDiagram(cfg, stem, svgRes) {
  const fig = $('fig');
  fig.classList.remove('zoomable'); fig.onclick = null; fig.onkeydown = null; fig.removeAttribute('tabindex'); fig.removeAttribute('role');
  if (svgRes.status === 404) { fig.replaceChildren(el('p', 'nodia', '這筆沒有架構圖。')); return; }
  if (svgRes.status !== 200) { fig.replaceChildren(el('p', 'nodia', '架構圖載入失敗，稍後再試。')); return; }
  const svg = prepareSvg(svgRes.text, 'h');
  if (!svg) { fig.replaceChildren(rejectedNotice(document, `https://github.com/${cfg.repo}/blob/main/library/${stem}.svg`)); return; }
  fig.replaceChildren(svg, el('span', 'hint', '點圖放大'));
  fig.classList.add('zoomable');
  fig.setAttribute('role', 'button');
  fig.tabIndex = 0;
  const zoom = () => {
    const big = prepareSvg(svgRes.text, 'v');
    if (!big) return;
    wire(big, lightbox.isDrag);
    lightbox.open(big);
  };
  fig.onclick = zoom;
  fig.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); zoom(); } };
  draft(svg);
}

function removeButton(cfg, stem, repo) {
  const b = el('button', 'rm', '移除'); b.type = 'button';
  b.onclick = async () => {
    if (!confirm(`從書庫移除 ${repo}？\n介紹和架構圖會一起刪掉；之後再收這個 repo 會重新分析。`)) return;
    b.disabled = true; b.textContent = '移除中…';
    try {
      await removeEntry(cfg, stem, repo);
      location.replace('./');
    } catch (e) {
      b.disabled = false; b.textContent = '移除';
      alert(e.status === 401 ? `移除失敗：${STATE_TEXT.auth}` : e.status === 403 ? '移除失敗：token 沒有這個收藏庫的寫入權限。' :
        e.status ? `移除失敗（GitHub 回應 ${e.status}），稍後再試。` : `移除失敗：${STATE_TEXT.unavailable}`);
    }
  };
  return b;
}

function renderRecord(cfg, stem, rec, svgRes, legacy, idx, mark) {
  const repo = text(rec.repo) || stem;
  const h1 = el('h1', null, repo); h1.title = repo;
  const head = el('div', 'head'); head.append(h1);
  if (text(rec.tagline)) head.append(el('p', 'sub', rec.tagline));
  const parts = [head, cell('分類', categoryLabel(text(rec.category)) || '—'), cell('授權', text(rec.license) || '—'),
    cell('收藏日', day(lastSeen(rec)))];
  if (/^https:\/\/github\.com\//.test(text(rec.url))) {
    const gh = el('a', 'gh', 'GitHub ↗'); gh.href = rec.url; gh.target = '_blank'; gh.rel = 'noopener';
    parts.push(gh);
  }
  parts.push(removeButton(cfg, stem, repo));
  $('tblock').replaceChildren(...parts);
  $('msg').hidden = true;
  $('tblock').hidden = false;
  $('read').hidden = false;
  document.title = `${repo} · GitHub Box`;
  const extras = [markSection(cfg, stem, rec, mark), relatedSection(idx, stem), sourceSection(rec)];
  renderText(rec, legacy, extras);
  renderDiagram(cfg, stem, svgRes);
  zipSection(cfg, stem).then((z) => { if (z && parseStem(location.hash) === stem) $('col').append(z); });
}

let generation = 0;

async function load() {
  const gen = ++generation;
  const stem = parseStem(location.hash);
  if (!stem) { showMessage('找不到這筆收藏。'); return; }
  const cfg = loadCfg();
  if (!cfg || !cfg.repo || !cfg.token) { showMessage('先到收藏頁連結收藏庫。'); return; }
  const [side, svgRes, idx, st] = await Promise.all([
    ghRaw(cfg, `library/${stem}.json`), ghRaw(cfg, `library/${stem}.svg`), loadIndex(cfg), loadState(cfg),
  ]);
  const mark = stateItem(st.items, stem);
  const index = idx.state === 'ok' ? idx.index : null;
  // A newer navigation (hashchange) or a settings change makes this result stale.
  const now = loadCfg();
  if (gen !== generation || parseStem(location.hash) !== stem || !now || now.repo !== cfg.repo) return;
  if (side.status === 200) {
    let rec = null;
    try { rec = JSON.parse(side.text); } catch { /* handled below */ }
    if (!rec || typeof rec !== 'object' || Array.isArray(rec)) { showMessage(STATE_TEXT['bad-data']); return; }
    renderRecord(cfg, stem, rec, svgRes, false, index, mark);
    return;
  }
  if (side.status === 401 || side.status === 403) { showMessage(STATE_TEXT.auth); return; }
  if (side.status === 404) {
    // Entries written before sidecars existed are still listed in index.json.
    const entry = idx.state === 'ok' ? idx.index.entries.find((e) => e && stemOf(e.md) === stem) : null;
    if (entry) { renderRecord(cfg, stem, entry, svgRes, true, index, mark); return; }
    showMessage(idx.state === 'auth' || idx.state === 'no-repo' ? STATE_TEXT[idx.state] : '找不到這筆收藏。');
    return;
  }
  showMessage(STATE_TEXT.unavailable);
}

addEventListener('hashchange', load);
load();
