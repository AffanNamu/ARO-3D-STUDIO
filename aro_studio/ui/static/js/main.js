import { api, setUnauthorizedHandler, token } from './api.js';
import { $, clear, errorToast, h, icon, modal, toast } from './dom.js';
import { refreshPills } from './jobs.js';

const ROUTES = [
  ['dashboard', 'Dashboard', () => import('./views/dashboard.js')],
  ['projects', 'Projects', () => import('./views/projects.js')],
  ['library', 'Asset Library', () => import('./views/library.js')],
  ['studio', '3D Studio', () => import('./views/studio.js')],
  ['generation', 'Generation', () => import('./views/generation.js')],
  ['models', 'Models', () => import('./views/models.js')],
  ['validation', 'Validation', () => import('./views/validation.js')],
  ['exports', 'Exports', () => import('./views/exports.js')],
  ['settings', 'Settings', () => import('./views/settings.js')],
];
let current = null;
let promptingToken = false;

function buildNav() {
  const nav = $('#nav');
  nav.append(...ROUTES.map(([key, label]) => h('a', { href: `#/${key}`, 'data-route': key }, icon(key), label)));
  nav.append(h('div', { class: 'sep' }), h('div', { class: 'foot' }, 'Production asset pipeline for African Online Roads. Free-tier, open-source stack.'));
}

async function route() {
  const [, key = 'dashboard', ...rest] = location.hash.replace(/^#/, '').split('/');
  const def = ROUTES.find((r) => r[0] === key) || ROUTES[0];
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === def[0]));
  const view = $('#view');
  current?.unmount?.();
  clear(view); view.className = def[0] === 'studio' ? 'flush' : '';
  try {
    const mod = await def[2]();
    current = mod;
    await mod.mount(view, rest.map(decodeURIComponent));
  } catch (e) {
    view.append(h('div', { class: 'notice err' }, h('b', null, 'This view failed to load.'), h('div', null, e.message || String(e)), e.action ? h('div', null, `→ ${e.action}`) : null));
    console.error(e);
  }
  view.focus({ preventScroll: true });
}

function askToken() {
  if (promptingToken) return; promptingToken = true;
  const input = h('input', { type: 'password', placeholder: 'Access token', autocomplete: 'off' });
  modal('Access token required', h('div', null, h('p', null, 'This Studio is protected. Enter the access token set by the administrator (ARO_ACCESS_TOKEN). It is kept in this browser tab only.'), input),
    [{ label: 'Unlock', cls: 'primary', onClick: () => { token.set(input.value.trim()); promptingToken = false; route(); refreshPills(); } }]);
}

buildNav();
setUnauthorizedHandler(askToken);
window.addEventListener('hashchange', route);
window.addEventListener('unhandledrejection', (e) => { if (!(e.reason && e.reason.status === 401)) errorToast(e.reason || new Error('Unexpected error')); });
route();
refreshPills();
setInterval(refreshPills, 4000);
