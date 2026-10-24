// Trust gates of the capture page: which incoming links may write without a tap.
// Run: PW_CORE=/path/to/playwright-core node web/tests/e2e/gate.cjs   (exit 1 on any mismatch)
const { chromium } = require(process.env.PW_CORE || 'playwright-core');
const serve = require('./serve.cjs');

(async () => {
  const { base: B, close } = await serve();
  const browser = await chromium.launch(process.env.PW_CHROME ? { executablePath: process.env.PW_CHROME } : {});
  const failures = [];
  const expect = (label, cond, detail) => { console.log(`${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : ` — ${detail}`}`); if (!cond) failures.push(label); };
  const mk = async (standalone) => {
    const ctx = await browser.newContext();
    if (standalone) await ctx.addInitScript(() => { const o = window.matchMedia.bind(window); window.matchMedia = (q) => (q.includes('standalone') ? { matches: true, addEventListener() {} } : o(q)); });
    ctx.puts = 0; ctx.errors = [];
    await ctx.route('https://api.github.com/**', (r) => {
      if (r.request().method() === 'PUT') { ctx.puts += 1; return r.fulfill({ status: 201, contentType: 'application/json', body: '{}' }); }
      return r.fulfill({ status: 404, contentType: 'application/json', body: '{"message":"Not Found"}' });
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => ctx.errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error' && !/404/.test(m.text())) ctx.errors.push(m.text()); });
    page.on('dialog', (d) => { ctx.lastDialog = d.message(); d.dismiss(); });
    await page.goto(B);
    await page.evaluate(() => localStorage.setItem('repobox.cfg', JSON.stringify({ repo: 'me/lib', token: 't', nonce: 'abc123' })));
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload(); await page.evaluate(() => navigator.serviceWorker.ready);
    return { ctx, page };
  };
  const go = async (page, url) => { await page.goto('about:blank'); await page.goto(url); await page.waitForTimeout(600); };
  const status = (page) => page.textContent('#status');
  const sharePost = async (page) => {
    await page.goto('about:blank'); await page.goto(B);
    await page.evaluate(() => { const f = document.createElement('form'); f.method = 'POST'; f.action = 'share'; f.enctype = 'multipart/form-data';
      for (const [k, v] of [['title', 'GitHub'], ['text', ''], ['url', 'https://github.com/HowieWang1121/Socratic-Education-System']]) { const i = document.createElement('input'); i.name = k; i.value = v; f.appendChild(i); }
      document.body.appendChild(f); f.submit(); });
    await page.waitForURL(B, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(600);
  };
  const check = async (label, ctx, page, wantPuts, wantStatus) => {
    const s = (await status(page)).trim();
    expect(label, ctx.puts === wantPuts && s === wantStatus, `puts=${ctx.puts} status="${s}"`);
    ctx.puts = 0;
  };

  let { ctx, page } = await mk(false);
  await go(page, B + '?url=https://github.com/evil/spam'); await check('A crafted GET query asks first', ctx, page, 0, '待確認');
  await go(page, B + '#url=https://github.com/a/b&k=nope'); await check('B bookmarklet with wrong nonce asks first', ctx, page, 0, '待確認');
  await go(page, B + '#url=https://github.com/a/b&k=abc123&ref=www.threads.com'); await check('C bookmarklet with nonce writes once', ctx, page, 1, '已收');
  await sharePost(page); await check('D share POST in a browser tab asks first', ctx, page, 0, '待確認');
  await go(page, B + '#s=12345678-1234-1234-1234-123456789abc'); await check('E forged handoff id does nothing', ctx, page, 0, '');
  const href = await page.getAttribute('#bookmarklet', 'href');
  ctx.lastDialog = null; let popups = 0; ctx.on('page', () => { popups += 1; });
  await page.evaluate((code) => { (0, eval)(decodeURIComponent(code.replace(/^javascript:/, ''))); }, href);
  await page.waitForTimeout(300);
  expect('F bookmarklet off GitHub only alerts', ctx.lastDialog === 'GitHub Box: open a GitHub repo page first' && popups === 0, `dialog=${ctx.lastDialog} popups=${popups}`);
  expect('no page errors (browser tab)', ctx.errors.length === 0, ctx.errors.join(' | '));
  await ctx.close();

  ({ ctx, page } = await mk(true));
  await sharePost(page); await check('G share POST in the app window writes once', ctx, page, 1, '已收');
  await go(page, B + '?url=https://github.com/evil/spam'); await check('H crafted GET in the app window asks first', ctx, page, 0, '待確認');
  const left = await page.evaluate(async () => (await (await caches.open('repobox-handoff')).keys()).length);
  expect('I handoff entries are consumed', left === 0, `left=${left}`);
  expect('no page errors (app window)', ctx.errors.length === 0, ctx.errors.join(' | '));

  await browser.close(); close();
  console.log(failures.length ? `\n${failures.length} gate check(s) failed` : '\nall gate checks passed');
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
