'use strict';

import { loadIndex, loadState, mergeLibrary, matches, badges, categoryLabel, STATE_TEXT, TRIED } from './lib/library.mjs';

const CFG_KEY = 'repobox.cfg';
const RESERVED_OWNERS = new Set([
  'about', 'apps', 'codespaces', 'collections', 'copilot', 'enterprise', 'explore', 'features',
  'issues', 'join', 'login', 'logout', 'marketplace', 'new', 'notifications', 'orgs',
  'organizations', 'pricing', 'pulls', 'search', 'security', 'settings', 'site', 'sponsors',
  'topics', 'trending',
]);
const OWNER_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const REPO_SEG_RE = /^[A-Za-z0-9._-]+/;
const GITHUB_HOSTS = new Set(['github.com', 'www.github.com']);
// Only these link wrappers are unwrapped; any other host carrying a GitHub URL in its
// query (e.g. evil.example/?next=github.com/a/b) is rejected.
const WRAPPERS = new Map([
  ['l.threads.com', 'u'], ['l.threads.net', 'u'], ['l.facebook.com', 'u'], ['l.instagram.com', 'u'],
]);
// Bare (scheme-less) candidates must not follow URL characters, so a path or query segment
// like evil.example/github.com/a/b never starts a candidate.
const CANDIDATE_RE = /https?:\/\/[^\s<>"'()]+|(?<![\w.@\/:?=&%-])(?:www\.)?github\.com\/[^\s<>"'()]+/gi;

const $ = (id) => document.getElementById(id);

function repoFromUrl(candidate, depth = 0) {
  let url;
  try { url = new URL(/^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`); } catch { return null; }
  const host = url.hostname.toLowerCase();
  if (GITHUB_HOSTS.has(host)) {
    if (url.username || url.password) return null;
    const [owner = '', repoSeg = ''] = url.pathname.split('/').slice(1);
    if (!OWNER_RE.test(owner) || RESERVED_OWNERS.has(owner.toLowerCase())) return null;
    const m = repoSeg.match(REPO_SEG_RE);
    const repo = m ? m[0].replace(/\.+$/, '').replace(/\.git$/i, '') : '';
    if (!repo) return null;
    return { owner, repo, url: `https://github.com/${owner}/${repo}` };
  }
  const param = WRAPPERS.get(host);
  if (param && depth < 2) {
    const target = url.searchParams.get(param);
    if (target) return repoFromUrl(target, depth + 1);
  }
  return null;
}

function findGitHubRepo(...texts) {
  for (const raw of texts) {
    if (!raw) continue;
    for (const m of raw.matchAll(CANDIDATE_RE)) {
      const hit = repoFromUrl(m[0]);
      if (hit) return hit;
    }
  }
  return null;
}

function detectSource(host) {
  if (!host) return '';
  if (/(^|\.)threads\.(com|net)$/.test(host)) return 'threads';
  if (/(^|\.)(x|twitter)\.com$|^t\.co$/.test(host)) return 'x';
  if (/(^|\.)youtube\.com$|^youtu\.be$/.test(host)) return 'youtube';
  return host;
}

function loadCfg() {
  try { return JSON.parse(localStorage.getItem(CFG_KEY)) || null; } catch { return null; }
}

function saveCfg(cfg) {
  try { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); return true; } catch { return false; }
}

const pad = (n, w = 2) => String(n).padStart(w, '0');

function makeId(d) {
  const rnd = crypto.getRandomValues(new Uint16Array(1))[0].toString(16).padStart(4, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}-${rnd}`;
}

function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
}

function b64utf8(s) {
  let bin = '';
  for (const b of new TextEncoder().encode(s)) bin += String.fromCharCode(b);
  return btoa(bin);
}

const HISTORY_KEY = 'repobox.history';
const HISTORY_MAX = 20;

function setStatus(text, cls = '') {
  $('status').textContent = text;
  $('block').dataset.state = cls || 'idle';
}

function setRepo(name) { $('block-repo').textContent = name || ''; }
function setHint(text) { $('hint').textContent = text || ''; }
function clearActions() { $('block-actions').replaceChildren(); }

function addAction(label, onClick, primary = false) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = primary ? 'btn small primary' : 'btn small';
  btn.textContent = label;
  btn.onclick = () => { clearActions(); onClick(); };
  $('block-actions').append(btn);
}

async function submit(hit, ctx = {}) {
  const cfg = loadCfg();
  setRepo(`${hit.owner}/${hit.repo}`);
  clearActions();
  if (!cfg || !cfg.repo || !cfg.token) {
    setStatus('還沒連結', 'err');
    setHint('先連結收藏庫，連結後按「重試」。');
    addAction('重試', () => submit(hit, ctx), true);
    openDrawer();
    return;
  }
  setStatus('送出中', 'busy');
  setHint('');
  const now = new Date();
  const id = makeId(now);
  const capture = {
    v: 1, url: hit.url, captured_at: isoLocal(now), source: ctx.source || '',
    page_url: ctx.page_url || '', note: '', client: 'pwa@1',
  };
  try {
    const res = await fetch(`https://api.github.com/repos/${cfg.repo}/contents/inbox/${id}.json`, {
      method: 'PUT',
      headers: ghHeaders(cfg),
      body: JSON.stringify({
        message: `capture: ${hit.owner}/${hit.repo}`,
        content: b64utf8(JSON.stringify(capture, null, 2) + '\n'),
      }),
    });
    const totalMs = Math.round(performance.now());
    if (res.ok) {
      setStatus('已收', 'ok');
      setHint(`${(totalMs / 1000).toFixed(1)} 秒，分析約需 3–8 分鐘，完成後會出現在書庫。`);
      addHistory({ id, repo: `${hit.owner}/${hit.repo}`, lib: cfg.repo, at: now.toISOString(), state: 'pending' });
      renderLibrary();
      schedulePoll();
      if (window.opener) setTimeout(() => window.close(), 1500);
    } else {
      const body = await res.json().catch(() => ({}));
      failWith(`GitHub 回應 ${res.status}${body.message ? `：${body.message}` : ''}`, hit, ctx);
    }
  } catch (e) {
    failWith(`連不到 GitHub（${e.message}）`, hit, ctx);
  }
}

function failWith(message, hit, ctx) {
  setStatus('沒收到', 'err');
  setHint(message);
  addAction('重試', () => submit(hit, ctx), true);
}

function ghHeaders(cfg) {
  return {
    Authorization: `Bearer ${cfg.token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

function loadHistory() {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY));
    return Array.isArray(h) ? h.filter((x) => x && typeof x.id === 'string' && typeof x.repo === 'string') : [];
  } catch { return []; }
}

function saveHistory(h) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, HISTORY_MAX))); } catch { /* storage blocked */ }
}

function addHistory(item) { saveHistory([item, ...loadHistory().filter((x) => x.id !== item.id)]); }

function ago(iso) {
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (mins < 1) return '剛剛';
  if (mins < 60) return `${mins} 分鐘前`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours} 小時前` : `${Math.round(hours / 24)} 天前`;
}

function historyFor(cfg) {
  return loadHistory().filter((x) => cfg && x.lib === cfg.repo);
}

// The list shows the whole library (index.json) plus local captures still being analyzed.
const lib = { state: 'ok', index: null, repo: null, marks: {} };
let libSeq = 0;

// Only the latest request for the currently configured repo may update the list.
async function loadLib() {
  const cfg = loadCfg();
  const seq = ++libSeq;
  if (!cfg || !cfg.token) { Object.assign(lib, { state: 'ok', index: null, repo: null }); renderLibrary(); return; }
  if (lib.repo !== cfg.repo) { Object.assign(lib, { state: 'ok', index: null, repo: cfg.repo }); renderLibrary(); }
  const [result, marks] = await Promise.all([loadIndex(cfg), loadState(cfg)]);
  const now = loadCfg();
  if (seq !== libSeq || !now || now.repo !== cfg.repo) return;
  Object.assign(lib, result, { repo: cfg.repo, marks: marks.items });
  renderLibrary();
}

let libFilter = '';
let libQuery = '';
const PENDING = '__pending', FAILED = '__failed', TRIED_KEY = '__tried:', INSTALLED = '__installed';

function card(href, external, cls, title, repo, chips) {
  const a = document.createElement('a');
  a.className = cls ? `card ${cls}` : 'card';
  a.href = href;
  if (external) { a.target = '_blank'; a.rel = 'noopener'; }
  const tl = document.createElement('span'); tl.className = 'tl'; tl.textContent = title;
  const rp = document.createElement('span'); rp.className = 'rp'; rp.textContent = repo;
  a.append(tl, rp);
  if (chips.length) {
    const bd = document.createElement('span'); bd.className = 'bd';
    for (const c of chips) { const s = document.createElement('span'); s.textContent = c; bd.append(s); }
    a.append(bd);
  }
  return a;
}

function catButton(key, label, count) {
  const b = document.createElement('button');
  b.type = 'button';
  b.setAttribute('aria-pressed', String(libFilter === key));
  const n = document.createElement('span'); n.textContent = String(count);
  b.append(label, ' ', n);
  b.onclick = () => { libFilter = key; renderLibrary(); };
  return b;
}

// Overview strip: totals for the whole library, independent of the search box and the chosen category.
function renderStats(all) {
  if (!all.length) { $('stats').replaceChildren(); return; }
  const weekAgo = Date.now() - 7 * 86400000;
  const rows = [['收藏', all.length], ['本週新增', all.filter((it) => Date.parse(it.last_seen) >= weekAgo).length],
    ...TRIED.map((t) => [t, all.filter((it) => it.tried === t).length]), ['可安裝', all.filter((it) => it.installable).length],
    ['已確認安裝', all.filter((it) => it.install).length]];
  $('stats').replaceChildren(...rows.filter(([k, n]) => n || k === '收藏').map(([k, n]) => {
    const s = document.createElement('span'); const b = document.createElement('b'); b.textContent = String(n); s.append(k, b); return s;
  }));
}

// Category index (全部, each category by size, then 分析中/失敗) and the cards for the chosen one.
function renderLibrary() {
  const cfg = loadCfg();
  const note = $('lib-note');
  note.textContent = lib.state === 'ok' || lib.state === 'empty' ? '' : STATE_TEXT[lib.state];
  const index = cfg && lib.repo === cfg.repo ? lib.index : null;
  const items = cfg ? mergeLibrary(index, historyFor(cfg), cfg.repo, lib.marks) : [];
  renderStats(items.filter((it) => it.kind === 'entry'));
  const entries = items.filter((it) => it.kind === 'entry' && matches(it, libQuery));
  const pending = items.filter((it) => it.kind === 'pending');
  const failed = items.filter((it) => it.kind === 'failed');
  const counts = new Map();
  for (const it of entries) { const k = it.category || 'other'; counts.set(k, (counts.get(k) || 0) + 1); }
  const triedCounts = TRIED.slice(1).map((t) => [t, entries.filter((it) => it.tried === t).length]).filter(([, n]) => n);
  const installedN = entries.filter((it) => it.install).length;
  const known = new Set(['', PENDING, FAILED, ...counts.keys(), ...triedCounts.map(([t]) => TRIED_KEY + t), ...(installedN ? [INSTALLED] : [])]);
  if (!known.has(libFilter) || (libFilter === PENDING && !pending.length) || (libFilter === FAILED && !failed.length)) libFilter = '';

  const cats = [catButton('', '全部', entries.length)];
  const label = (k) => categoryLabel(k) || k;
  for (const [k, n] of [...counts].sort((a, b) => b[1] - a[1] || label(a[0]).localeCompare(label(b[0]), 'zh-Hant'))) cats.push(catButton(k, label(k), n));
  if (triedCounts.length || installedN) { const sep = document.createElement('i'); sep.className = 'sep'; cats.push(sep); }
  for (const [t, n] of triedCounts) cats.push(catButton(TRIED_KEY + t, t, n));
  if (installedN) cats.push(catButton(INSTALLED, '已確認安裝', installedN));
  if (pending.length || failed.length) { const sep = document.createElement('i'); sep.className = 'sep'; cats.push(sep); }
  if (pending.length) cats.push(catButton(PENDING, '分析中', pending.length));
  if (failed.length) cats.push(catButton(FAILED, '失敗', failed.length));
  $('cats').replaceChildren(...(items.length ? cats : []));

  if (!entries.length && !pending.length && !failed.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = cfg ? STATE_TEXT.empty : '連結收藏庫之後，你的書庫會列在這裡。';
    if (cfg && libQuery) p.textContent = `沒有符合「${libQuery}」的收藏。`;
    $('recent').replaceChildren(p);
    return;
  }
  const gh = `https://github.com/${cfg.repo}`;
  const pendingCards = () => pending.map((it) => card(`${gh}/actions`, true, 'pending', it.repo, `分析中 · ${ago(it.at)}`, []));
  const failedCards = () => failed.map((it) => card(`${gh}/blob/main/inbox/failed/${it.id}.json`, true, 'failed', it.repo, `分析失敗 · ${ago(it.at)}`, []));
  const chips = (it) => [...(it.tried !== '未試' ? [it.tried] : []), ...(it.install ? ['已安裝'] : []), ...badges(it.requirements)].slice(0, 4);
  const entryCards = (list) => list.map((it) => card(`read.html#${it.stem}`, false, '', it.tagline || it.intro || it.repo, it.purpose ? `${it.repo} · ${it.purpose}` : it.repo, chips(it)));
  let cards;
  if (libFilter === PENDING) cards = pendingCards();
  else if (libFilter === FAILED) cards = failedCards();
  else if (libFilter === INSTALLED) cards = entryCards(entries.filter((it) => it.install));
  else if (libFilter.startsWith(TRIED_KEY)) cards = entryCards(entries.filter((it) => it.tried === libFilter.slice(TRIED_KEY.length)));
  else if (libFilter) cards = entryCards(entries.filter((it) => (it.category || 'other') === libFilter));
  else cards = [...pendingCards(), ...failedCards(), ...entryCards(entries)];
  $('recent').replaceChildren(...cards);
}

// Coupled with publish.py: a processed capture moves to inbox/done/ or inbox/failed/ under the same name.
async function refreshStates() {
  const cfg = loadCfg();
  if (!cfg || !cfg.token) return;
  const pending = historyFor(cfg).filter((x) => x.state === 'pending');
  if (!pending.length) return;
  const api = `https://api.github.com/repos/${cfg.repo}/contents`;
  const exists = async (path) => {
    try { return (await fetch(`${api}/${path}`, { method: 'GET', headers: ghHeaders(cfg) })).ok; } catch { return false; }
  };
  const updates = new Map();
  for (const item of pending) {
    if (await exists(`inbox/done/${item.id}.json`)) updates.set(item.id, 'done');
    else if (await exists(`inbox/failed/${item.id}.json`)) updates.set(item.id, 'failed');
  }
  if (!updates.size) return;
  // Re-read: a capture may have been added while the requests were in flight.
  const latest = loadHistory();
  for (const item of latest) if (updates.has(item.id) && item.lib === cfg.repo) item.state = updates.get(item.id);
  saveHistory(latest);
  if ([...updates.values()].includes('done')) await loadLib();
  else renderLibrary();
}

let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  const cfg = loadCfg();
  if (document.hidden || !historyFor(cfg).some((x) => x.state === 'pending')) return;
  pollTimer = setTimeout(async () => { await refreshStates(); schedulePoll(); }, 60000);
}

function openDrawer() {
  const d = $('drawer');
  if (!d.open) { if (d.showModal) d.showModal(); else d.setAttribute('open', ''); }
}

function closeDrawer() { const d = $('drawer'); if (d.open) d.close ? d.close() : d.removeAttribute('open'); }

function renderConn(cfg) {
  const ok = Boolean(cfg && cfg.repo && cfg.token);
  $('conn').dataset.ok = ok ? '1' : '0';
  $('conn').querySelector('span').textContent = ok ? cfg.repo.split('/')[1] : '尚未設定';
  $('library').href = ok ? `https://github.com/${cfg.repo}` : '#';
}

function drawerMessage(text, isError) {
  const p = $('drawer').querySelector('p');
  p.textContent = text;
  p.style.color = isError ? 'var(--err)' : '';
}

function init() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  let cfg = loadCfg();
  if (cfg) { $('repo').value = cfg.repo || ''; $('token').value = cfg.token ? '********' : ''; }
  const base = location.origin + location.pathname;
  renderBookmarklet(base, cfg);
  renderConn(cfg);
  loadLib();

  $('conn').onclick = openDrawer;
  $('drawer-close').onclick = closeDrawer;
  $('drawer').addEventListener('click', (e) => {
    const r = $('drawer').getBoundingClientRect();
    const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    if (e.target === $('drawer') && outside) closeDrawer();
  });
  $('library').onclick = (e) => { if (!loadCfg()) { e.preventDefault(); openDrawer(); } };

  $('settings').onsubmit = (e) => {
    e.preventDefault();
    const repo = $('repo').value.trim();
    const tokenInput = $('token').value.trim();
    if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(repo)) { drawerMessage('收藏庫格式應為「帳號/repo 名稱」。', true); return; }
    const token = tokenInput === '********' ? (cfg && cfg.token) : tokenInput;
    if (!token) { drawerMessage('請貼上 token。', true); return; }
    const next = { repo, token, nonce: (cfg && cfg.nonce) || randomHex(16) };
    if (!saveCfg(next)) { drawerMessage('無法儲存：這個瀏覽器封鎖了本機儲存。', true); return; }
    cfg = next;
    $('token').value = '********';
    drawerMessage('已儲存。', false);
    renderBookmarklet(base, cfg);
    renderConn(cfg);
    loadLib();
    setTimeout(closeDrawer, 600);
  };

  $('q').oninput = () => { libQuery = $('q').value; renderLibrary(); };

  $('add').onsubmit = (e) => {
    e.preventDefault();
    const hit = findGitHubRepo($('add-url').value);
    if (!hit) { setRepo(''); setStatus('沒找到連結', 'err'); setHint('這段文字裡沒有 GitHub repo 連結。'); return; }
    $('add-url').value = '';
    submit(hit, { source: 'manual' });
  };

  if (!cfg || !cfg.token) openDrawer();
  handleIncoming(base, cfg);
  refreshStates().then(schedulePoll);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshStates().then(schedulePoll);
  });
}

// Auto-write only when provenance is proven; everything else needs an explicit tap.
// - Share sheet: manifest POST -> service worker stores a single-use handoff -> #s=<id>,
//   accepted only inside the installed app window. A crafted link can only GET, so it
//   cannot mint a handoff id.
// - Bookmarklet: #k=<nonce>; the bookmarklet runs only on github.com, so no other page
//   ever sees the nonce.
// - Plain ?url= / #url= links: always confirm.
async function handleIncoming(base, cfg) {
  const q = new URLSearchParams(location.search);
  const h = new URLSearchParams(location.hash.slice(1));
  let shared = null;
  let trusted = false;
  if (h.has('s')) {
    // A cross-site form can also POST to ./share, but it lands in a browser tab;
    // only the OS share sheet delivers a POST into the installed app window.
    shared = await takeHandoff(h.get('s'));
    trusted = Boolean(shared) && matchMedia('(display-mode: standalone)').matches;
  } else if (h.has('url')) {
    shared = { url: h.get('url'), ref: h.get('ref') };
    trusted = Boolean(cfg && cfg.nonce && h.get('k') === cfg.nonce);
  } else if (q.has('url') || q.has('text') || q.has('title')) {
    shared = { title: q.get('title'), text: q.get('text'), url: q.get('url') };
  }
  if (location.search || location.hash) history.replaceState(null, '', base);
  if (!shared) return;
  $('received').textContent = JSON.stringify(shared, null, 2);
  const hit = findGitHubRepo(shared.url, shared.text, shared.title);
  if (!hit) {
    setStatus('沒找到連結', 'err');
    setHint('分享的內容裡沒有 GitHub repo 網址。');
    return;
  }
  const ctx = { source: detectSource(shared.ref || '') };
  if (trusted) { submit(hit, ctx); return; }
  setRepo(`${hit.owner}/${hit.repo}`);
  setStatus('待確認', 'ask');
  setHint('這個連結不是從分享選單或你的書籤來的，確認後才收。');
  addAction('確認收藏', () => submit(hit, ctx), true);
}

// Coupled with sw.js: same cache name and key path; the entry is deleted on first read.
async function takeHandoff(id) {
  if (!/^[0-9a-f-]{36}$/.test(id || '') || !('caches' in self)) return null;
  try {
    const cache = await caches.open('repobox-handoff');
    const key = new URL(`handoff/${id}`, location.href).href;
    const res = await cache.match(key);
    if (!res) return null;
    await cache.delete(key);
    return await res.json();
  } catch { return null; }
}

function randomHex(bytes) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, '0')).join('');
}

// iOS has no web share target, so a Shortcut opens this URL with the shared link appended.
function renderShortcut(base, cfg) {
  $('shortcut-url').textContent = cfg && cfg.nonce ? `${base}#k=${cfg.nonce}&ref=ios&url=` : '（先儲存設定）';
}

function renderBookmarklet(base, cfg) {
  renderShortcut(base, cfg);
  const el = $('bookmarklet');
  if (!cfg || !cfg.nonce) { el.removeAttribute('href'); el.textContent = '（先儲存設定）'; return; }
  el.textContent = '收進 GitHub Box';
  el.href = "javascript:(function(){if(location.hostname!=='github.com'){alert('GitHub Box: open a GitHub repo page first');return}" +
    "var r='';try{r=new URL(document.referrer).hostname}catch(e){}" +
    "window.open('" + base + "#k=" + cfg.nonce + "&url='+encodeURIComponent(location.href)+'&ref='+encodeURIComponent(r)," +
    "'_blank','width=420,height=360')})()";
}
init();
