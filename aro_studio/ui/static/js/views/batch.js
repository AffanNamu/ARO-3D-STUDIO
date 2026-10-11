// Batch image-to-3D panel: several images -> several independent assets (one generation job each).
// It is NOT multi-view reconstruction (several photos of ONE object fused into one model); the UI says so.
import { api } from '../api.js';
import { bar, empty, errorToast, field, fmt, h, icon, select, toast } from '../dom.js';
import { isTerminal, trackJob } from '../jobs.js';

const MAX_ITEMS = 10;
const OK_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);
const WORKING = { QUEUED: 'Queued', INITIALIZING: 'Starting', PREPROCESSING: 'Preparing image', GENERATING: 'Reconstructing', POSTPROCESSING: 'Saving', VALIDATING: 'Checking', RETRYING: 'Retrying' };
let nextId = 1;

const plainStatus = (it) => ({
  Checking: 'Checking…', Ready: 'Ready', Invalid: 'Cannot use', Submitting: 'Uploading…', COMPLETED: 'Done', CANCELLED: 'Cancelled',
}[it.status] || WORKING[it.status] || (it.failed ? 'Failed' : it.status));
const chipClass = (it) => (it.failed || it.status === 'Invalid' ? 'chip err' : it.status === 'COMPLETED' ? 'chip ok' : it.status === 'Ready' ? 'chip' : 'chip info');

function describeError(e) {
  if (!e) return '';
  return e.recommended_action ? `${e.message} — ${e.recommended_action}` : e.message;
}

function readDimensions(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve({ url, width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
    img.src = url;
  });
}

export function batchPanel({ categories, getProject, getEngine, getSettings, getLimits, onJobsChanged }) {
  const st = { items: [], busy: false };
  const input = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', multiple: true, hidden: true, 'aria-label': 'Choose multiple images' });
  const defaultCategory = select(categories, 'other', { 'aria-label': 'Category for all images in this batch' });
  const summary = h('div', { class: 'batch-summary', 'aria-live': 'polite' });
  const reason = h('div', { class: 'hint batch-reason' });
  const overall = h('div');
  const list = h('div', { class: 'batch-list' });
  const go = h('button', { class: 'btn primary', disabled: true }, icon('play'), 'Generate selected images');
  const clearDone = h('button', { class: 'btn', hidden: true }, 'Clear finished');
  const drop = h('div', { class: 'dropzone', tabindex: 0, role: 'button', 'aria-label': 'Drop images here or choose files' }, icon('upload'), h('div', null, 'Drop up to 10 images here, or click to choose (PNG, JPG, WebP)'));

  const limits = () => getLimits() || { max_upload_mb: 25, max_image_pixels: 64_000_000, min_image_side: 64 };

  async function addFiles(files) {
    const room = MAX_ITEMS - st.items.length;
    const picked = Array.from(files || []);
    if (picked.length > room) toast(`Batches are limited to ${MAX_ITEMS} images`, room > 0 ? `Only the first ${room} were added.` : 'Remove an image first.', 'warn');
    for (const file of picked.slice(0, Math.max(0, room))) {
      const it = { id: nextId++, file, name: file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim() || 'New asset', category: defaultCategory.value, status: 'Checking', failed: false, progress: 0, message: '', error: '', asset: null, job: null, version: null, thumb: null, dims: null };
      st.items.push(it);
      precheck(it).then(() => drawItem(it));
    }
    draw();
  }

  async function precheck(it) {
    const lim = limits();
    const bad = (msg) => { it.status = 'Invalid'; it.error = msg; };
    if (!OK_TYPES.has(it.file.type)) return bad('This is not a PNG, JPG or WebP image. Export it in one of those formats.');
    if (it.file.size > lim.max_upload_mb * 1_000_000) return bad(`The file is ${fmt.bytes(it.file.size)}; the limit is ${lim.max_upload_mb} MB. Resize or compress it.`);
    const d = await readDimensions(it.file);
    if (!d) return bad('The browser could not read this file as an image. It may be corrupt: re-export it.');
    it.thumb = d.url; it.dims = `${d.width}×${d.height}`;
    if (Math.min(d.width, d.height) < lim.min_image_side) return bad(`The image is ${it.dims}; the shorter side must be at least ${lim.min_image_side} px.`);
    if (d.width * d.height > lim.max_image_pixels) return bad(`The image is ${it.dims}, above the ${(lim.max_image_pixels / 1e6).toFixed(0)} megapixel limit. Downscale it.`);
    it.status = 'Ready'; it.error = '';
  }

  const release = (it) => { if (it.thumb) URL.revokeObjectURL(it.thumb); };
  const remove = (it) => { release(it); st.items = st.items.filter((x) => x !== it); draw(); };
  const editable = (it) => !st.busy && (it.status === 'Ready' || it.status === 'Invalid');

  function itemCard(it) {
    const canEdit = editable(it) && it.status === 'Ready';
    const nameInput = h('input', { value: it.name, maxlength: 120, disabled: !canEdit, 'aria-label': `Asset name for ${it.file.name}`, onchange: (e) => { it.name = e.target.value; } });
    const catInput = select(categories, it.category, { 'aria-label': `Category for ${it.file.name}`, disabled: !canEdit });
    catInput.onchange = () => { it.category = catInput.value; };
    const working = !!it.job && !it.failed && it.status !== 'COMPLETED' && it.status !== 'CANCELLED';
    const actions = [];
    if (it.status === 'COMPLETED' && it.asset) actions.push(h('a', { class: 'btn sm primary', href: `#/studio/${it.asset.asset_id}${it.version ? `/${it.version}` : ''}` }, 'Open asset'));
    if (it.failed && it.job) actions.push(h('button', { class: 'btn sm', onclick: () => requeue(it) }, 'Re-queue'));
    if (it.failed && !it.job) actions.push(h('button', { class: 'btn sm', onclick: () => { it.failed = false; it.status = 'Ready'; it.error = ''; draw(); } }, 'Edit and retry'));
    if (!st.busy && !working) actions.push(h('button', { class: 'btn sm', 'aria-label': `Remove ${it.file.name}`, onclick: () => remove(it) }, 'Remove'));
    return h('div', { class: `card batch-item${it.failed || it.status === 'Invalid' ? ' bad' : ''}`, 'data-status': it.status },
      h('div', { class: 'batch-thumb' }, it.thumb ? h('img', { src: it.thumb, alt: `Preview of ${it.file.name}` }) : h('div', { class: 'hint' }, it.status === 'Checking' ? 'Reading…' : 'No preview')),
      h('div', { class: 'batch-body' },
        h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('b', { title: it.file.name, class: 'batch-file' }, it.file.name), h('span', { class: chipClass(it), 'data-testid': 'item-status' }, plainStatus(it))),
        h('div', { class: 'hint' }, [fmt.bytes(it.file.size), it.dims].filter(Boolean).join(' · ')),
        h('div', { class: 'row2', style: { marginTop: '6px' } }, field('Asset name', nameInput), field('Asset category', catInput)),
        working ? h('div', null, bar(it.progress), h('div', { class: 'hint' }, it.message || 'Waiting in the queue…')) : null,
        it.error ? h('div', { class: 'batch-error', role: 'alert' }, it.error) : null,
        actions.length ? h('div', { class: 'btn-row', style: { marginTop: '6px' } }, ...actions) : null));
  }

  const cards = new Map();
  function chrome() {
    const n = (f) => st.items.filter(f).length;
    const ready = n((i) => i.status === 'Ready'), done = n((i) => i.status === 'COMPLETED'), failed = n((i) => i.failed || i.status === 'Invalid');
    const busy = n((i) => i.job && !i.failed && i.status !== 'COMPLETED' && i.status !== 'CANCELLED') + n((i) => i.status === 'Submitting');
    summary.textContent = st.items.length ? `${st.items.length} image(s) · ${ready} ready · ${busy} in progress · ${done} done · ${failed} need attention` : 'No images selected yet.';
    const fin = st.items.length ? (done + n((i) => i.failed)) / st.items.length : 0;
    overall.replaceChildren(st.items.length && (busy || done) ? bar(fin) : '');
    go.lastChild.textContent = `Generate selected images${ready ? ` (${ready})` : ''}`;
    clearDone.hidden = !st.items.some((i) => i.status === 'COMPLETED' || i.status === 'CANCELLED');
    const eng = getEngine(), project = getProject();
    const why = !eng ? 'No generation engine is registered.' : !eng.runnable ? `${eng.info.name} cannot run in this environment (see the notice at the top of the page).` : !project ? 'Choose a project in “1 · Target” above.' : !ready ? (st.items.length ? 'Fix or remove the images that need attention.' : 'Add at least one image.') : st.busy ? 'Uploading…' : '';
    go.disabled = !!why;
    reason.textContent = why;
  }

  // full redraw: used when the list itself changes (add / remove / submit)
  function draw() {
    cards.clear();
    list.replaceChildren(...(st.items.length ? st.items.map((it) => { const c = itemCard(it); cards.set(it.id, c); return c; }) : [empty('Choose images of different objects. Each one becomes its own asset.')]));
    chrome();
  }

  // single-card update: used for job progress so typing in another card is never interrupted
  function drawItem(it) {
    const old = cards.get(it.id);
    if (!old || !old.isConnected) return draw();
    const fresh = itemCard(it);
    old.replaceWith(fresh); cards.set(it.id, fresh);
    chrome();
  }

  function applyJob(it, job) {
    it.status = job.state;
    it.progress = job.progress || 0;
    it.message = job.message || '';
    if (job.result?.version_id) it.version = job.result.version_id;
    if (isTerminal(job.state) && job.state !== 'COMPLETED') {
      it.failed = job.state !== 'CANCELLED';
      it.error = job.state === 'CANCELLED' ? 'This job was cancelled.' : describeError(job.error) || `The job ended as ${job.state}.`;
    } else { it.failed = false; it.error = ''; }
    drawItem(it);
    if (isTerminal(job.state)) onJobsChanged?.();
  }

  function follow(it) {
    trackJob(it.job, { label: `Batch · ${it.asset?.name || it.file.name}`, silent: true, onUpdate: (j) => applyJob(it, j) });
  }

  async function requeue(it) {
    try {
      const nj = await api.post(`/api/jobs/${it.job.job_id}/requeue`);
      it.job = nj; it.failed = false; it.error = ''; it.status = 'QUEUED'; it.progress = 0; draw(); follow(it);
    } catch (e) { errorToast(e, 'Could not re-queue'); }
  }

  go.onclick = async () => {
    const project = getProject();
    const ready = st.items.filter((i) => i.status === 'Ready');
    if (!project || !ready.length || st.busy) return;
    st.busy = true; ready.forEach((i) => { i.status = 'Submitting'; i.error = ''; }); draw();
    try {
      const { settings, preprocess, preset, engineId, useCache, force, priority } = getSettings();
      const form = new FormData();
      ready.forEach((i) => form.append('files', i.file, i.file.name));
      form.append('category', defaultCategory.value);
      form.append('items_json', JSON.stringify(ready.map((i) => ({ name: i.name, category: i.category }))));
      form.append('engine_id', engineId); form.append('preset', preset);
      form.append('settings_json', JSON.stringify(settings)); form.append('preprocess_json', JSON.stringify(preprocess));
      form.append('use_cache', String(useCache)); form.append('force', String(force)); form.append('priority', String(priority));
      const result = await api.post(`/api/projects/${project}/batch-generate`, form);
      result.items.forEach((entry) => {
        const it = ready[entry.index]; if (!it) return;
        it.asset = entry.asset || null; it.job = entry.job || null;
        if (entry.status === 'QUEUED') { it.status = 'QUEUED'; follow(it); }
        else { it.failed = true; it.status = 'FAILED'; it.error = describeError(entry.error); }
      });
      toast('Batch submitted', `${result.queued} queued · ${result.failed} could not be queued${result.failed ? ' (the others continue)' : ''}`, result.failed ? 'warn' : 'ok');
    } catch (e) {
      ready.forEach((i) => { i.failed = true; i.status = 'FAILED'; i.error = e.message || 'The batch could not be submitted.'; });
      errorToast(e, 'Batch submission failed');
    } finally { st.busy = false; draw(); onJobsChanged?.(); }
  };
  clearDone.onclick = () => { st.items.filter((i) => i.status === 'COMPLETED' || i.status === 'CANCELLED').forEach(release); st.items = st.items.filter((i) => i.status !== 'COMPLETED' && i.status !== 'CANCELLED'); draw(); };
  defaultCategory.onchange = () => { st.items.filter((i) => i.status === 'Ready').forEach((i) => { i.category = defaultCategory.value; }); draw(); };
  input.onchange = () => { addFiles(input.files); input.value = ''; };
  drop.onclick = () => input.click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); addFiles(e.dataTransfer.files); };

  const el = h('div', { class: 'card', style: { marginTop: '14px' }, id: 'batch-panel' },
    h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('h3', null, 'Batch image-to-3D'), h('span', { class: 'chip' }, `Up to ${MAX_ITEMS} images`)),
    h('p', { class: 'hint' }, 'Each accepted image becomes its own asset and its own reconstruction job. A problem with one image never stops the others.'),
    h('div', { class: 'notice info', style: { margin: '8px 0' } }, h('b', null, 'Batch is not multi-view. '), 'Several photos of the same object are not fused into one model: multi-view reconstruction is a separate capability that is not available yet.'),
    drop, input,
    h('div', { class: 'row2', style: { alignItems: 'end', marginTop: '10px' } }, field('Default category for new images', defaultCategory), h('div', { class: 'btn-row' }, h('button', { class: 'btn', onclick: () => input.click() }, 'Choose images'))),
    h('div', { class: 'btn-row', style: { justifyContent: 'space-between', marginTop: '10px' } }, summary, h('div', { class: 'btn-row' }, clearDone, go)),
    reason, overall, list);
  draw();
  return { el, draw, refresh: chrome, addFiles };
}
