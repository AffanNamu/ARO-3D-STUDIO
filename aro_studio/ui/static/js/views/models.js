import { api } from '../api.js';
import { confirmDialog, empty, errorToast, fmt, h, kv, notice, statusChip, toast } from '../dom.js';

export async function mount(root) {
  const [eng, mod] = await Promise.all([api.get('/api/engines'), api.get('/api/models')]);
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Models'), h('p', { class: 'sub' }, 'Replaceable engines behind a stable interface. Licences are recorded and enforced.')), h('div', { class: 'spacer' }),
    h('button', { class: 'btn', onclick: async () => { try { await api.post('/api/models/unload'); toast('Model unloaded', 'GPU/RAM released', 'ok'); } catch (e) { errorToast(e); } } }, 'Unload resident model')));
  for (const e of eng.items) {
    const i = e.info, l = i.license, av = e.availability;
    root.append(h('div', { class: 'card', style: { marginBottom: '14px' } },
      h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('h2', null, i.name), h('div', { class: 'btn-row' }, statusChip(e.runnable ? 'ready' : 'blocked'), h('span', { class: `chip ${l.status === 'verified' ? 'ok' : 'warn'}` }, `licence ${l.status}`), e.loaded ? h('span', { class: 'chip accent' }, 'loaded') : null)),
      h('p', null, i.description),
      h('div', { class: 'grid c2' },
        h('div', null, h('h3', null, 'Identity & licence'), kv({ 'Engine id': h('code', null, i.id), Capability: i.capability, 'Model version': i.version, Revision: i.revision || 'not pinned (pin a commit hash in deployment)', Source: h('a', { href: i.source_url, target: '_blank', rel: 'noopener noreferrer' }, i.source_url), Licence: `${l.spdx} · commercial use: ${l.commercial_use}`, 'Licence source': h('a', { href: l.source_url, target: '_blank', rel: 'noopener noreferrer' }, l.source_url), 'Verified by deployer': e.license_verified_by_deployer ? 'yes' : 'no (set ARO_VERIFIED_MODEL_LICENSES)' }),
          h('p', { class: 'hint', style: { marginTop: '8px' } }, l.notes)),
        h('div', null, h('h3', null, 'Runtime'), kv({ Device: e.device, 'VRAM (default)': `${i.requirements.vram_mb_default ?? '?'} MB — ${i.requirements.vram_source || ''}`, 'Estimated (default settings)': `${e.estimate_default.vram_mb ?? '–'} MB VRAM / ${e.estimate_default.ram_mb ?? '–'} MB RAM · ${e.estimate_default.measured ? 'measured/published' : 'estimate, not measured'}`, Packages: (i.requirements.packages || []).join(', '), Weights: i.requirements.weights_download }),
          av.reasons.length ? notice('warn', h('b', null, 'Cannot run here'), h('ul', null, ...av.reasons.map((r) => h('li', null, r)))) : notice('ok', 'All runtime requirements are satisfied.'),
          av.activation.length ? h('div', null, h('b', null, 'Activate: '), av.activation.join(' · ')) : null, ...av.warnings.map((w) => h('div', { class: 'hint' }, '⚠ ' + w)))),
      h('h3', { style: { marginTop: '12px' } }, 'Presets (resource-aware; quality is not guaranteed by name)'),
      h('table', null, h('thead', null, h('tr', null, h('th', null, 'Preset'), h('th', null, 'Settings'))), h('tbody', null, ...Object.entries(e.presets).map(([k, v]) => h('tr', null, h('td', null, h('b', null, k)), h('td', { class: 'mono' }, JSON.stringify(v))))))));
  }
  root.append(h('div', { class: 'card', style: { marginBottom: '14px', borderColor: 'rgba(255,92,108,.4)' } }, h('h3', null, 'Blocked models'),
    ...Object.entries(eng.blocked).filter(([k]) => k !== 'lyra').map(([k, why]) => h('div', null, h('span', { class: 'chip err' }, k), ' ', why)), h('p', { class: 'hint', style: { marginTop: '6px' } }, 'The registry refuses to register these models; they can never become part of the production pipeline.')));
  root.append(h('div', { class: 'card' }, h('h3', null, 'Model events'), mod.events.length ? h('table', null, h('thead', null, h('tr', null, h('th', null, 'When'), h('th', null, 'Model'), h('th', null, 'Event'), h('th', null, 'Device'), h('th', { class: 'num' }, 'Duration'))), h('tbody', null, ...mod.events.map((x) => h('tr', null, h('td', null, fmt.date(x.ts)), h('td', null, x.model_id), h('td', null, x.event), h('td', null, x.device || '—'), h('td', { class: 'num' }, x.duration_s != null ? fmt.dur(x.duration_s) : '—'))))) : empty('No model has been loaded yet (models load lazily on first generation).')));
}
