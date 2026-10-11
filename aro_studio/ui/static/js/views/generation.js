import { api } from '../api.js';
import { confirmDialog, empty, errorToast, field, fmt, h, kv, nav, notice, select, statusChip, toast } from '../dom.js';
import { isTerminal, trackJob } from '../jobs.js';
import { authImage, categoryOptions, createAssetDialog, createProjectDialog, uploadImage } from './common.js';
import { batchPanel } from './batch.js';

let timer;
const PRESET_HELP = { LOW_RESOURCE: 'Smaller marching-cubes grid and chunk size: lower VRAM/RAM, lower detail.', BALANCED: 'TripoSR defaults (256³ grid): the only configuration with a published VRAM figure.', HIGH_QUALITY: 'Finer 320³ grid: more detail and more VRAM/time. Not benchmarked here.' };

export async function mount(root, [assetId]) {
  const [projects, engines, categories, system] = await Promise.all([api.get('/api/projects'), api.get('/api/engines'), categoryOptions(), api.get('/api/system')]);
  const eng = engines.items.find((e) => e.runnable) || engines.items[0];
  const st = { project: null, asset: null, sha: null };
  const projSel = select([['', '— choose project —'], ...projects.items.filter((p) => p.status === 'active').map((p) => [p.project_id, p.name])], '', { 'aria-label': 'Project' });
  const assetSel = select([['', '— choose asset —']], '', { 'aria-label': 'Asset' });
  const srcBox = h('div'); const preview = h('div'); const assetInfo = h('div', { class: 'hint' });
  const presetSel = select(Object.keys(eng?.presets || { BALANCED: 1 }), 'BALANCED', { 'aria-label': 'Preset' });
  const presetHelp = h('div', { class: 'hint' }, PRESET_HELP.BALANCED);
  const bg = select([['auto', 'Automatic (recommended)'], ['none', 'Keep original background'], ['border_color_matte', 'Plain-background matte (classical)'], ['rembg', 'Neural matting (rembg, if installed)']], 'auto', { 'aria-label': 'Background removal' });
  const fg = h('input', { type: 'range', min: 0.5, max: 1, step: 0.01, value: 0.85, 'aria-label': 'Foreground ratio' }); const fgv = h('span', { class: 'mono' }, '0.85');
  const mc = h('input', { type: 'number', min: 32, max: 512, placeholder: 'preset default', 'aria-label': 'Marching cubes resolution' }); const chunk = h('input', { type: 'number', min: 0, placeholder: 'preset default', 'aria-label': 'Chunk size' });
  const cache = h('input', { type: 'checkbox', checked: true }); const force = h('input', { type: 'checkbox' }); const prio = select([['1', '1 · urgent'], ['5', '5 · normal'], ['9', '9 · background']], '5');
  const go = h('button', { class: 'btn primary', disabled: true }, 'Queue generation');
  const histBox = h('div');
  let batchUi = null;

  const loadAssets = async () => {
    const r = st.project ? await api.get(`/api/assets?project_id=${st.project}`) : { items: [] };
    assetSel.replaceChildren(...[['', '— choose asset —'], ...r.items.map((a) => [a.asset_id, `${a.name} (${a.category})`])].map(([v, l]) => h('option', { value: v, selected: v === st.asset }, l)));
    const p = st.project ? await api.get(`/api/projects/${st.project}`) : { sources: [] };
    srcBox.replaceChildren(p.sources.length ? h('div', { class: 'grid c3' }, ...p.sources.map((s) => h('label', { class: 'card', style: { cursor: 'pointer', padding: '8px', borderColor: st.sha === s.sha256 ? 'var(--accent)' : '' } }, h('input', { type: 'radio', name: 'src', checked: st.sha === s.sha256, onchange: () => { st.sha = s.sha256; loadAssets(); drawPreview(); update(); } }), ' ', s.filename, authImage(`/api/projects/${st.project}/sources/${s.sha256}/image`, { class: 'thumb' })))) : h('div', { class: 'hint' }, 'No source images yet.'),
      st.project ? h('div', { style: { marginTop: '8px' } }, h('button', { class: 'btn sm', onclick: async () => { const s = await uploadImage(st.project, null); if (s) { st.sha = s.sha256; loadAssets(); drawPreview(); update(); } } }, 'Upload concept image')) : null);
    update();
  };
  const drawPreview = () => {
    if (!st.project || !st.sha) return preview.replaceChildren();
    const qs = new URLSearchParams({ remove_background: bg.value, foreground_ratio: fg.value });
    preview.replaceChildren(h('h3', null, 'Model input preview'), authImage(`/api/projects/${st.project}/sources/${st.sha}/preprocessed.png?${qs}`, { class: 'thumb', style: { maxWidth: '260px' } }), h('div', { class: 'hint' }, 'This exact image (subject on neutral grey) is what the engine receives.'));
  };
  const update = () => {
    go.disabled = !(st.project && st.asset && st.sha && eng?.runnable);
    go.title = !eng?.runnable ? 'The engine cannot run in this environment (see the notice above).' : '';
    batchUi?.refresh();
  };
  projSel.onchange = () => { st.project = projSel.value || null; st.asset = null; st.sha = null; batchUi?.refresh(); loadAssets(); drawPreview(); };
  assetSel.onchange = () => { st.asset = assetSel.value || null; update(); };
  presetSel.onchange = () => { presetHelp.textContent = PRESET_HELP[presetSel.value] || ''; };
  bg.onchange = drawPreview; fg.oninput = () => { fgv.textContent = fg.value; }; fg.onchange = drawPreview;
  go.onclick = async () => {
    try {
      const settings = {}; if (mc.value) settings.mc_resolution = Number(mc.value); if (chunk.value) settings.chunk_size = Number(chunk.value);
      const job = await api.post(`/api/assets/${st.asset}/generate`, { image_sha256: st.sha, engine_id: eng.info.id, preset: presetSel.value, settings, preprocess: { remove_background: bg.value, foreground_ratio: Number(fg.value) }, use_cache: cache.checked, force: force.checked, priority: Number(prio.value) });
      trackJob(job, { label: 'Generation', onDone: (j) => { drawHist(); if (j.state === 'COMPLETED') toast('Raw asset saved', 'Open it in the 3D Studio to inspect and process.', 'ok'); } }); drawHist();
    } catch (e) { errorToast(e); }
  };
  const drawHist = async () => {
    const r = await api.get('/api/jobs?kind=generation&limit=15'); const gens = await api.get('/api/generations');
    const gmap = Object.fromEntries(gens.items.map((g) => [g.job_id, g]));
    histBox.replaceChildren(r.items.length ? h('table', null, h('thead', null, h('tr', null, h('th', null, 'Job'), h('th', null, 'State'), h('th', null, 'Progress'), h('th', null, 'Model'), h('th', null, 'Time'), h('th', null, ''))), h('tbody', null, ...r.items.flatMap((j) => {
      const g = gmap[j.job_id]; const model = j.error?.context?.model || j.resources?.annotations?.model;
      return [h('tr', null, h('td', null, h('span', { class: 'mono' }, j.job_id.slice(0, 12)), h('div', { class: 'hint' }, fmt.ago(j.created_at))), h('td', null, statusChip(j.state)), h('td', null, j.message || '—'),
        h('td', null, model ? `${model.id} · ${j.result?.model_ran === false ? 'cache hit' : g?.device || ''}` : '—'), h('td', null, j.resources?.seconds != null ? fmt.dur(j.resources.seconds) : '—'),
        h('td', null, h('div', { class: 'btn-row' }, j.state === 'COMPLETED' && j.result?.version_id ? h('a', { class: 'btn sm', href: `#/studio/${j.asset_id}/${j.result.version_id}` }, 'Open in Studio') : null,
          isTerminal(j.state) && j.state !== 'COMPLETED' ? h('button', { class: 'btn sm', onclick: async () => { const nj = await api.post(`/api/jobs/${j.job_id}/requeue`); trackJob(nj, { label: 'Generation', onDone: drawHist }); drawHist(); } }, 'Re-queue') : null, !isTerminal(j.state) ? h('button', { class: 'btn sm', onclick: () => api.post(`/api/jobs/${j.job_id}/cancel`).then(drawHist).catch(errorToast) }, 'Cancel') : null))),
        j.error ? h('tr', null, h('td', { colspan: 6 }, notice('err', h('b', null, j.error.message), h('div', null, `→ ${j.error.recommended_action || ''}`), h('details', null, h('summary', { class: 'hint' }, 'Preserved failure record (input, model, resources, log)'), h('pre', { class: 'log' }, JSON.stringify({ code: j.error.code, params: j.params, context: j.error.context, resources: j.resources && { start: j.resources.at_start && { ram_available_mb: j.resources.at_start.ram_available_mb, disk_free_mb: j.resources.at_start.disk_free_mb, gpu: j.resources.at_start.gpu } } }, null, 2)))))) : null].filter(Boolean);
    }))) : empty('No generation jobs yet.'));
  };

  batchUi = batchPanel({
    categories, getProject: () => st.project, getEngine: () => eng, getLimits: () => system.limits,
    getSettings: () => {
      const settings = {}; if (mc.value) settings.mc_resolution = Number(mc.value); if (chunk.value) settings.chunk_size = Number(chunk.value);
      return { settings, preprocess: { remove_background: bg.value, foreground_ratio: Number(fg.value) }, preset: presetSel.value, engineId: eng.info.id, useCache: cache.checked, force: force.checked, priority: Number(prio.value) };
    },
    onJobsChanged: () => drawHist().catch(() => {}),
  });
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Generation'), h('p', { class: 'sub' }, 'Single-image 3D reconstruction as a queued job. The model runs for real or the job fails — there is never placeholder geometry.'))));
  if (eng && !eng.runnable) root.append(notice('warn', h('b', null, `${eng.info.name} cannot run in this environment, so generation is disabled.`), h('ul', null, ...eng.availability.reasons.map((r) => h('li', null, r)), !eng.license_verified_by_deployer ? h('li', null, `Weights licence not yet verified by the deployer (ARO_VERIFIED_MODEL_LICENSES=${eng.info.id}).`) : null), eng.availability.activation.length ? h('div', { class: 'hint' }, 'Activate: ' + eng.availability.activation.join(' · ')) : null,
    h('div', { style: { marginTop: '6px' } }, 'You can still import a mesh generated elsewhere or use the TITAN 480 reference in the ', h('a', { href: '#/studio' }, '3D Studio'), '.')));
  root.append(h('div', { class: 'grid c2', style: { gridTemplateColumns: '1.2fr 1fr' } },
    h('div', { class: 'card' }, h('h3', null, '1 · Target'), h('div', { class: 'row2' }, field('Project', projSel), field('Asset', assetSel)),
      h('div', { class: 'btn-row' }, h('button', { class: 'btn sm', onclick: async () => { const p = await createProjectDialog(); if (p) { location.reload(); } } }, 'New project'), h('button', { class: 'btn sm', onclick: async () => { if (!st.project) return toast('Choose a project first', '', 'warn'); const a = await createAssetDialog(st.project); if (a) { st.asset = a.asset_id; await loadAssets(); } } }, 'New asset')),
      h('h3', { style: { marginTop: '14px' } }, '2 · Concept image'), srcBox, preview),
    h('div', { class: 'card' }, h('h3', null, '3 · Engine & settings'), kv({ Engine: eng ? `${eng.info.name} (${eng.info.license.spdx})` : '—', Device: eng?.device || '—' }),
      h('div', { style: { marginTop: '10px' } }), field('Preset', presetSel, null), presetHelp,
      h('div', { class: 'row2', style: { marginTop: '10px' } }, field('Background removal', bg), field('Foreground ratio', h('div', { class: 'btn-row' }, fg, fgv))),
      h('details', null, h('summary', { class: 'hint' }, 'Advanced overrides'), h('div', { class: 'row2', style: { marginTop: '8px' } }, field('Marching-cubes resolution', mc), field('Chunk size (0 = none)', chunk))),
      h('label', { class: 'check', style: { marginTop: '10px' } }, cache, 'Reuse an identical previous generation (saves GPU time)'), h('label', { class: 'check' }, force, 'Force a fresh run'), field('Priority', prio), go,
      h('p', { class: 'hint', style: { marginTop: '8px' } }, 'The cache key is input-image hash + model version + all settings. Estimated needs: ', eng ? `${eng.estimate_default.vram_mb ?? '–'} MB VRAM (${eng.estimate_default.measured ? 'published' : 'estimate'})` : '—'))),
    h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', null, 'Generation jobs'), histBox));
  root.append(batchUi.el);
  if (assetId) { const a = await api.get(`/api/assets/${assetId}`); st.project = a.project_id; projSel.value = a.project_id; await loadAssets(); st.asset = assetId; assetSel.value = assetId; update(); }
  await drawHist(); timer = setInterval(() => drawHist().catch(() => {}), 3000);
}
export function unmount() { clearInterval(timer); }
