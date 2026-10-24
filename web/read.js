'use strict';

import { prepareSvg, rejectedNotice, wire, draft, mountLightbox } from './lib/diagram.mjs';
import { parseStem, stemOf, ghRaw, ghBlob, loadIndex, loadState, loadInstalls, installPhase, saveStateItem, stateItem, SURFACES, removeEntry, specRows, categoryLabel, STATE_TEXT, TRIED, VERDICTS, health } from './lib/library.mjs';

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
// One save path for 我的標記 and the install panel, so both repaint from the same mark.
function marker(cfg, stem, repoName, mark) {
  const listeners = [];
  return {
    mark,
    on: (fn) => listeners.push(fn),
    async save(patch, msgEl) {
      if (msgEl) msgEl.textContent = '儲存中…';
      try {
        Object.assign(mark, await saveStateItem(cfg, stem, patch, repoName));
        if (msgEl) msgEl.textContent = '已儲存。';
      } catch (e) {
        if (msgEl) msgEl.textContent = e.status === 403 ? '儲存失敗：token 沒有寫入權限。' : `儲存失敗（${e.status || '連線'}），稍後再試。`;
      }
      listeners.forEach((fn) => fn());
    },
  };
}

function markSection(m) {
  const box = el('div', 'marks');
  const msg = el('span', 'mmsg');
  const seg = el('div', 'tried'); seg.setAttribute('role', 'radiogroup'); seg.setAttribute('aria-label', '是否已試過');
  const owned = el('p', 'mmsg');
  const paint = () => {
    seg.querySelectorAll('button').forEach((b) => { b.disabled = false; b.setAttribute('aria-checked', String(b.textContent === m.mark.tried)); });
    box.dataset.tried = m.mark.tried;
    owned.textContent = m.mark.owned ? '你標記為「原本就裝了」。' : '';
  };
  for (const t of TRIED) {
    const b = el('button', null, t); b.type = 'button'; b.setAttribute('role', 'radio');
    b.onclick = () => { if (t !== m.mark.tried) { seg.querySelectorAll('button').forEach((x) => { x.disabled = true; }); m.save({ tried: t }, msg); } };
    seg.append(b);
  }
  m.on(paint);
  paint();
  box.append(el('span', 'lbl', '是否已試過'), seg, owned, msg);
  return section('我的標記', box);
}

function usageSection(rec) {
  const when = list(rec.when_to_use), how = list(rec.how_to_use);
  if (!when.length && !how.length) return null;
  const kids = [];
  if (when.length) kids.push(el('b', 'sublbl', '什麼時候用'), bullets(when));
  if (how.length) kids.push(el('b', 'sublbl', '怎麼用'), bullets(how));
  return section('什麼時候用、怎麼用', ...kids);
}

function copyRow(cmd) {
  const row = el('div', 'cmd');
  const b = el('button', 'copy', '複製'); b.type = 'button';
  b.onclick = async () => {
    try { await navigator.clipboard.writeText(cmd); b.textContent = '已複製'; } catch { b.textContent = '請長按選取'; }
    setTimeout(() => { b.textContent = '複製'; }, 1500);
  };
  row.append(el('code', null, cmd), b);
  return row;
}

function zipButton(cfg, path) {
  const name = path.split('/').pop();
  const b = el('button', 'linkish', `⬇ 下載 ${name}`); b.type = 'button';
  b.onclick = async () => {
    const r = await ghBlob(cfg, path);
    if (!r.blob) { alert(`下載失敗（${r.status || '連線'}）`); return; }
    const a = document.createElement('a'); a.href = URL.createObjectURL(r.blob); a.download = name;
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  };
  return b;
}

const PHASE_TEXT = {
  pending: '⏳ 處理中：GitHub 正在打包，約 1–3 分鐘，這頁會自動更新。',
  ready: '✅ 打包成功。GitHub Box 看不到你的 Claude 裡裝了什麼，請照下面三個地方各做一次，做完勾選。',
  partial: '⚠️ 部分成功，請看下面的說明。',
  problem: '❌ 沒有成功。',
};

// 確認安裝 → the install workflow builds the bundle → the owner finishes each surface and ticks it off.
function installSection(cfg, stem, rec, m) {
  const box = el('div', 'install');
  const installable = rec.installable && typeof rec.installable === 'object' && rec.installable.kind;
  const msg = el('span', 'mmsg');
  let timer = null, polls = 0;
  const render = async () => {
    clearTimeout(timer);
    const mark = m.mark;
    if (!installable) {
      box.replaceChildren(el('p', 'note', mark.owned ? '你標記為原本就裝了。這個 repo 不是 Claude 外掛或 skill，不用裝進 Claude。'
        : '這個 repo 不是 Claude 外掛或 skill，沒有可以裝進 Claude 的東西。'));
      return;
    }
    if (!mark.install) {
      const b = el('button', 'inst', '確認安裝到 Claude'); b.type = 'button';
      b.onclick = () => {
        if (!confirm(`確認安裝 ${text(rec.repo)}？\n會加進你的 Claude Code 套件清單，並打包給 Claude Chat／Cowork 上傳的 zip。第三方程式碼請先自己看過。`)) return;
        b.disabled = true; polls = 0; m.save({ install: true }, msg);
      };
      box.replaceChildren(b, msg);
      return;
    }
    const result = (await loadInstalls(cfg))[stem];
    const phase = installPhase(mark, result);
    const kids = [el('p', `phase ${phase}`, PHASE_TEXT[phase])];
    if (phase === 'pending') {
      if (polls++ < 15) timer = setTimeout(render, 20000);
      else kids.push(el('p', 'mmsg', '等太久了，可以到收藏庫的 Actions 看看 install 有沒有出錯。'));
    } else {
      for (const p of Array.isArray(result.problems) ? result.problems : []) kids.push(el('p', 'warnline', `⚠️ ${p}`));
      const skills = list(result.skills);
      if (skills.length) kids.push(el('p', 'mmsg', `安裝後的技能名稱：${skills.join('、')}`));
      const zips = list(result.zips).filter((z) => /^dist\/[a-z0-9._-]+__[a-z0-9._-]+\/[A-Za-z0-9_-]{1,64}\.zip$/.test(z));
      const done = mark.installed;
      const surface = (key, title, body) => {
        const s = el('div', 'surface'); s.dataset.done = String(done[key]);
        const cb = el('input'); cb.type = 'checkbox'; cb.checked = done[key];
        cb.onchange = () => { cb.disabled = true; m.save({ installed: { ...done, [key]: cb.checked }, ...(cb.checked ? { tried: '在用' } : {}) }, msg); };
        const lab = el('label', 'done'); lab.append(cb, ` 我在 ${title} 裝好了`);
        s.append(el('b', null, `${done[key] ? '✅' : '⬜'} ${title}`), ...body, lab);
        return s;
      };
      const code = [];
      if (typeof result.code_cmd === 'string' && result.code_cmd) {
        code.push(el('p', 'mmsg', '第一次使用（之後不用再做）：'), copyRow(`/plugin marketplace add ${cfg.repo}`),
          el('p', 'mmsg', '每次確認安裝後：'), copyRow('/plugin marketplace update github-box'), copyRow(result.code_cmd),
          el('p', 'mmsg', '裝完重新開啟 Claude Code，輸入 /plugin 可以看到它。'));
      } else if (typeof result.market_cmd === 'string' && result.market_cmd) {
        code.push(el('p', 'mmsg', '它自己就是套件市集：'), copyRow(result.market_cmd), el('p', 'mmsg', '再輸入 /plugin 選要裝的項目。'));
      } else code.push(el('p', 'mmsg', '這項沒有 Claude Code 版本。'));
      const chat = zips.length ? [ulOf(zips.map((z) => zipButton(cfg, z))),
        el('p', 'mmsg', '到 claude.ai › 設定 › Capabilities（功能）› Skills › 上傳技能，選這個 zip，再把它的開關打開。')]
        : [el('p', 'mmsg', '這項沒有可以上傳的 skill zip。')];
      const cowork = zips.length ? [el('p', 'mmsg', 'Cowork 用的是同一個 claude.ai 帳號的 Skills。Chat 上傳好之後，在 Cowork 開新任務，確認技能清單裡看得到它。')]
        : [el('p', 'mmsg', '這項沒有可以上傳的 skill zip。')];
      kids.push(surface('code', 'Claude Code', code), surface('chat', 'Claude Chat', chat), surface('cowork', 'Cowork', cowork));
      const n = SURFACES.filter(([k]) => done[k]).map(([, t]) => t);
      kids.push(el('p', 'summary', n.length ? `已安裝：${n.join('、')}（已自動標成「在用」）` : '還沒有在任何地方裝好。'));
    }
    const cancel = el('button', 'linkish', '取消確認安裝'); cancel.type = 'button';
    cancel.onclick = () => { if (confirm('從 GitHub Box 的安裝清單移除？已經裝進 Claude 的要自己移除。')) m.save({ install: false }, msg); };
    kids.push(cancel, msg);
    box.replaceChildren(...kids);
  };
  m.on(render);
  render();
  return section('安裝到 Claude', box);
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

function bullets(items) { const ul = el('ul', 'plain'); items.forEach((x) => ul.append(el('li', null, x))); return ul; }

// The find-skill report, in its fixed order: 結論 → 活躍度 → 能力邊界 → 應用場景 → 風險 → 待查證.
function verdictSection(rec) {
  const verdict = VERDICTS.includes(rec.verdict) ? rec.verdict : '';
  if (!verdict) return null;
  const head = el('p', 'verdict'); head.dataset.v = verdict;
  head.append(el('b', null, verdict), el('span', null, text(rec.verdict_reason)));
  const kids = [head];
  const act = rec.activity && typeof rec.activity === 'object' ? rec.activity : null;
  if (act) {
    const h = health(act);
    const pushed = typeof act.pushed_at === 'string' ? `${day(act.pushed_at)}（${act.days_since_push} 天前）` : '待查證';
    kids.push(el('p', h ? 'act warn' : 'act', `活躍度：最後更新 ${pushed}${h ? ` · ${h}` : ''} · 查詢於 ${day(act.checked_at)}`));
  }
  const groups = [['實際能力邊界', list(rec.capabilities)], ['對你的應用場景（推論）', list(rec.fit)],
    ['不適合的情況／風險（推論）', list(rec.risks)], ['待查證', list(rec.unverified)]];
  for (const [title, items] of groups) if (items.length) kids.push(el('b', 'sublbl', title), bullets(items));
  return section('能不能用', ...kids);
}

function tasksSection(rec) {
  const tasks = list(rec.tasks), areas = list(rec.task_areas);
  if (!tasks.length && !areas.length) return null;
  const kids = [];
  if (tasks.length) kids.push(bullets(tasks));
  if (areas.length) { const d = el('div', 'stack'); areas.forEach((a) => d.append(el('span', null, a))); kids.push(d); }
  return section('可用在哪些任務', ...kids);
}

function renderText(rec, legacy, extras = []) {
  const parts = [verdictSection(rec), usageSection(rec)].filter(Boolean);
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
  const ts = tasksSection(rec);
  if (ts) parts.push(ts);
  const t = legacy ? null : tabs(rec);
  if (t) parts.push(t);
  if (legacy || (!intro && !t)) parts.push(el('p', 'note', '這筆是舊格式，重新分析後會有完整內容。'));
  $('col').replaceChildren(...parts, ...extras.filter(Boolean));
}

// 看懂架構圖: the plain-language note plus a node table, shown under the figure and beside the zoomed diagram.
function guideNodes(rec) {
  return (Array.isArray(rec.diagram_nodes) ? rec.diagram_nodes : [])
    .filter((n) => n && typeof n.label === 'string' && typeof n.zh === 'string' && typeof n.role === 'string');
}

function buildGuide(rec) {
  const note = text(rec.diagram_note), nodes = guideNodes(rec);
  if (!note && !nodes.length) return [el('p', 'note', '這筆還沒有架構圖說明，重新分析後會出現節點的中文翻譯與作用。')];
  const kids = [el('h2', null, '看懂架構圖')];
  if (note) kids.push(el('p', 'gnote', note));
  if (nodes.length) {
    const t = el('table', 'spec nodes'); const body = el('tbody'); t.append(body);
    const head = el('tr'); head.append(el('th', null, '節點'), el('th', null, '中文'), el('th', null, '作用')); body.append(head);
    for (const n of nodes) {
      const tr = el('tr'); tr.dataset.label = n.label.trim().toLowerCase();
      tr.append(el('td', 'mono', n.label), el('td', null, n.zh), el('td', null, n.role));
      body.append(tr);
    }
    kids.push(t);
  }
  return kids;
}

let currentRec = {};

function renderGuide(rec) {
  currentRec = rec;
  $('guide').replaceChildren(...buildGuide(rec));
}

const nodeTitle = (g) => (g.querySelector('text')?.textContent || '').trim().toLowerCase();

// Tapping a node lights its row in the side panel; tapping a row lights the node, both ways.
function linkGuide(svg, panel) {
  const rows = [...panel.querySelectorAll('tr[data-label]')];
  const light = (label) => {
    rows.forEach((r) => r.classList.toggle('hit', r.dataset.label === label));
    rows.find((r) => r.dataset.label === label)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  for (const g of svg.querySelectorAll('g.node')) g.addEventListener('click', () => light(nodeTitle(g)));
  for (const r of rows) {
    r.onclick = () => {
      const g = [...svg.querySelectorAll('g.node')].find((x) => nodeTitle(x) === r.dataset.label);
      if (g) g.dispatchEvent(new MouseEvent('click', { bubbles: true })); else light(r.dataset.label);
    };
  }
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
    $('lb-guide').replaceChildren(...buildGuide(currentRec));
    $('lb-guide').scrollTop = 0;
    linkGuide(big, $('lb-guide'));
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
  const m = marker(cfg, stem, repo, mark);
  const extras = [markSection(m), installSection(cfg, stem, rec, m), relatedSection(idx, stem), sourceSection(rec)];
  renderText(rec, legacy, extras);
  renderDiagram(cfg, stem, svgRes);
  renderGuide(rec);

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
