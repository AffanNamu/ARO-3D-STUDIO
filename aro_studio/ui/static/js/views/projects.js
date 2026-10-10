import { api } from '../api.js';
import { confirmDialog, empty, errorToast, fmt, h, icon, nav, promptDialog, statusChip, toast } from '../dom.js';
import { assetCard, authImage, createAssetDialog, createProjectDialog, taxonomy, uploadImage } from './common.js';

export async function mount(root, [pid]) { return pid ? detail(root, pid) : list(root); }

async function list(root) {
  const q = h('input', { placeholder: 'Search projects…', 'aria-label': 'Search projects', style: { maxWidth: '280px' } });
  const show = h('select', { 'aria-label': 'Status filter', style: { maxWidth: '150px' } }, ...[['', 'Active + archived'], ['active', 'Active'], ['archived', 'Archived']].map(([v, l]) => h('option', { value: v }, l)));
  const grid = h('div', { class: 'grid auto' });
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Projects'), h('p', { class: 'sub' }, 'Each project holds source images, assets, versions, exports and full history.')), h('div', { class: 'spacer' }), q, show,
    h('button', { class: 'btn primary', onclick: async () => { const p = await createProjectDialog(); if (p) nav(`#/projects/${p.project_id}`); } }, icon('plus'), 'New project')), grid);
  const draw = async () => {
    const r = await api.get(`/api/projects?${new URLSearchParams({ ...(q.value ? { q: q.value } : {}), ...(show.value ? { status: show.value } : {}) })}`);
    grid.replaceChildren(...(r.items.length ? r.items.map((p) => h('div', { class: 'card hover', tabindex: 0, onclick: () => nav(`#/projects/${p.project_id}`), onkeydown: (e) => e.key === 'Enter' && nav(`#/projects/${p.project_id}`) },
      h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, statusChip(p.status), h('span', { class: 'hint' }, fmt.ago(p.updated_at))), h('h2', { style: { marginTop: '10px' } }, p.name), h('p', null, p.description || 'No description'), h('div', { class: 'hint' }, `${p.asset_count} asset(s) · ${p.project_id}`))) : [empty('No projects match.')]));
  };
  q.oninput = draw; show.onchange = draw; await draw();
}

async function detail(root, pid) {
  const [p, t, hist] = await Promise.all([api.get(`/api/projects/${pid}`), taxonomy(), api.get(`/api/projects/${pid}/history`)]);
  const refresh = () => { root.replaceChildren(); return detail(root, pid); };
  const act = (fn, msg) => async () => { try { await fn(); if (msg) toast(msg, '', 'ok'); } catch (e) { errorToast(e); } };
  root.append(h('div', { class: 'page-head' }, h('div', null, h('div', { class: 'btn-row' }, h('a', { href: '#/projects' }, '← Projects'), statusChip(p.status)), h('h1', { style: { marginTop: '6px' } }, p.name), h('p', { class: 'sub' }, p.description || p.project_id)), h('div', { class: 'spacer' }),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', onclick: act(async () => { const n = await promptDialog('Rename project', 'Name', p.name); if (n) { await api.patch(`/api/projects/${pid}`, { name: n }); await refresh(); } }) }, 'Rename'),
      h('button', { class: 'btn', onclick: act(async () => { const d = await api.post(`/api/projects/${pid}/duplicate`, {}); nav(`#/projects/${d.project_id}`); }, 'Project duplicated') }, 'Duplicate'),
      p.status === 'active' ? h('button', { class: 'btn', onclick: act(async () => { await api.post(`/api/projects/${pid}/archive`); await refresh(); }, 'Archived') }, icon('archive'), 'Archive') : h('button', { class: 'btn', onclick: act(async () => { await api.post(`/api/projects/${pid}/restore`); await refresh(); }, 'Restored') }, 'Restore'),
      h('button', { class: 'btn', onclick: act(() => api.download(`/api/projects/${pid}/archive.zip`, `${p.name.replace(/\W+/g, '-')}-project.zip`)) }, icon('download'), 'Export project'),
      h('button', { class: 'btn danger', onclick: act(async () => { if (await confirmDialog('Delete project?', `"${p.name}" will be hidden (soft delete). Files are kept until permanently deleted.`, 'Delete', true)) { await api.del(`/api/projects/${pid}`); nav('#/projects'); } }) }, icon('trash'), 'Delete'))));
  const assets = h('div', { class: 'grid auto' }, ...(p.assets.length ? p.assets.map((a) => assetCard({ ...a, version_count: undefined }, t, () => nav(`#/studio/${a.asset_id}`))) : [empty('No assets yet.')]));
  const srcGrid = h('div', { class: 'grid c3' }, ...(p.sources.length ? p.sources.map((s) => srcCard(pid, s)) : [empty('No source images yet.')]));
  root.append(h('div', { class: 'grid c2', style: { gridTemplateColumns: '2fr 1fr' } },
    h('div', null,
      h('div', { class: 'card', style: { marginBottom: '14px' } }, h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('h3', null, 'Assets'), h('button', { class: 'btn sm primary', onclick: act(async () => { const a = await createAssetDialog(pid); if (a) nav(`#/studio/${a.asset_id}`); }) }, icon('plus'), 'New asset')), assets),
      h('div', { class: 'card' }, h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('h3', null, 'Source images (concepts)'), h('button', { class: 'btn sm', onclick: act(async () => { if (await uploadImage(pid)) await refresh(); }) }, icon('upload'), 'Upload concept')), srcGrid)),
    h('div', { class: 'card' }, h('h3', null, 'History'), h('ul', { class: 'timeline scroll', style: { maxHeight: '620px' } }, ...hist.items.map((e) => h('li', null, h('div', null, e.title), e.detail ? h('div', { class: 'hint' }, e.detail) : null, h('div', { class: 't' }, `${fmt.date(e.ts)} · ${e.type}`)))))));
}

function srcCard(pid, s) {
  const v = s.report.validation, a = s.report.analysis;
  return h('div', { class: 'card' }, authImage(`/api/projects/${pid}/sources/${s.sha256}/image`, { class: 'thumb', alt: s.filename }), h('div', { style: { marginTop: '8px', fontWeight: 600 } }, s.filename), h('div', { class: 'hint' }, `${s.width}×${s.height} · ${fmt.bytes(s.size_bytes)} · quality ${(v.quality_score * 100).toFixed(0)}%`),
    h('div', { class: 'btn-row', style: { marginTop: '6px' } }, h('span', { class: 'chip' }, `bg: ${a.background_type}`), h('span', { class: 'chip' }, `mode: ${a.recommended_mode}`)), ...v.warnings.map((w) => h('div', { class: 'hint', style: { color: 'var(--warn)' } }, '⚠ ' + w)), h('div', { class: 'hint mono', style: { marginTop: '4px' } }, s.sha256.slice(0, 16) + '…'));
}
