// Architecture diagram engine for the reading page: allowlist check before inlining, the
// drafting animation, node focus and the zoomable lightbox.
// Coupled with action/scripts/validate.py: ELEMENTS, ATTRS and the paint grammars must match.

export const ELEMENTS = new Set(['svg', 'title', 'desc', 'defs', 'symbol', 'g', 'rect', 'path', 'line', 'polyline',
  'polygon', 'circle', 'ellipse', 'text', 'tspan', 'use', 'marker']);
export const ATTRS = new Set(['aria-hidden', 'aria-labelledby', 'class', 'cx', 'cy', 'd', 'data-edge', 'fill',
  'fill-opacity', 'font-family', 'font-size', 'font-weight', 'height', 'href', 'id', 'letter-spacing', 'marker-end',
  'marker-start', 'markerHeight', 'markerWidth', 'orient', 'points', 'r', 'refX', 'refY', 'role', 'rx', 'ry', 'stroke',
  'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'stroke-opacity', 'stroke-width', 'text-anchor', 'transform',
  'viewBox', 'width', 'x', 'x1', 'x2', 'y', 'y1', 'y2', 'dominant-baseline', 'opacity', 'xmlns', 'version']);
const URL_REF = String.raw`url\(#[A-Za-z0-9_-]+\)`;
const PAINT = new RegExp(String.raw`^(none|transparent|currentColor|#[0-9A-Fa-f]{3}|#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{8}|${URL_REF})$`);
const MARKER = new RegExp(`^${URL_REF}$`);
const STRICT = { fill: PAINT, stroke: PAINT, 'marker-start': MARKER, 'marker-end': MARKER };
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

export function elementAllowed(name) { return ELEMENTS.has(name); }

export function attrAllowed(name, value) {
  const low = value.trim().toLowerCase();
  if (name.startsWith('on') || name === 'style' || !ATTRS.has(name)) return false;
  if (value.includes('\\') || CONTROL.test(value)) return false;
  if (name === 'href') return value.startsWith('#');
  if (STRICT[name]) return STRICT[name].test(value.trim());
  if (low.includes('url(') || low.includes('javascript:') || low.includes('data:')) return false;
  return true;
}

export function checkSvgDoc(root) {
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (!elementAllowed(el.localName)) return false;
    for (const a of el.attributes) {
      if (a.name.startsWith('xmlns')) continue;
      if (!attrAllowed(a.localName, a.value)) return false;
    }
  }
  return true;
}

// Returns null when the SVG fails the allowlist; callers then show rejectedNotice and must not
// expose the bytes through any URL.
export function prepareSvg(text, prefix, doc = document) {
  const parsed = new DOMParser().parseFromString(text, 'image/svg+xml');
  const root = parsed.documentElement;
  if (root.localName !== 'svg' || parsed.querySelector('parsererror') || !checkSvgDoc(root)) return null;
  const ids = new Map();
  for (const el of root.querySelectorAll('[id]')) { const n = `${prefix}-${el.id}`; ids.set(el.id, n); el.id = n; }
  for (const el of root.querySelectorAll('*')) {
    for (const a of [...el.attributes]) {
      if (a.localName === 'href' || a.value.includes('url(#')) {
        a.value = a.value.replace(/#([\w-]+)/g, (m, id) => (ids.has(id) ? `#${ids.get(id)}` : m));
      } else if (a.localName === 'aria-labelledby') {
        a.value = a.value.split(/\s+/).map((id) => ids.get(id) || id).join(' ');
      }
    }
  }
  // <use> clones ignore page CSS, so icon and arrowhead ink follows currentColor instead.
  for (const el of root.querySelectorAll('symbol, symbol *, marker, marker *')) {
    for (const a of ['stroke', 'fill']) if ((el.getAttribute(a) || '').toLowerCase() === '#1a1a1a') el.setAttribute(a, 'currentColor');
  }
  const vb = (root.getAttribute('viewBox') || '').split(/\s+/).map(Number);
  const first = root.querySelector(':scope > rect');
  if (first && Number(first.getAttribute('width')) >= vb[2] - 1) first.classList.add('canvas');
  root.removeAttribute('width');
  root.removeAttribute('height');
  root.classList.add('dia');
  return doc.importNode(root, true);
}

export function rejectedNotice(doc, githubUrl) {
  const box = doc.createElement('p');
  box.className = 'rejected';
  box.append(doc.createTextNode('這張架構圖沒通過安全檢查，所以沒有顯示。'));
  if (githubUrl) {
    const a = doc.createElement('a');
    a.href = githubUrl; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = '在 GitHub 查看原檔';
    box.append(' ', a);
  }
  return box;
}

export function endpoints(d) {
  let x = 0, y = 0, sx = null, sy = null;
  for (const [, cmd, args] of d.matchAll(/([MLHV])([^MLHV]*)/g)) {
    const n = args.split(/[\s,]+/).filter(Boolean).map(Number);
    if (cmd === 'M' || cmd === 'L') {
      for (let i = 0; i + 1 < n.length; i += 2) { x = n[i]; y = n[i + 1]; if (sx === null) { sx = x; sy = y; } }
    } else if (cmd === 'H') x = n[n.length - 1];
    else if (cmd === 'V') y = n[n.length - 1];
  }
  return [[sx, sy], [x, y]];
}

// Tapping a node lights it, its edges, the nodes at their other ends and their labels.
export function wire(svg, isDrag = () => false) {
  const nodes = [...svg.querySelectorAll('g.node')].map((g) => {
    const r = g.querySelector('rect');
    return { g, x: +r.getAttribute('x'), y: +r.getAttribute('y'), w: +r.getAttribute('width'), h: +r.getAttribute('height') };
  });
  const near = ([px, py]) => nodes.find((n) => px >= n.x - 16 && px <= n.x + n.w + 16 && py >= n.y - 16 && py <= n.y + n.h + 16);
  const edges = [...svg.querySelectorAll('path.edge')].map((p) => {
    const [a, b] = endpoints(p.getAttribute('d') || '');
    return { p, a: near(a), b: near(b) };
  });
  const labels = [...svg.querySelectorAll('g.label')];
  const clear = () => { svg.classList.remove('focus'); svg.querySelectorAll('.lit').forEach((e) => e.classList.remove('lit')); };
  for (const n of nodes) {
    n.g.addEventListener('click', (ev) => {
      if (isDrag()) return;
      ev.stopPropagation();
      const was = n.g.classList.contains('lit') && svg.classList.contains('focus');
      clear();
      if (was) return;
      svg.classList.add('focus');
      n.g.classList.add('lit');
      for (const e of edges) {
        if (e.a !== n && e.b !== n) continue;
        e.p.classList.add('lit');
        (e.a === n ? e.b : e.a)?.g.classList.add('lit');
        for (const l of labels) {
          const ref = l.getAttribute('data-edge');
          if (ref && e.p.id.endsWith(ref)) l.classList.add('lit');
        }
      }
    });
  }
  svg.addEventListener('click', () => { if (!isDrag()) clear(); });
}

// Zones, then nodes, then solid edges traced along the flow, then labels.
export function draft(svg) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const zones = [...svg.querySelectorAll('g.zone')];
  const nodes = [...svg.querySelectorAll('g.node')];
  const edges = [...svg.querySelectorAll('path.edge')];
  const labels = [...svg.querySelectorAll('g.label')];
  zones.forEach((z, i) => z.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 260, delay: i * 50, fill: 'backwards', easing: 'ease-out' }));
  const t0 = 160 + zones.length * 50;
  nodes.forEach((n, i) => n.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }],
    { duration: 240, delay: t0 + i * 45, fill: 'backwards', easing: 'ease-out' }));
  const t1 = t0 + nodes.length * 45 + 80;
  edges.forEach((p, i) => {
    const delay = t1 + i * 70;
    if (p.getAttribute('stroke-dasharray')) {
      p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay, fill: 'backwards' });
      return;
    }
    const len = p.getTotalLength();
    const marker = p.getAttribute('marker-end');
    if (marker) p.removeAttribute('marker-end');
    p.style.strokeDasharray = `${len}`;
    const a = p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: 380, delay, fill: 'backwards', easing: 'ease-in-out' });
    a.onfinish = () => { p.style.strokeDasharray = ''; if (marker) p.setAttribute('marker-end', marker); };
  });
  labels.forEach((l, i) => l.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, delay: t1 + edges.length * 70 + i * 40, fill: 'backwards' }));
}

// root holds [data-stage], [data-reset] and [data-close]; only allowlisted SVGs are passed in.
export function mountLightbox(root) {
  const stage = root.querySelector('[data-stage]');
  const view = { s: 1, x: 0, y: 0, base: 1 };
  const pts = new Map();
  let moved = false, downAt = null, opener = null;
  const svg = () => stage.firstElementChild;
  const apply = () => { if (svg()) svg().style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.s})`; };
  const reset = () => {
    const el = svg(); if (!el) return;
    view.s = view.base;
    view.x = (stage.clientWidth - el.getAttribute('width') * view.s) / 2;
    view.y = (stage.clientHeight - el.getAttribute('height') * view.s) / 2;
    apply();
  };
  const zoomAt = (cx, cy, k) => {
    const s = Math.min(Math.max(view.s * k, view.base * 0.6), view.base * 8);
    view.x = cx - (cx - view.x) * (s / view.s);
    view.y = cy - (cy - view.y) * (s / view.s);
    view.s = s;
    apply();
  };
  stage.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const r = stage.getBoundingClientRect();
    zoomAt(ev.clientX - r.left, ev.clientY - r.top, Math.exp(-ev.deltaY * 0.0015));
  }, { passive: false });
  stage.addEventListener('pointerdown', (ev) => {
    pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
    if (pts.size === 1) { moved = false; downAt = [ev.clientX, ev.clientY]; }
  });
  stage.addEventListener('pointermove', (ev) => {
    if (!pts.has(ev.pointerId)) return;
    const prev = pts.get(ev.pointerId);
    const others = [...pts].filter(([id]) => id !== ev.pointerId);
    if (downAt && Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 6) {
      moved = true;
      if (!stage.hasPointerCapture(ev.pointerId)) stage.setPointerCapture(ev.pointerId);
    }
    if (others.length === 1) {
      const o = others[0][1];
      const r = stage.getBoundingClientRect();
      const d0 = Math.hypot(prev[0] - o[0], prev[1] - o[1]);
      const d1 = Math.hypot(ev.clientX - o[0], ev.clientY - o[1]);
      if (d0 > 0) zoomAt((ev.clientX + o[0]) / 2 - r.left, (ev.clientY + o[1]) / 2 - r.top, d1 / d0);
    } else if (moved) {
      view.x += ev.clientX - prev[0];
      view.y += ev.clientY - prev[1];
      apply();
    }
    pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
  });
  for (const t of ['pointerup', 'pointercancel']) {
    stage.addEventListener(t, (ev) => { pts.delete(ev.pointerId); if (!pts.size) setTimeout(() => { downAt = null; }, 0); });
  }
  stage.addEventListener('dblclick', reset);
  root.querySelector('[data-reset]').addEventListener('click', reset);
  const close = () => { root.hidden = true; stage.replaceChildren(); opener?.focus(); };
  root.querySelector('[data-close]').addEventListener('click', close);
  addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !root.hidden) close(); });
  return {
    isDrag: () => moved,
    open(el) {
      opener = document.activeElement;
      stage.replaceChildren(el);
      root.hidden = false;
      root.querySelector('[data-close]').focus();
      requestAnimationFrame(() => {
        const vb = (el.getAttribute('viewBox') || '0 0 1200 800').split(/\s+/).map(Number);
        el.setAttribute('width', vb[2]);
        el.setAttribute('height', vb[3]);
        view.base = Math.min(stage.clientWidth / vb[2], stage.clientHeight / vb[3]) * 0.96;
        reset();
      });
    },
    close,
  };
}
