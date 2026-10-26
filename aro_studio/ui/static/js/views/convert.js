// One-click "Convert to 3D": one image in, one verified GLB out (reconstruct -> prepare -> export, a single queued job).
// The model runs for real or the job fails; the panel says exactly which step stopped and what was kept.
import { api } from '../api.js';
import { bar, errorToast, field, fmt, h, icon, notice, select, statusChip, toast } from '../dom.js';
import { isTerminal, trackJob } from '../jobs.js';

const OK_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);
const STEPS = [
  { key: 'check', label: 'Check the image' },
  { key: 'reconstruct', label: 'Reconstruct 3D' },
  { key: 'prepare', label: 'Prepare the mesh' },
  { key: 'export', label: 'Export GLB' },
];
const slug = (s) => (s || 'model').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'model';

export function convertPanel({ categories, getEngine, getLimits, presets, defaultPreset }) {
  const st = { file: null, thumb: null, dims: null, problem: '', phase: 'idle', job: null, result: null, failure: null, asset: null, stepStates: {}, progress: 0, message: '' };
  const input = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true, 'aria-label': 'Choose an image to convert' });
  const drop = h('div', { class: 'dropzone', tabindex: 0, role: 'button', 'aria-label': 'Drop an image here or choose a file' }, icon('upload'), h('div', null, 'Drop an image here, or click to choose (PNG, JPG, WebP)'));
  const nameInput = h('input', { maxlength: 120, placeholder: 'Asset name', 'aria-label': 'Asset name' });
  const categoryInput = select(categories, 'other', { 'aria-label': 'Asset category' });
  const lengthInput = h('input', { type: 'number', min: 0.02, max: 100, step: 0.01, placeholder: 'optional, e.g. 0.8', 'aria-label': 'Real length in metres' });
  const presetInput = select(Object.keys(presets || { BALANCED: 1 }), defaultPreset || 'BALANCED', { 'aria-label': 'Quality preset' });
  const go = h('button', { class: 'btn primary', disabled: true }, icon('play'), 'Convert to 3D');
  const reason = h('div', { class: 'hint convert-reason' });
  const preview = h('div', { class: 'convert-preview' });
  const tracker = h('div');
  const outcome = h('div');

  const limits = () => getLimits() || { max_upload_mb: 25, max_image_pixels: 64_000_000, min_image_side: 64 };
  const busy = () => st.phase === 'uploading' || st.phase === 'running';

  async function pick(file) {
    if (!file || busy()) return;
    if (st.thumb) URL.revokeObjectURL(st.thumb);
    Object.assign(st, { file, thumb: null, dims: null, problem: '', phase: 'idle', result: null, failure: null, job: null, stepStates: {} });
    nameInput.value = file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim() || 'New asset';
    const lim = limits();
    if (!OK_TYPES.has(file.type)) st.problem = 'This is not a PNG, JPG or WebP image. Export it in one of those formats.';
    else if (file.size > lim.max_upload_mb * 1_000_000) st.problem = `The file is ${fmt.bytes(file.size)}; the limit is ${lim.max_upload_mb} MB. Resize or compress it.`;
    else {
      const url = URL.createObjectURL(file);
      const dims = await new Promise((res) => { const im = new Image(); im.onload = () => res({ w: im.naturalWidth, h: im.naturalHeight }); im.onerror = () => res(null); im.src = url; });
      if (!dims) { URL.revokeObjectURL(url); st.problem = 'The browser could not read this file as an image. It may be corrupt: re-export it.'; }
      else {
        st.thumb = url; st.dims = dims;
        if (Math.min(dims.w, dims.h) < lim.min_image_side) st.problem = `The image is ${dims.w}×${dims.h}; the shorter side must be at least ${lim.min_image_side} px.`;
        else if (dims.w * dims.h > lim.max_image_pixels) st.problem = `The image is ${dims.w}×${dims.h}, above the ${(lim.max_image_pixels / 1e6).toFixed(0)} megapixel limit. Downscale it.`;
      }
    }
    draw();
  }

  function stepState(key) {
    if (key === 'check') return st.phase === 'idle' ? 'pending' : st.phase === 'uploading' ? 'running' : st.job ? 'done' : 'pending';
    return st.stepStates[key] || 'pending';
  }

  function applyJob(j) {
    st.progress = j.progress || 0; st.message = j.message || '';
    const stages = j.result?.stages || j.error?.context?.convert_stages;
    if (stages) {
      for (const s of stages) st.stepStates[s.stage] = { COMPLETED: 'done', FAILED: 'failed', RUNNING: 'running', NOT_RUN: 'pending' }[s.status] || 'pending';
    } else {
      const m = /^Step (\d) of 4/.exec(st.message); const cur = m ? Number(m[1]) : 2;
      ['reconstruct', 'prepare', 'export'].forEach((k, i) => { st.stepStates[k] = i + 2 < cur ? 'done' : i + 2 === cur ? 'running' : 'pending'; });
    }
    if (isTerminal(j.state)) {
      if (j.state === 'COMPLETED') { st.phase = 'done'; st.result = j.result; }
      else { st.phase = 'failed'; st.failure = j; }
    }
    draw();
  }

  go.onclick = async () => {
    if (!st.file || st.problem || busy()) return;
    Object.assign(st, { phase: 'uploading', result: null, failure: null, stepStates: {}, progress: 0, message: 'Uploading and checking the image…' });
    draw();
    try {
      const f = new FormData();
      f.append('file', st.file, st.file.name);
      f.append('name', nameInput.value || ''); f.append('category', categoryInput.value); f.append('preset', presetInput.value);
      if (getEngine()) f.append('engine_id', getEngine().info.id);
      if (lengthInput.value !== '') f.append('length_m', lengthInput.value);
      const r = await api.post('/api/convert', f);
      st.job = r.job; st.asset = r.asset; st.phase = 'running'; draw();
      trackJob(r.job, { label: `Convert · ${r.asset.name}`, silent: true, onUpdate: applyJob });
    } catch (e) {
      st.phase = 'rejected'; st.failure = { error: { message: e.message, recommended_action: e.action } }; draw();
      errorToast(e, 'Could not start the conversion');
    }
  };
  input.onchange = () => { pick(input.files[0]); input.value = ''; };
  drop.onclick = () => !busy() && input.click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); drop.onclick(); } };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); pick(e.dataTransfer.files[0]); };

  function drawTracker() {
    if (st.phase === 'idle' || st.phase === 'rejected') return tracker.replaceChildren();
    const rows = STEPS.map((s, i) => {
      const state = stepState(s.key);
      const mark = { done: '✓', running: '…', failed: '✕', pending: String(i + 1) }[state];
      return h('li', { class: `convert-step ${state}`, 'data-step': s.key, 'data-state': state }, h('span', { class: 'mark' }, mark), h('span', null, s.label));
    });
    tracker.replaceChildren(h('ol', { class: 'convert-steps' }, ...rows), busy() ? h('div', null, bar(st.progress), h('div', { class: 'hint' }, st.message)) : null);
  }

  function drawOutcome() {
    if (st.phase === 'done' && st.result) {
      const r = st.result;
      const who = r.engine?.name || 'the engine';
      const note = r.model_ran ? `Reconstructed by ${who} just now.` : `Reused an identical earlier reconstruction (no GPU time spent; generation ${r.reused_from}).`;
      outcome.replaceChildren(notice('ok', h('b', null, 'Your 3D model is ready.'), h('div', { class: 'hint' }, note),
        h('div', { class: 'btn-row', style: { marginTop: '8px' } },
          r.download ? h('button', { class: 'btn primary', onclick: () => api.download(r.download, `${slug(st.asset?.name)}.glb`).catch(errorToast) }, icon('download'), 'Download GLB') : null,
          h('a', { class: 'btn', href: `#/studio/${r.asset_id}/${r.final_version_id}` }, 'Open in 3D Studio'),
          h('a', { class: 'btn', href: `#/studio/${r.asset_id}/${r.raw_version_id}` }, 'Raw reconstruction')),
        h('div', { style: { marginTop: '8px' } }, statusChip(r.validation?.status || 'NOT_VALIDATED'), ' ', h('span', { class: 'hint' }, r.final_extents_m ? `size ${r.final_extents_m.map((x) => x.toFixed(2)).join(' × ')} m` : '')),
        (r.needs_human || []).length ? h('div', { style: { marginTop: '8px' } }, h('b', null, 'Needs a person to confirm:'), h('ul', null, ...r.needs_human.map((n) => h('li', null, n)))) : null,
        h('p', { class: 'hint' }, 'One photo cannot show hidden surfaces, the true size or which end is the front. Check the model in the 3D Studio before you rely on it.')));
    } else if (st.phase === 'failed' || st.phase === 'rejected') {
      const e = st.failure?.error || {};
      const ctx = e.context || {};
      const failed = ctx.convert_failed_stage; const label = STEPS.find((s) => s.key === failed)?.label;
      outcome.replaceChildren(notice('err', h('b', null, label ? `Stopped at “${label}”.` : 'Could not convert this image.'), h('div', null, e.message || 'Unknown error.'),
        e.recommended_action ? h('div', { class: 'hint' }, `→ ${e.recommended_action}`) : null,
        ctx.raw_version_id ? h('div', { class: 'hint' }, 'The raw reconstruction was kept: ', h('a', { href: `#/studio/${st.asset?.asset_id}/${ctx.raw_version_id}` }, 'open it'), '.') : null,
        h('div', { class: 'btn-row', style: { marginTop: '8px' } }, h('button', { class: 'btn', onclick: () => { st.phase = 'idle'; st.failure = null; st.stepStates = {}; draw(); } }, 'Try again'))));
    } else outcome.replaceChildren();
  }

  function draw() {
    preview.replaceChildren(st.file ? h('div', { class: 'convert-picked' }, st.thumb ? h('img', { src: st.thumb, alt: `Preview of ${st.file.name}` }) : null,
      h('div', null, h('b', null, st.file.name), h('div', { class: 'hint' }, [fmt.bytes(st.file.size), st.dims ? `${st.dims.w}×${st.dims.h}` : ''].filter(Boolean).join(' · ')),
        st.problem ? h('div', { class: 'batch-error', role: 'alert' }, st.problem) : null)) : null);
    for (const el of [nameInput, categoryInput, lengthInput, presetInput]) el.disabled = busy();
    const eng = getEngine();
    const why = !eng ? 'No generation engine is registered.' : !eng.runnable ? `${eng.info.name} cannot run in this environment (see the notice at the top of the page).` : !st.file ? 'Choose an image first.' : st.problem ? 'Fix the problem with the image first.' : busy() ? 'Converting…' : '';
    go.disabled = !!why; reason.textContent = why;
    go.lastChild.textContent = busy() ? 'Converting…' : 'Convert to 3D';
    drawTracker(); drawOutcome();
  }

  const el = h('div', { class: 'card convert-card', id: 'convert-panel' },
    h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('h3', null, 'Convert an image to 3D'), h('span', { class: 'chip accent' }, 'One click')),
    h('p', { class: 'hint' }, 'Any object photo or render: it is reconstructed by the engine chosen at the top right (TripoSR runs locally; TRELLIS.2 and TripoSG run on a GPU worker when one is connected), prepared (cleaned, scaled, textured, with collision and LODs) and exported as a verified GLB — one step at a time, so a problem is reported where it happens.'),
    drop, input, preview,
    h('div', { class: 'row2', style: { marginTop: '10px' } }, field('Asset name', nameInput), field('Asset category', categoryInput)),
    h('div', { class: 'row2' }, field('Real length, front to back (m) — optional', lengthInput, 'A single image cannot tell the true size. Leave empty and the model keeps a 1 m placeholder, marked for review.'), field('Quality preset', presetInput)),
    h('div', { class: 'btn-row', style: { marginTop: '10px' } }, go), reason, tracker, outcome);
  draw();
  return { el, refresh: draw };
}
