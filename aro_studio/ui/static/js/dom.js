// DOM helpers. All user-controlled strings go through textContent (never innerHTML) to prevent XSS.

// Element.replaceChildren(null) inserts the literal text "null"; skip null/false the same way h() does.
const nativeReplaceChildren = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function replaceChildren(...kids) {
  return nativeReplaceChildren.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false));
};

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'hidden' || k === 'required' || k === 'multiple') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}
export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

const ICONS = {
  dashboard: 'M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z',
  projects: 'M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  library: 'M4 4h4v16H4zM10 4h4v16h-4zM16.5 5.2l3.9-1 3 15.2-3.9 1z',
  studio: 'M12 2l9 5v10l-9 5-9-5V7zM12 12l9-5M12 12v10M12 12L3 7',
  generation: 'M12 2l2.4 5.6L20 10l-5.6 2.4L12 18l-2.4-5.6L4 10l5.6-2.4zM19 16l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z',
  models: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2',
  validation: 'M12 2l8 3v6c0 5-3.4 9.4-8 11-4.6-1.6-8-6-8-11V5zM8.5 12l2.5 2.5L16 9.5',
  exports: 'M12 3v12M7 10l5 5 5-5M4 19h16',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  play: 'M6 4l14 8-14 8z', plus: 'M12 5v14M5 12h14', trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  archive: 'M3 4h18v4H3zM5 8v12h14V8M10 12h4', refresh: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7', download: 'M12 3v12M7 10l5 5 5-5M4 19h16', upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1', x: 'M6 6l12 12M18 6L6 18', check: 'M5 12.5l4.5 4.5L19 7',
};
export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ns, 'path'); p.setAttribute('d', ICONS[name] || ICONS.dashboard); s.append(p);
  return s;
}

export const fmt = {
  bytes(n) { if (n == null) return '—'; const u = ['B', 'KB', 'MB', 'GB']; let i = 0; let v = n; while (v >= 1024 && i < 3) { v /= 1024; i++; } return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`; },
  int(n) { return n == null ? '—' : Number(n).toLocaleString('en-US'); },
  num(n, d = 2) { return n == null ? '—' : Number(n).toFixed(d); },
  date(ts) { return ts ? new Date(ts * 1000).toLocaleString() : '—'; },
  ago(ts) { if (!ts) return '—'; const s = Math.max(0, Date.now() / 1000 - ts); if (s < 60) return `${Math.floor(s)}s ago`; if (s < 3600) return `${Math.floor(s / 60)}m ago`; if (s < 86400) return `${Math.floor(s / 3600)}h ago`; return `${Math.floor(s / 86400)}d ago`; },
  dur(s) { if (s == null) return '—'; return s < 1 ? `${Math.round(s * 1000)} ms` : s < 90 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`; },
  pct(n) { return n == null ? 'n/a' : `${Math.round(n)}%`; },
  title(s) { return String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bLod\b/g, 'LOD'); },
};

const STATUS_CLASS = {
  PRODUCTION_READY: 'ok', COMPLETED: 'ok', APPROVED: 'ok', passed: 'ok', active: 'ok',
  FAILED: 'err', MODEL_ERROR: 'err', RESOURCE_LIMIT: 'err', INVALID_INPUT: 'err', TIMEOUT: 'err', failed: 'err',
  NEEDS_REVIEW: 'warn', CANCELLED: 'warn', warning: 'warn', archived: 'warn',
  QUEUED: 'info', INITIALIZING: 'accent', PREPROCESSING: 'accent', GENERATING: 'accent', POSTPROCESSING: 'accent', VALIDATING: 'accent', PROCESSING: 'accent',
};
export const statusChip = (s) => h('span', { class: `chip ${STATUS_CLASS[s] || ''}` }, String(s).replace(/_/g, ' '));
export function bar(frac, cls = '') { return h('div', { class: `bar ${cls}`, role: 'progressbar', 'aria-valuenow': Math.round((frac || 0) * 100), 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('i', { style: { width: `${Math.max(0, Math.min(1, frac || 0)) * 100}%` } })); }

export function toast(title, msg = '', kind = '') {
  const t = h('div', { class: `toast ${kind}` }, h('b', null, title), msg ? h('span', null, msg) : null);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'err' ? 9000 : 4500);
}
export function errorToast(e, title = 'Something went wrong') {
  toast(title, [e.message, e.action ? `→ ${e.action}` : ''].filter(Boolean).join('\n'), 'err');
  // eslint-disable-next-line no-console
  console.error(e);
}

export function modal(title, body, actions = []) {
  const root = document.getElementById('modal-root');
  const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const box = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, h('h2', null, title), body,
    h('div', { class: 'actions' }, ...actions.map((a) => h('button', { class: `btn ${a.cls || ''}`, onclick: async () => { const r = await a.onClick?.(close); if (r !== false && !a.keepOpen) close(); } }, a.label))));
  const overlay = h('div', { class: 'overlay', onmousedown: (e) => { if (e.target === overlay) close(); } }, box);
  document.addEventListener('keydown', onKey); root.append(overlay);
  box.querySelector('input,select,textarea')?.focus();
  return close;
}
export const confirmDialog = (title, text, label = 'Confirm', danger = false) => new Promise((res) => {
  modal(title, h('p', null, text), [{ label: 'Cancel', onClick: () => res(false) }, { label, cls: danger ? 'danger' : 'primary', onClick: () => res(true) }]);
});
export function promptDialog(title, label, value = '') {
  return new Promise((res) => {
    const input = h('input', { value, 'aria-label': label });
    modal(title, h('label', { class: 'field' }, h('span', null, label), input), [{ label: 'Cancel', onClick: () => res(null) }, { label: 'OK', cls: 'primary', onClick: () => res(input.value.trim() || null) }]);
  });
}
export const field = (label, control, hint) => h('label', { class: 'field' }, h('span', null, label), control, hint ? h('div', { class: 'hint' }, hint) : null);
export const select = (opts, value, attrs = {}) => h('select', attrs, ...opts.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h('option', { value: v, selected: v === value }, l); }));
export const kv = (obj) => h('dl', { class: 'kv' }, ...Object.entries(obj).flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v ?? '—')]));
export const empty = (text, ...extra) => h('div', { class: 'empty' }, text, ...extra);
export function notice(kind, ...kids) { return h('div', { class: `notice ${kind}` }, ...kids); }
export const nav = (hash) => { location.hash = hash; };
