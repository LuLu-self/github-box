// Capture page library list: every index.json outcome still shows local pending items.
// Run: PW_CORE=/path/to/playwright-core node web/tests/e2e/capture.cjs   (exit 1 on any mismatch)
const { chromium } = require(process.env.PW_CORE || 'playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const serve = require('./serve.cjs');
const INDEX = fs.readFileSync(path.join(__dirname, 'fixtures/index.json'), 'utf8');

(async () => {
  const { base: B, close } = await serve();
  const browser = await chromium.launch(process.env.PW_CHROME ? { executablePath: process.env.PW_CHROME } : {});
  const failures = [];
  const expect = (label, cond, detail) => { console.log(`${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : ` — ${detail}`}`); if (!cond) failures.push(label); };
  const run = async (label, index, repo, check) => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    await ctx.route('https://api.github.com/**', (r) => {
      const u = r.request().url().replace('https://api.github.com/repos/me/lib', '');
      if (u === '/contents/index.json') return index === 'net' ? r.abort() : r.fulfill({ status: index.status, contentType: 'application/json', body: index.body || '{}' });
      if (u === '') return r.fulfill({ status: repo, contentType: 'application/json', body: '{}' });
      return r.fulfill({ status: 404, contentType: 'application/json', body: '{"message":"Not Found"}' });
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(B);
    await page.evaluate(() => {
      localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'n' }));
      localStorage.setItem('repobox.history', JSON.stringify([{ id: 'p1', repo: 'Fresh/Repo', lib: 'me/lib', at: new Date().toISOString(), state: 'pending' }]));
    });
    await page.reload(); await page.waitForTimeout(700);
    const rows = await page.$$eval('#recent .card', (cs) => cs.map((c) => c.textContent.trim()));
    const note = (await page.textContent('#lib-note')).trim();
    await check({ page, rows, note, label });
    expect(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
    await ctx.close();
  };
  await run('index 200 + pending', { status: 200, body: INDEX }, 200, async ({ page, rows, note, label }) => {
    expect(`${label}: 4 rows, pending first`, rows.length === 4 && rows[0].includes('Fresh/Repo') && rows[0].includes('分析中'), rows.join(' / '));
    expect(`${label}: no error note`, note === '', note);
    const href = await page.getAttribute('#recent a[href^="read.html"]', 'href');
    expect(`${label}: entry links to the reading page`, /^read\.html#[a-z0-9._-]+__[a-z0-9._-]+$/.test(href), href);
    const cats = await page.$$eval('#cats button', (bs) => bs.map((b) => b.textContent.replace(/\s+/g, ' ').trim()));
    expect(`${label}: category index lists 全部 and each category with counts`, cats[0] === '全部 3' && cats.some((c) => c === '桌面應用 1') && cats.some((c) => c === '分析中 1'), cats.join(' / '));
    const live = await page.textContent('#recent a.card[href="read.html#squirrelray__livesummary"]');
    expect(`${label}: card shows tagline and badges`, /Windows/.test(live) && /SquirrelRay\/LiveSummary/.test(live), live);
    await page.click('#cats button:has-text("桌面應用")');
    const only = await page.$$eval('#recent .card', (cs) => cs.map((c) => c.getAttribute('href')));
    expect(`${label}: picking a category filters the cards`, only.length === 1 && only[0] === 'read.html#squirrelray__livesummary', only.join(' / '));
    await page.click('#cats button:has-text("全部")');
    await page.click('#recent a.card[href="read.html#xiaopuouo__openchatx-mcp"]');
    await page.waitForTimeout(300);
    expect(`${label}: click opens read.html#stem`, page.url().endsWith('read.html#xiaopuouo__openchatx-mcp'), page.url());
  });
  await run('index 404 + repo 200', { status: 404 }, 200, async ({ rows, note, label }) => {
    expect(`${label}: pending only, no note`, rows.length === 1 && rows[0].includes('Fresh/Repo') && note === '', `${rows} | ${note}`);
  });
  await run('index 404 + repo 404', { status: 404 }, 404, async ({ rows, note, label }) => {
    expect(`${label}: no-repo note + pending`, note.includes('找不到收藏庫') && rows.length === 1, `${rows} | ${note}`);
  });
  await run('index 401', { status: 401 }, 200, async ({ rows, note, label }) => {
    expect(`${label}: auth note + pending`, note.includes('token 失效') && rows.length === 1, `${rows} | ${note}`);
  });
  await run('index 503', { status: 503 }, 200, async ({ rows, note, label }) => {
    expect(`${label}: unavailable note + pending`, note.includes('暫時連不到') && rows.length === 1, `${rows} | ${note}`);
  });
  await run('index bad JSON', { status: 200, body: '{broken' }, 200, async ({ rows, note, label }) => {
    expect(`${label}: bad-data note + pending`, note.includes('格式錯誤') && rows.length === 1, `${rows} | ${note}`);
  });
  {
    // A slow index for the old repo must not overwrite the list after switching repos.
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    const libB = JSON.stringify({ entries: [{ repo: 'Bee/Only', md: 'library/bee__only.md', intro: 'b', category: 'other', last_seen: '2026-10-19T00:00:00Z' }] });
    await ctx.route('https://api.github.com/**', async (r) => {
      const u = r.request().url();
      if (u.endsWith('/repos/me/lib/contents/index.json')) { await new Promise((res) => setTimeout(res, 1500)); return r.fulfill({ status: 200, contentType: 'application/json', body: INDEX }); }
      if (u.endsWith('/repos/me/other/contents/index.json')) return r.fulfill({ status: 200, contentType: 'application/json', body: libB });
      return r.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(B);
    await page.evaluate(() => localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'n' })));
    await page.reload(); await page.waitForTimeout(200);
    await page.click('#conn'); await page.fill('#repo', 'me/other'); await page.click('#settings button[type=submit]');
    await page.waitForTimeout(2200);
    const rows = await page.$$eval('#recent .card', (cs) => cs.map((c) => c.textContent.trim()));
    expect('switching repos ignores the late old index', rows.length === 1 && rows[0].includes('Bee/Only'), rows.join(' / '));
    expect('switching repos: no page errors', errors.length === 0, errors.join(' | '));
    await ctx.close();
  }
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    const broken = JSON.stringify({ entries: [null, 5, ...JSON.parse(INDEX).entries] });
    await ctx.route('https://api.github.com/**', (r) => r.fulfill({ status: r.request().url().endsWith('/index.json') ? 200 : 404, contentType: 'application/json', body: r.request().url().endsWith('/index.json') ? broken : '{}' }));
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(B);
    await page.evaluate(() => localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'n' })));
    await page.reload(); await page.waitForTimeout(700);
    const n = await page.locator('#recent a.card').count();
    expect('malformed index rows are skipped, the rest render', n === 3 && errors.length === 0, `rows=${n} errors=${errors.join(' | ')}`);
    await ctx.close();
  }
  {
    // With more entries than fit, the last one must still be reachable by the user's own scrolling.
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const many = JSON.stringify({ entries: Array.from({ length: 30 }, (_, i) => ({ repo: `Own/R${i}`, md: `library/own__r${i}.md`, intro: 'x', category: 'other', last_seen: new Date(Date.UTC(2026, 9, 1) + (30 - i) * 3600e3).toISOString() })) });
    await ctx.route('https://api.github.com/**', (r) => r.fulfill({ status: r.request().url().endsWith('/index.json') ? 200 : 404, contentType: 'application/json', body: r.request().url().endsWith('/index.json') ? many : '{}' }));
    const page = await ctx.newPage();
    await page.goto(B);
    await page.evaluate(() => localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'n' })));
    await page.reload(); await page.waitForTimeout(700);
    const box = await page.locator('#recent').boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (let i = 0; i < 20; i += 1) await page.mouse.wheel(0, 400);
    await page.waitForTimeout(300);
    const last = page.locator('#recent .card').last();
    const lb = await last.boundingBox();
    const visible = lb && lb.y + lb.height <= box.y + box.height + 1 && lb.y >= box.y - 1;
    expect('long library scrolls to its last entry by wheel', visible, JSON.stringify({ box, lb }));
    expect('one-screen page still does not scroll', await page.evaluate(() => document.documentElement.scrollHeight === innerHeight), 'page scrolls');
    await ctx.close();
  }
  {
    // Many categories on a short desktop screen: the last index button must be reachable.
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 560 } });
    const errors = [];
    const cats = ['constructor', 'toString', 'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa'];
    const idx = JSON.stringify({ entries: cats.map((c, i) => ({ repo: `O/R${i}`, md: `library/o__r${i}.md`, tagline: '副標文字測試', category: c, last_seen: '2026-10-19T00:00:00Z' })) });
    await ctx.route('https://api.github.com/**', (r) => r.fulfill({ status: r.request().url().endsWith('/index.json') ? 200 : 404, contentType: 'application/json', body: r.request().url().endsWith('/index.json') ? idx : '{}' }));
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(B);
    await page.evaluate(() => {
      localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'n' }));
      localStorage.setItem('repobox.history', JSON.stringify([{ id: 'p1', repo: 'Fresh/Repo', lib: 'me/lib', at: new Date().toISOString(), state: 'pending' }]));
    });
    await page.reload(); await page.waitForTimeout(700);
    expect('odd category names (constructor) render', errors.length === 0 && (await page.locator('#cats button').count()) === 14, errors.join(' | '));
    const nav = await page.locator('#cats').boundingBox();
    await page.mouse.move(nav.x + nav.width / 2, nav.y + Math.min(nav.height, 200) / 2);
    for (let i = 0; i < 10; i += 1) await page.mouse.wheel(0, 300);
    await page.waitForTimeout(300);
    const last = await page.locator('#cats button').last().boundingBox();
    expect('long category index scrolls to its last button', last && last.y + last.height <= 560, JSON.stringify(last));
    await ctx.close();
  }
  await browser.close(); close();
  console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nall capture checks passed');
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
