import { api } from '../api.js';
import { bar, empty, fmt, h, nav, notice, statusChip } from '../dom.js';
import { assetCard, createProjectDialog, taxonomy } from './common.js';

let timer;
export async function mount(root) {
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Dashboard'), h('p', { class: 'sub' }, 'The ARO asset factory: reference image → production-ready Unity asset.')), h('div', { class: 'spacer' }),
    h('button', { class: 'btn primary', onclick: async () => { const p = await createProjectDialog(); if (p) nav(`#/projects/${p.project_id}`); } }, 'New project')));
  const body = h('div'); root.append(body);
  const draw = async () => {
    const [sys, eng, jobs, assets, t] = await Promise.all([api.get('/api/system'), api.get('/api/engines'), api.get('/api/jobs?limit=8'), api.get('/api/assets'), taxonomy()]);
    const r = sys.resources; const gpu = r.gpu;
    const ramUsed = 1 - r.ram_available_mb / r.ram_total_mb; const diskUsed = 1 - r.disk_free_mb / r.disk_total_mb;
    const e = eng.items[0];
    body.replaceChildren(
      e && !e.runnable ? notice('warn', h('b', null, `${e.info.name} cannot run in this environment.`), h('ul', null, ...e.availability.reasons.map((x) => h('li', null, x)), !e.license_verified_by_deployer ? h('li', null, `Weights licence (${e.info.license.spdx}) is "${e.info.license.status}" – deployer verification required (ARO_VERIFIED_MODEL_LICENSES=${e.info.id}).`) : null),
        e.availability.activation.length ? h('div', { class: 'hint', style: { marginTop: '6px' } }, 'To activate: ', e.availability.activation.join(' · ')) : null,
        h('div', { class: 'hint', style: { marginTop: '6px' } }, 'Everything after reconstruction (geometry, materials, vehicle, collision, LOD, validation, export) still works: import a mesh or use the ARO TITAN 480 procedural reference.')) : null,
      h('div', { class: 'grid c4' },
        h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'CPU'), h('div', { class: 'v' }, `${r.cpu_count} vCPU`), bar(r.cpu_percent / 100)),
        h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'RAM'), h('div', { class: 'v' }, `${fmt.bytes(r.ram_available_mb * 2 ** 20)} free`), bar(ramUsed, ramUsed > 0.85 ? 'err' : ramUsed > 0.65 ? 'warn' : ''), h('div', { class: 'hint' }, `of ${fmt.bytes(r.ram_total_mb * 2 ** 20)} · process ${r.process_rss_mb} MB`)),
        h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'Disk'), h('div', { class: 'v' }, `${fmt.bytes(r.disk_free_mb * 2 ** 20)} free`), bar(diskUsed, diskUsed > 0.9 ? 'err' : ''), h('div', { class: 'hint' }, `studio data ${sys.data_dir_size_mb} MB`)),
        h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'GPU / VRAM'), h('div', { class: 'v' }, gpu.available ? gpu.name : 'No GPU'), gpu.available ? bar(1 - gpu.free_mb / gpu.total_mb) : bar(0, 'na'), h('div', { class: 'hint' }, gpu.available ? `${gpu.free_mb} / ${gpu.total_mb} MB free` : 'CPU-only environment'))),
      h('div', { class: 'grid c2', style: { marginTop: '14px' } },
        h('div', { class: 'card' }, h('h3', null, 'Pipeline'), h('div', { class: 'statusbar' }, ...['Image', 'Analysis', 'Preprocess', 'Image→3D', 'Raw asset', 'Geometry', 'Materials', 'Textures', 'Vehicle', 'Collision', 'LOD', 'Validation', 'Version', 'Export', 'Unity 6'].map((s, i) => h('span', { class: `chip ${i === 3 && e && !e.runnable ? 'warn' : 'accent'}` }, s))),
          h('p', { class: 'hint', style: { marginTop: '10px' } }, 'The Image→3D stage is highlighted amber when the selected engine cannot run in this environment; it is never replaced by placeholder geometry.')),
        h('div', { class: 'card' }, h('h3', null, 'Queue'), h('div', { class: 'btn-row' }, ...Object.entries(sys.queue.by_state).map(([k, v]) => h('span', { class: 'chip' }, `${k}: ${v}`)), !Object.keys(sys.queue.by_state).length ? h('span', { class: 'hint' }, 'No jobs yet.') : null),
          h('p', { class: 'hint', style: { marginTop: '8px' } }, `Workers: ${sys.workers} · model resident: ${sys.models.resident || 'none'} · cache hits: ${sys.cache.cache_hits}/${sys.cache.completed}`))),
      h('div', { class: 'grid c2', style: { marginTop: '14px' } },
        h('div', { class: 'card' }, h('h3', null, 'Recent assets'), assets.items.length ? h('div', { class: 'grid' }, ...assets.items.slice(0, 4).map((a) => assetCard(a, t, () => nav(`#/studio/${a.asset_id}`)))) : empty('No assets yet. Create a project, then an asset.')),
        h('div', { class: 'card' }, h('h3', null, 'Recent jobs'), jobs.items.length ? h('table', null, h('thead', null, h('tr', null, h('th', null, 'Job'), h('th', null, 'State'), h('th', null, 'When'))),
          h('tbody', null, ...jobs.items.map((j) => h('tr', null, h('td', null, j.kind, j.params?.operation ? ` · ${j.params.operation}` : ''), h('td', null, statusChip(j.state)), h('td', { class: 'hint' }, fmt.ago(j.created_at)))))) : empty('No jobs yet.'))));
  };
  await draw(); timer = setInterval(() => draw().catch(() => {}), 5000);
}
export function unmount() { clearInterval(timer); }
