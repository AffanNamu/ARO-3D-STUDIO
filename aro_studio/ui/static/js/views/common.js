import { api } from '../api.js';
import { confirmDialog, errorToast, field, fmt, h, icon, modal, nav, select, statusChip, toast } from '../dom.js';
import { trackJob } from '../jobs.js';

let taxonomyCache = null;
export async function taxonomy() { return (taxonomyCache ||= await api.get('/api/taxonomy')); }
export async function categoryOptions() {
  const t = await taxonomy();
  return t.groups.flatMap((g) => g.categories.filter((c) => c.available).map((c) => [c.id, `${g.label} › ${c.label}`]));
}
export const categoryLabel = (t, id) => { for (const g of t.groups) for (const c of g.categories) if (c.id === id) return c.label; return fmt.title(id); };

export async function createProjectDialog() {
  const name = h('input', { placeholder: 'e.g. ARO TITAN 480', maxlength: 120 }); const desc = h('textarea', { style: { minHeight: '70px', fontFamily: 'inherit' } });
  return new Promise((res) => modal('New project', h('div', null, field('Project name', name), field('Description', desc)), [
    { label: 'Cancel', onClick: () => res(null) },
    { label: 'Create project', cls: 'primary', onClick: async () => { try { const p = await api.post('/api/projects', { name: name.value, description: desc.value }); toast('Project created', p.name, 'ok'); res(p); } catch (e) { errorToast(e); return false; } } },
  ]));
}

export async function createAssetDialog(projectId, preset = {}) {
  const cats = await categoryOptions();
  const name = h('input', { value: preset.name || '', maxlength: 120 }); const cat = select(cats, preset.category || 'heavy_truck');
  const man = h('input', { value: preset.manufacturer || '', placeholder: 'ARO Motors' }); const model = h('input', { value: preset.model || '' });
  const drive = h('input', { value: preset.drive_configuration || '', placeholder: '6x4' });
  return new Promise((res) => modal('New asset', h('div', null, field('Asset name', name), field('Category', cat), h('div', { class: 'row2' }, field('Manufacturer', man), field('Model', model)), field('Drive configuration (vehicles)', drive)), [
    { label: 'Cancel', onClick: () => res(null) },
    { label: 'Create asset', cls: 'primary', onClick: async () => {
      try {
        const metadata = {}; if (man.value) { metadata.manufacturer = man.value; metadata.brand = man.value.split(' ')[0]; } if (model.value) metadata.model = model.value; if (drive.value) metadata.drive_configuration = drive.value;
        const a = await api.post(`/api/projects/${projectId}/assets`, { name: name.value, category: cat.value, metadata }); toast('Asset created', a.name, 'ok'); res(a);
      } catch (e) { errorToast(e); return false; }
    } },
  ]));
}

export function uploadImage(projectId, category) {
  return new Promise((res) => {
    const inp = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp' });
    inp.onchange = async () => {
      if (!inp.files[0]) return res(null);
      try { const s = await api.upload(`/api/projects/${projectId}/sources`, inp.files[0], { category }); toast('Image validated and stored', `${s.width}×${s.height} · quality ${(s.report.validation.quality_score * 100).toFixed(0)}%`, 'ok'); res(s); } catch (e) { errorToast(e, 'Image rejected'); res(null); }
    };
    inp.click();
  });
}

export function dropzone(onFile, label = 'Drop an image here or click to choose (PNG, JPG, WebP)') {
  const inp = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true });
  const z = h('div', { class: 'dropzone', tabindex: 0, role: 'button', 'aria-label': label }, icon('upload'), h('div', null, label), inp);
  const pick = (f) => f && onFile(f);
  z.onclick = () => inp.click(); z.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp.click(); } };
  inp.onchange = () => pick(inp.files[0]);
  z.ondragover = (e) => { e.preventDefault(); z.classList.add('over'); }; z.ondragleave = () => z.classList.remove('over');
  z.ondrop = (e) => { e.preventDefault(); z.classList.remove('over'); pick(e.dataTransfer.files[0]); };
  return z;
}

export async function runProcess(versionId, operation, params, label) {
  const job = await api.post(`/api/versions/${versionId}/process`, { operation, params });
  return trackJob(job, { label: label || fmt.title(operation) });
}
export async function startJob(promise, label) { const job = await promise; return trackJob(job, { label }); }

export function assetCard(a, t, onClick) {
  const m = a.metadata || {};
  const lv = a.latest_version;
  return h('div', { class: 'card hover asset-card', tabindex: 0, role: 'link', onclick: onClick, onkeydown: (e) => { if (e.key === 'Enter') onClick(); } },
    h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, statusChip(a.status), h('span', { class: 'chip' }, categoryLabel(t, a.category))),
    h('div', { class: 't', style: { marginTop: '10px' } }, a.name),
    h('div', { class: 'm' }, [m.manufacturer, m.model, m.drive_configuration].filter(Boolean).join(' · ') || 'No metadata'),
    h('div', { class: 'hint' }, `${a.version_count ?? 0} version(s)${lv ? ` · latest ${lv.label} (${lv.stage}) · ${fmt.int(lv.triangle_count)} tris` : ''}`),
    a.production_version_id ? h('div', { style: { marginTop: '8px' } }, h('span', { class: 'chip ok' }, `Production ${m.asset_version || ''}`)) : null);
}
export { confirmDialog, nav };

// <img> that loads through fetch so the Authorization header is sent (plain src cannot).
export function authImage(url, attrs = {}) {
  const img = h('img', { alt: '', ...attrs });
  api.blob(url).then((b) => { img.src = URL.createObjectURL(b); img.onload = () => URL.revokeObjectURL(img.src); }).catch(() => { img.alt = 'image unavailable'; });
  return img;
}
