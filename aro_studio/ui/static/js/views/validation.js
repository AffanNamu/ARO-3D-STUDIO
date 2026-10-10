import { api } from '../api.js';
import { bar, empty, errorToast, fmt, h, nav, notice, select, statusChip, toast } from '../dom.js';
import { trackJob } from '../jobs.js';

export async function mount(root, [validationId]) { return validationId ? detail(root, validationId) : list(root); }

async function list(root) {
  const [r, assets] = await Promise.all([api.get('/api/validations'), api.get('/api/assets')]);
  const names = Object.fromEntries(assets.items.map((a) => [a.asset_id, a.name]));
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Validation'), h('p', { class: 'sub' }, 'Geometry, materials, textures, LOD, collision, vehicle and Unity checks. Scores never override critical failures.'))));
  const aSel = select([['', '— asset —'], ...assets.items.map((a) => [a.asset_id, a.name])], '', { 'aria-label': 'Asset' }); const vSel = select([['', '— version —']], '', { 'aria-label': 'Version' });
  aSel.onchange = async () => { vSel.replaceChildren(h('option', { value: '' }, '— version —')); if (!aSel.value) return; const a = await api.get(`/api/assets/${aSel.value}`); for (const v of a.versions) vSel.append(h('option', { value: v.version_id }, `${v.label} · ${v.stage} · ${v.operation}`)); vSel.value = a.versions.at(-1)?.version_id || ''; };
  root.append(h('div', { class: 'card', style: { marginBottom: '14px' } }, h('h3', null, 'Run validation'), h('div', { class: 'btn-row' }, h('div', { style: { minWidth: '240px' } }, aSel), h('div', { style: { minWidth: '280px' } }, vSel),
    h('button', { class: 'btn primary', onclick: async () => { if (!vSel.value) return toast('Choose an asset and version', '', 'warn'); try { const j = await api.post(`/api/versions/${vSel.value}/process`, { operation: 'validate', params: {} }); const done = await trackJob(j, { label: 'Validation' }); if (done.state === 'COMPLETED') nav(`#/validation/${done.result.validation_id}`); } catch (e) { errorToast(e); } } }, 'Validate'))));
  root.append(h('div', { class: 'card' }, r.items.length ? h('table', null, h('thead', null, h('tr', null, h('th', null, 'Asset'), h('th', null, 'Status'), h('th', { class: 'num' }, 'Overall'), h('th', { class: 'num' }, 'Critical'), h('th', null, 'When'), h('th', null, ''))), h('tbody', null, ...r.items.map((v) => h('tr', null, h('td', null, names[v.asset_id] || v.asset_id), h('td', null, statusChip(v.status)), h('td', { class: 'num' }, fmt.pct(v.overall)), h('td', { class: 'num' }, v.critical_failures), h('td', { class: 'hint' }, fmt.ago(v.created_at)), h('td', null, h('a', { class: 'btn sm', href: `#/validation/${v.validation_id}` }, 'Open')))))) : empty('No validations yet.')));
}

export function reportView(r) {
  const ok = r.status === 'PRODUCTION_READY';
  const cats = Object.entries(r.categories);
  const failing = r.checks.filter((c) => c.status === 'failed' || c.status === 'warning');
  return h('div', null,
    h('div', { class: 'card', style: { marginBottom: '14px' } }, h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } },
      h('div', null, h('div', { class: 'hint' }, `${r.asset_name} · ${r.version_label || ''}`), h('div', { class: `big-status ${ok ? 'ok' : r.status === 'FAILED' ? 'err' : 'warn'}` }, r.status.replace(/_/g, ' ')), h('div', { class: 'hint' }, `${r.critical_failures} critical · ${r.major_failures} major failure(s) · ${r.seconds}s`)),
      h('div', { style: { textAlign: 'right' } }, h('div', { class: 'big-status' }, `${r.overall}%`), h('div', { class: 'hint' }, 'overall score'))),
      r.blocking_reasons.length ? notice('err', h('b', null, 'Not production ready:'), h('ul', null, ...r.blocking_reasons.map((x) => h('li', null, x))), h('div', { class: 'hint' }, 'A high score never overrides a critical failure.')) : notice('ok', 'No critical or major failures, and the overall score meets the threshold.'),
      ...cats.map(([k, c]) => h('div', { class: 'scoreRow' }, h('div', null, fmt.title(k)), bar(c.applicable ? c.score / 100 : 0, !c.applicable ? 'na' : c.score >= 90 ? 'ok' : c.score >= 70 ? 'warn' : 'err'), h('div', { class: 'mono', style: { textAlign: 'right' } }, c.applicable ? fmt.pct(c.score) : 'n/a')))),
    failing.length ? h('div', { class: 'card', style: { marginBottom: '14px' } }, h('h3', null, 'Needs attention'), h('table', null, h('tbody', null, ...failing.map((c) => h('tr', null, h('td', { class: 'mono' }, c.id), h('td', null, statusChip(c.status), ' ', h('span', { class: 'chip' }, c.severity)), h('td', null, h('b', null, c.title), h('div', { class: 'hint' }, c.message))))))) : null,
    h('div', { class: 'card' }, h('h3', null, 'All checks'), h('table', null, h('thead', null, h('tr', null, h('th', null, 'ID'), h('th', null, 'Category'), h('th', null, 'Check'), h('th', null, 'Result'), h('th', null, 'Detail'))),
      h('tbody', null, ...r.checks.map((c) => h('tr', null, h('td', { class: 'mono' }, c.id), h('td', null, fmt.title(c.category)), h('td', null, c.title, h('div', { class: 'hint' }, c.severity)), h('td', null, statusChip(c.status)), h('td', { class: 'hint' }, c.message)))))));
}

async function detail(root, id) {
  const r = await api.get(`/api/validations/${id}`);
  root.append(h('div', { class: 'page-head' }, h('div', null, h('a', { href: '#/validation' }, '← Validation'), h('h1', { style: { marginTop: '6px' } }, 'Validation report')), h('div', { class: 'spacer' }), h('a', { class: 'btn', href: `#/studio/${r.asset_id}/${r.version_id}` }, 'Open in 3D Studio')), reportView(r));
}
