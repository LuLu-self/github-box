// Library data for the capture and reading pages: index loading, entry reads and the merged list.
// Coupled with action/scripts/index.py (index.json shape) and publish.py (library/<stem>.md|json|svg).

export const STEM_RE = /^[a-z0-9._-]+__[a-z0-9._-]+$/;
const API = 'https://api.github.com/repos';

export const CATEGORY_LABEL = { 'agent-framework': 'Agent 框架', 'mcp-server': 'MCP 伺服器', 'dev-tool': '開發工具',
  'model-inference': '模型推論', 'data-processing': '資料處理', frontend: '前端', infrastructure: '基礎設施', game: '遊戲',
  'desktop-app': '桌面應用', other: '其他' };

// Category names come from a user-edited taxonomy and from index.json, so never read inherited members.
export function categoryLabel(key) {
  return Object.hasOwn(CATEGORY_LABEL, key) ? CATEGORY_LABEL[key] : String(key ?? '');
}

export const STATE_TEXT = {
  empty: '書庫還是空的。分享或貼上一個 GitHub repo 連結，分析完會出現在這裡。',
  'no-repo': '找不到收藏庫，或 token 沒有它的權限。請到設定確認收藏庫名稱與 token。',
  auth: 'token 失效，請到設定重新貼上。',
  unavailable: '暫時連不到 GitHub，稍後再試。',
  'bad-data': '書庫目錄格式錯誤，下一次分析完成時會自動重建。',
};

export function parseStem(hash) {
  let s = String(hash || '').replace(/^#/, '');
  try { s = decodeURIComponent(s); } catch { return null; }
  return s.length <= 200 && STEM_RE.test(s) ? s : null;
}

export function stemOf(mdPath) {
  const m = /^library\/([^/]+)\.md$/.exec(String(mdPath || ''));
  return m && STEM_RE.test(m[1]) ? m[1] : null;
}

function headers(cfg, accept) {
  return { Authorization: `Bearer ${cfg.token}`, Accept: accept, 'X-GitHub-Api-Version': '2022-11-28' };
}

// no-cache: the API answers with max-age=60, which would keep showing an entry just removed or published.
export async function ghRaw(cfg, path, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${API}/${cfg.repo}/contents/${path}`, { headers: headers(cfg, 'application/vnd.github.raw+json'), cache: 'no-cache' });
    return { status: res.status, text: res.ok ? await res.text() : null };
  } catch {
    return { status: 0, text: null };
  }
}

export async function ghRepo(cfg, fetchImpl = fetch) {
  try {
    return (await fetchImpl(`${API}/${cfg.repo}`, { headers: headers(cfg, 'application/vnd.github+json') })).status;
  } catch {
    return 0;
  }
}

const failState = (status) => (status === 401 || status === 403 ? 'auth' : 'unavailable');

// A private repo answers 404 both when index.json is missing and when the token cannot see the
// repo, so a 404 is resolved by asking for the repo itself.
export async function loadIndex(cfg, fetchImpl = fetch) {
  const r = await ghRaw(cfg, 'index.json', fetchImpl);
  if (r.status === 200) {
    try {
      const index = JSON.parse(r.text);
      return index && Array.isArray(index.entries) ? { state: 'ok', index } : { state: 'bad-data', index: null };
    } catch {
      return { state: 'bad-data', index: null };
    }
  }
  if (r.status === 404) {
    const repo = await ghRepo(cfg, fetchImpl);
    if (repo === 200) return { state: 'empty', index: null };
    if (repo === 404) return { state: 'no-repo', index: null };
    return { state: failState(repo), index: null };
  }
  return { state: failState(r.status), index: null };
}

async function ghJson(cfg, method, path, body, fetchImpl) {
  const res = await fetchImpl(`${API}/${cfg.repo}${path}`, {
    method, cache: 'no-cache', headers: { ...headers(cfg, 'application/vnd.github+json'), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, data: res.ok ? await res.json() : null };
}

class RemoveError extends Error {
  constructor(status) { super(`GitHub ${status}`); this.status = status; }
}
const must = (r) => { if (!r.data) throw new RemoveError(r.status); return r.data; };

export function withoutEntry(indexText, stem) {
  const data = JSON.parse(indexText);
  const entries = (Array.isArray(data.entries) ? data.entries : []).filter((e) => !(e && stemOf(e.md) === stem));
  return JSON.stringify({ ...data, generated_at: new Date().toISOString().replace(/\.\d+Z$/, '+00:00'), count: entries.length, entries }, null, 2) + '\n';
}

// Coupled with index.py render_readme: entry lines are `- [owner/repo](library/<stem>.md) ...` and the
// header reads `N 個 repo`. The next publish rebuilds README.md whole; this only keeps it from linking a deleted file.
export function readmeWithout(readme, stem, count) {
  const lines = readme.split('\n');
  const kept = lines.filter((l) => !l.startsWith('- [') || !l.includes(`](library/${stem}.md)`));
  if (kept.length === lines.length) return readme;
  return count === null ? kept.join('\n') : kept.join('\n').replace(/^\d+ 個 repo/m, `${count} 個 repo`);
}

// Removes one entry in a single commit: library/<stem>.{md,json,svg}, its index.json row and its README line.
// Retries when the branch moved under it (a publish landed in between). Returns 'ok', or 'gone' when nothing
// referenced the stem any more; throws RemoveError and commits nothing when a read fails, so a retry can finish it.
export async function removeEntry(cfg, stem, repoName, fetchImpl = fetch) {
  if (!STEM_RE.test(stem)) throw new RemoveError(400);
  const branch = must(await ghJson(cfg, 'GET', '', null, fetchImpl)).default_branch;
  const ref = String(branch).split('/').map(encodeURIComponent).join('/');
  const read = async (path, head) => {
    const r = await ghRaw(cfg, `${path}?ref=${head}`, fetchImpl);
    if (r.status !== 200 && r.status !== 404) throw new RemoveError(r.status);
    return r.text;
  };
  for (let attempt = 0; attempt < 3; attempt++) {
    const head = must(await ghJson(cfg, 'GET', `/git/ref/heads/${ref}`, null, fetchImpl)).object.sha;
    const treeSha = must(await ghJson(cfg, 'GET', `/git/commits/${head}`, null, fetchImpl)).tree.sha;
    const libDir = must(await ghJson(cfg, 'GET', `/git/trees/${treeSha}`, null, fetchImpl)).tree.find((t) => t.path === 'library' && t.type === 'tree');
    const names = libDir ? must(await ghJson(cfg, 'GET', `/git/trees/${libDir.sha}`, null, fetchImpl)).tree.map((t) => t.path) : [];
    const tree = ['md', 'json', 'svg'].map((x) => `${stem}.${x}`).filter((n) => names.includes(n))
      .map((n) => ({ path: `library/${n}`, mode: '100644', type: 'blob', sha: null }));
    const [idxText, readmeText] = [await read('index.json', head), await read('README.md', head)];
    let count = null;
    if (idxText !== null) {
      try {
        const before = JSON.parse(idxText).entries;
        if (Array.isArray(before)) {
          const content = withoutEntry(idxText, stem);
          count = JSON.parse(content).count;
          if (count !== before.length) tree.push({ path: 'index.json', mode: '100644', type: 'blob', content });
        }
      } catch { /* a malformed index is rebuilt by the next publish */ }
    }
    if (readmeText !== null) {
      const content = readmeWithout(readmeText, stem, count);
      if (content !== readmeText) tree.push({ path: 'README.md', mode: '100644', type: 'blob', content });
    }
    if (!tree.length) return 'gone';
    const newTree = must(await ghJson(cfg, 'POST', '/git/trees', { base_tree: treeSha, tree }, fetchImpl)).sha;
    const commit = must(await ghJson(cfg, 'POST', '/git/commits', { message: `remove: ${repoName || stem}`, tree: newTree, parents: [head] }, fetchImpl)).sha;
    const moved = await ghJson(cfg, 'PATCH', `/git/refs/heads/${ref}`, { sha: commit, force: false }, fetchImpl);
    if (moved.status === 200) return 'ok';
    if (moved.status !== 422) throw new RemoveError(moved.status);
  }
  throw new RemoveError(409);
}

const time = (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? 0 : t; };

// 是否已試過: the owner's own mark per entry, kept in state.json (written only by the dashboard and the skill).
export const TRIED = ['未試', '試過', '在用', '放棄'];
const strs = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);

export const VERDICTS = ['能用', '有條件才能用', '不建議用'];

// From the API facts the pipeline stored: '' when healthy or unknown.
export function health(activity) {
  if (!activity || typeof activity !== 'object') return '';
  if (activity.archived === true) return '已封存';
  return activity.stale === true ? '半年未更新' : '';
}

export function stateItem(state, stem) {
  const it = state && typeof state === 'object' && Object.hasOwn(state, stem) ? state[stem] : null;
  return { tried: it && TRIED.includes(it.tried) ? it.tried : '未試', install: Boolean(it && it.install === true), owned: Boolean(it && it.owned === true) };
}

function b64decodeUtf8(b64) {
  const bin = atob(String(b64).replace(/\s/g, ''));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function b64encodeUtf8(s) {
  let bin = '';
  for (const b of new TextEncoder().encode(s)) bin += String.fromCharCode(b);
  return btoa(bin);
}

// Returns {status, items, sha}; a missing state.json is an empty state, not an error.
export async function loadState(cfg, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${API}/${cfg.repo}/contents/state.json`, { headers: headers(cfg, 'application/vnd.github+json'), cache: 'no-cache' });
    if (res.status === 404) return { status: 200, items: {}, sha: null };
    if (!res.ok) return { status: res.status, items: {}, sha: null };
    const body = await res.json();
    let data = null;
    try { data = JSON.parse(b64decodeUtf8(body.content)); } catch { /* treated as empty */ }
    const items = data && typeof data.items === 'object' && data.items && !Array.isArray(data.items) ? data.items : {};
    return { status: 200, items, sha: body.sha || null };
  } catch {
    return { status: 0, items: {}, sha: null };
  }
}

// Merges `patch` into one stem's state and commits state.json; retries when another write landed first.
export async function saveStateItem(cfg, stem, patch, repoName, fetchImpl = fetch) {
  if (!STEM_RE.test(stem)) throw new RemoveError(400);
  for (let attempt = 0; attempt < 3; attempt++) {
    const cur = await loadState(cfg, fetchImpl);
    if (cur.status !== 200) throw new RemoveError(cur.status);
    const items = { ...cur.items };
    const next = { ...stateItem(items, stem), ...patch, updated_at: new Date().toISOString().replace(/\.\d+Z$/, '+00:00') };
    items[stem] = next;
    const body = { message: `state: ${repoName || stem} ${next.tried}${next.install ? ' · 確認安裝' : ''}`,
      content: b64encodeUtf8(JSON.stringify({ v: 1, items }, null, 2) + '\n'), ...(cur.sha ? { sha: cur.sha } : {}) };
    const res = await fetchImpl(`${API}/${cfg.repo}/contents/state.json`, {
      method: 'PUT', cache: 'no-cache', headers: { ...headers(cfg, 'application/vnd.github+json'), 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (res.ok) return { tried: next.tried, install: next.install === true, owned: next.owned === true };
    if (res.status !== 409 && res.status !== 422) throw new RemoveError(res.status);
  }
  throw new RemoveError(409);
}

// Downloads a private repo file (a skill zip under dist/) as a Blob the page can hand to the user.
export async function ghBlob(cfg, path, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${API}/${cfg.repo}/contents/${path}`, { headers: headers(cfg, 'application/vnd.github.raw+json'), cache: 'no-cache' });
    return { status: res.status, blob: res.ok ? await res.blob() : null };
  } catch {
    return { status: 0, blob: null };
  }
}

// Lists dist/<stem>/*.zip; an empty list when nothing has been built for this entry yet.
export async function listZips(cfg, stem, fetchImpl = fetch) {
  if (!STEM_RE.test(stem)) return [];
  try {
    const res = await fetchImpl(`${API}/${cfg.repo}/contents/dist/${stem}`, { headers: headers(cfg, 'application/vnd.github+json'), cache: 'no-cache' });
    if (!res.ok) return [];
    const list = await res.json();
    return Array.isArray(list) ? list.filter((f) => f && f.type === 'file' && /^[A-Za-z0-9_-]{1,64}\.zip$/.test(f.name)).map((f) => `dist/${stem}/${f.name}`) : [];
  } catch {
    return [];
  }
}

export function matches(item, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  const hay = [item.repo, item.tagline, item.purpose, item.intro, item.verdict, ...(item.scenarios || []), ...(item.tags || []),
    ...(item.tasks || []), ...(item.task_areas || [])].join(' ').toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

export function mergeLibrary(index, history, lib, state = {}) {
  const str = (v) => (typeof v === 'string' ? v : '');
  const entries = (index && Array.isArray(index.entries) ? index.entries : [])
    .filter((e) => e && typeof e === 'object' && typeof e.repo === 'string' && typeof e.md === 'string')
    .map((e) => ({ kind: 'entry', stem: stemOf(e.md), repo: e.repo, tagline: str(e.tagline), intro: str(e.intro), category: str(e.category),
      requirements: strs(e.requirements), last_seen: str(e.last_seen), purpose: str(e.purpose), scenarios: strs(e.scenarios), tags: strs(e.tags),
      installable: Boolean(e.installable && typeof e.installable === 'object' && e.installable.kind), ...stateItem(state, stemOf(e.md)),
      verdict: VERDICTS.includes(e.verdict) ? e.verdict : '', tasks: strs(e.tasks), task_areas: strs(e.task_areas), health: health(e.activity) }))
    .filter((e) => e.stem && e.repo)
    .sort((a, b) => time(b.last_seen) - time(a.last_seen));
  const known = new Set(entries.map((e) => e.repo.toLowerCase()));
  const local = (Array.isArray(history) ? history : [])
    .filter((h) => h && h.lib === lib && (h.state === 'pending' || h.state === 'failed') && !known.has(String(h.repo).toLowerCase()))
    .map((h) => ({ kind: h.state, id: h.id, repo: h.repo, at: h.at }))
    .sort((a, b) => time(b.at) - time(a.at));
  return [...local, ...entries];
}

export function specRows(lines) {
  return (lines || []).map((line) => {
    const m = /^([^：:]{1,8})[：:]\s*(.+)$/.exec(line);
    return m ? [m[1], m[2]] : [null, line];
  });
}

const OS = [['Windows', /windows/i], ['macOS', /mac\s?os|macos|\bmac\b|apple silicon/i], ['Linux', /linux/i],
  ['iOS', /\bios\b|iphone|ipad/i], ['Android', /android/i]];

// A match counts only when no negation (不支援、無法、不需、不按…) sits just before it.
const NEGATION = /(不|無|免|非|沒有|沒)[^，,。；;、]{0,3}$/;
const AFFIRMATIVE = /(無論|不論|不管|不只|不僅|不但|並非只|非只)[^，,。；;]{0,6}$/;
function positive(text, re) {
  const g = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
  for (const m of text.matchAll(g)) {
    const before = text.slice(Math.max(0, m.index - 6), m.index);
    if (!NEGATION.test(before) || AFFIRMATIVE.test(before)) return m.index;
  }
  return -1;
}

// Short card labels derived from the 使用門檻 lines; anything unrecognised yields no badge.
export function badges(requirements) {
  const out = [];
  for (const [label, text] of specRows(Array.isArray(requirements) ? requirements : [])) {
    if (!label && /不需安裝/.test(text)) out.push('不需安裝');
    if (label === '平台') {
      const os = OS.map(([name, re]) => [name, positive(text, re)]).filter(([, at]) => at >= 0).sort((x, y) => x[1] - y[1]).map(([name]) => name);
      if (os.length >= 3) out.push('跨平台');
      else if (os.length) out.push(...os);
      else if (positive(text, /瀏覽器|網頁|web/i) >= 0) out.push('網頁');
    }
    if (label === '費用') {
      if (positive(text, /訂閱|月費|年費/) >= 0) out.push('訂閱');
      else if (positive(text, /用量|計費|使用費|按次/) >= 0) out.push('需付模型費');
      else if (/免費/.test(text)) out.push('免費');
    }
  }
  return out.slice(0, 3);
}
