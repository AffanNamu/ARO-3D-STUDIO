import { api } from '../api.js';
import { append, bar, clear, confirmDialog, empty, errorToast, field, fmt, h, icon, kv, modal, nav, notice, promptDialog, select, statusChip, toast } from '../dom.js';
import { trackJob } from '../jobs.js';
import { Viewer } from '../viewer.js';
import { assetCard, createAssetDialog, createProjectDialog, runProcess, taxonomy } from './common.js';
import { reportView } from './validation.js';

let viewer = null;
let S = null; // studio state
let rememberedStep = null; // survives re-mounts so the open step stays open after a job finishes

export function unmount() { viewer?.dispose(); viewer = null; S = null; }

export async function mount(root, [assetId, versionId]) {
  if (!assetId) return chooser(root);
  const asset = await api.get(`/api/assets/${assetId}`);
  const versions = asset.versions;
  const cur = versions.find((v) => v.version_id === versionId) || versions.find((v) => v.is_production) || versions.at(-1) || null;
  const [detail, project, t] = await Promise.all([cur ? api.get(`/api/versions/${cur.version_id}`) : null, api.get(`/api/projects/${asset.project_id}`), taxonomy()]);
  S = { asset, versions, cur, detail, project, t, tab: 'inspect', openStep: rememberedStep || (cur ? 'geometry' : 'source') };
  document.getElementById('ctx').hidden = false; document.getElementById('ctx').textContent = `${project.name} › ${asset.name}`;
  const left = h('section', { class: 'left' }), center = h('section', { class: 'center' }), right = h('section', { class: 'right' });
  root.append(h('div', { class: 'studio' }, left, center, right));
  S.left = left; S.right = right; S.center = center;
  drawLeft(); drawRight(); await initViewer(center);
}

async function chooser(root) {
  const [r, t] = await Promise.all([api.get('/api/assets'), taxonomy()]);
  root.className = '';
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, '3D Studio'), h('p', { class: 'sub' }, 'Choose an asset to inspect and process, or start a new one.')), h('div', { class: 'spacer' }),
    h('button', { class: 'btn primary', onclick: async () => { const pr = await api.get('/api/projects'); if (!pr.items.length) { const p = await createProjectDialog(); if (!p) return; const a = await createAssetDialog(p.project_id); if (a) nav(`#/studio/${a.asset_id}`); return; } const p = pr.items[0]; const a = await createAssetDialog(p.project_id); if (a) nav(`#/studio/${a.asset_id}`); } }, icon('plus'), 'New asset')),
    r.items.length ? h('div', { class: 'grid auto' }, ...r.items.map((a) => assetCard(a, t, () => nav(`#/studio/${a.asset_id}`)))) : empty('No assets yet. Create a project and an asset to begin.'));
}

// ---------------------------------------------------------------- viewer
async function initViewer(center) {
  viewer = new Viewer(center);
  if (!viewer.ok) { center.append(h('div', { class: 'vmsg' }, h('div', null, h('h2', null, 'WebGL is not available'), h('p', null, 'The 3D viewer needs WebGL. Processing and export still work without it.')))); return; }
  center.append(toolbar(), h('div', { class: 'vstats', id: 'vstats' }), lightPanel());
  if (!S.cur) { center.append(h('div', { class: 'vmsg' }, h('div', null, h('h2', null, 'No geometry yet'), h('p', null, 'Generate a reconstruction, import a mesh, or create the TITAN 480 reference from the Source step.')))); return; }
  const msg = h('div', { class: 'vmsg' }, h('div', null, 'Loading model…')); center.append(msg);
  try {
    const buf = await api.buffer(`/api/versions/${S.cur.version_id}/preview.glb`);
    const stats = await viewer.load(buf); msg.remove(); S.stats = stats; paintStats(); drawRight(); drawLodButtons();
  } catch (e) { msg.replaceChildren(h('div', null, h('h2', null, 'Could not load the model'), h('p', null, e.message), e.action ? h('p', null, `→ ${e.action}`) : null)); }
}

function toolbar() {
  const btn = (label, fn, on) => h('button', { onclick: (e) => { fn(e.currentTarget); }, class: on ? 'on' : '' }, label);
  const toggle = (label, flag, init) => { const b = btn(label, (el) => { const v = !viewer.flags[flag]; viewer.set(flag, v); el.classList.toggle('on', v); }, init); return b; };
  const shading = (label, mode) => { const b = btn(label, () => { viewer.set('shading', mode); [...b.parentElement.children].forEach((c) => c.classList.toggle('on', c === b)); }, mode === 'pbr'); return b; };
  return h('div', { class: 'vtoolbar' },
    h('div', { class: 'grp', role: 'group', 'aria-label': 'Camera views' }, ...['front', 'rear', 'left', 'right', 'top', 'bottom', 'iso'].map((v) => btn(fmt.title(v), () => viewer.setView(v))), btn('Reset', () => viewer.reset())),
    h('div', { class: 'grp', role: 'group', 'aria-label': 'Shading' }, shading('Material', 'pbr'), shading('Clay', 'clay'), shading('Normals', 'normal'), toggle('Wireframe', 'wire', false)),
    h('div', { class: 'grp', role: 'group', 'aria-label': 'Overlays' }, toggle('Grid', 'grid', true), toggle('Bounds', 'bbox', false), toggle('Collision', 'collision', false), toggle('Rig', 'rig', false)),
    h('div', { class: 'grp', id: 'lodbtns', role: 'group', 'aria-label': 'Level of detail' }),
    h('div', { class: 'grp' }, btn('Light', () => { const p = document.getElementById('vlight'); p.hidden = !p.hidden; }), btn('Stats', () => { const p = document.getElementById('vstats'); p.hidden = !p.hidden; }, true), btn('Screenshot', () => { const a = document.createElement('a'); a.href = viewer.screenshot(); a.download = `${S.asset.name.replace(/\W+/g, '-')}.png`; a.click(); })));
}
function drawLodButtons() {
  const g = document.getElementById('lodbtns'); if (!g) return; clear(g);
  const lv = viewer.lodLevels; if (lv.length < 2) { g.hidden = true; return; } g.hidden = false;
  for (const n of lv) g.append(h('button', { class: n === viewer.lod ? 'on' : '', onclick: () => { viewer.setLod(n); S.stats = viewer.stats(); paintStats(); drawLodButtons(); } }, `LOD${n}`));
}
function lightPanel() {
  const row = (label, key, min, max, step) => h('label', null, label, h('input', { type: 'range', min, max, step, value: viewer.light[key], 'aria-label': label, oninput: (e) => viewer.setLight({ [key]: Number(e.target.value) }) }));
  return h('div', { class: 'vlight', id: 'vlight', hidden: true }, row('Key light', 'key', 0, 4, 0.05), row('Environment', 'env', 0, 2, 0.05), row('Azimuth', 'azimuth', 0, 360, 1), row('Exposure', 'exposure', 0.3, 2.5, 0.05));
}
function paintStats() {
  const el = document.getElementById('vstats'); if (!el || !S.stats) return; const s = S.stats;
  const d = s.dimensions.map((x) => x.toFixed(2)).join(' × ');
  clear(el); append(el, [h('div', null, 'Vertices (GPU) ', h('b', null, fmt.int(s.vertices))), h('div', null, 'Triangles  ', h('b', null, fmt.int(s.triangles))), h('div', null, 'Materials  ', h('b', null, s.materials), '  Textures ', h('b', null, s.textures)),
    h('div', null, 'Size (m)   ', h('b', null, d)), h('div', null, 'File       ', h('b', null, fmt.bytes(s.fileSize))), s.lods.length ? h('div', null, 'LOD        ', h('b', null, `LOD${s.lod}`), '  ', s.lods.map((l) => `${l.level}:${fmt.int(l.triangles)}`).join(' ')) : null]);
}

// ---------------------------------------------------------------- left: pipeline
const isVehicle = () => S.t.groups.find((g) => g.group === 'vehicles').categories.some((c) => c.id === S.asset.category);
const man = () => S.detail?.scene.manifest;
const has = (k) => ({ geometry: S.versions.some((v) => v.operation === 'geometry'), materials: S.versions.some((v) => v.operation === 'materials'), textures: S.versions.some((v) => v.operation === 'textures'), vehicle: !!man()?.vehicle, collision: (man()?.colliders.length || 0) > 0, lod: (man()?.lods.length || 0) > 0, rig: !!man()?.rig, validate: !!S.detail?.validation, export: S.asset.exports.some((e) => e.status === 'COMPLETED') }[k]);

// Navigate to `target` version (or stay) and always re-mount so every panel reflects the new server state.
function reloadStudio(versionId) {
  const hash = `#/studio/${S.asset.asset_id}/${versionId || ''}`;
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange')); else nav(hash);
}
async function afterJob(j) {
  if (j.state !== 'COMPLETED') return;
  reloadStudio(j.result?.version_id && !j.result.validation_id ? j.result.version_id : S.cur?.version_id);
}
async function op(operation, params, label) { if (!S.cur) return toast('Create or import geometry first', '', 'warn'); try { const j = await runProcess(S.cur.version_id, operation, params, label); await afterJob(j); } catch (e) { errorToast(e); } }

function step(key, title, body, vehicleOnly = false) {
  if (vehicleOnly && !isVehicle()) return null;
  const open = S.openStep === key; const done = key !== 'source' && has(key) || (key === 'source' && S.versions.length);
  return h('li', { class: `step ${open ? 'open' : ''} ${done ? 'done' : ''}` }, h('button', { class: 'head', 'aria-expanded': open, onclick: () => { S.openStep = open ? null : key; rememberedStep = S.openStep; drawLeft(); } }, h('span', { class: 'n' }, done ? icon('check') : String(STEPS.indexOf(key) + 1)), title, h('span', { class: 'state' }, done ? 'done' : '')), open ? h('div', { class: 'body' }, body()) : null);
}
const STEPS = ['source', 'geometry', 'materials', 'textures', 'vehicle', 'collision', 'lod', 'validate', 'export'];

function drawLeft() {
  const a = S.asset; const left = S.left; clear(left);
  left.append(h('div', { class: 'pad' },
    h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('a', { href: '#/studio' }, '← Assets'), statusChip(a.status)),
    h('h2', { style: { marginTop: '6px' } }, a.name), h('div', { class: 'hint', style: { marginBottom: '8px' } }, [a.metadata.manufacturer, a.metadata.model, a.metadata.drive_configuration].filter(Boolean).join(' · ') || a.category),
    S.cur ? h('div', { class: 'btn-row', style: { marginBottom: '10px' } }, h('span', { class: 'chip accent' }, `${S.cur.label} · ${S.cur.stage}`), S.cur.is_production ? h('span', { class: 'chip ok' }, '★ production') : null, h('span', { class: 'hint' }, S.cur.operation)) : null,
    h('ol', { class: 'steps' }, ...[
      step('source', 'Source / Inspect', srcBody), step('geometry', 'Geometry', geoBody), step('materials', 'Materials', matBody), step('textures', 'Textures', texBody),
      step('vehicle', 'Vehicle setup', vehBody, true), step('collision', 'Collision', colBody), step('lod', 'LOD', lodBody), step('validate', 'Validate', valBody), step('export', 'Version & Export', expBody)].filter(Boolean))));
}

function srcBody() {
  const a = S.asset; const c = h('div'); const gen = a.generations[0];
  c.append(kv({ Category: a.category, Project: S.project.name, 'Asset id': h('span', { class: 'mono' }, a.asset_id.slice(0, 14) + '…') }));
  const prov = man()?.provenance;
  if (prov) c.append(notice(prov.source === 'ai_reconstruction' ? 'info' : 'warn', h('b', null, `Provenance: ${prov.source.replace(/_/g, ' ')}`), prov.engine_id ? h('div', null, `${prov.engine_id} · ${prov.model_version}`) : null, h('div', { class: 'hint' }, prov.note)));
  c.append(h('div', { class: 'btn-row' }, h('a', { class: 'btn primary', href: `#/generation/${a.asset_id}` }, icon('play'), 'Generate from concept'),
    h('button', { class: 'btn', onclick: importMesh }, icon('upload'), 'Import mesh')));
  if (S.cur?.stage === 'raw') {
    const defaultUp = prov?.source === 'ai_reconstruction' && prov?.engine_id === 'triposr' ? '+Z' : '+Y';
    const upAxis = select(['+Y', '+Z', '-Y', '-Z', '+X', '-X'], defaultUp, { 'aria-label': 'Source up direction' });
    const forwardAxis = select([['', 'Automatic guess (review)'], ['+Z', 'Forward +Z'], ['-Z', 'Forward -Z'], ['+X', 'Forward +X'], ['-X', 'Forward -X'], ['+Y', 'Forward +Y'], ['-Y', 'Forward -Y']], '', { 'aria-label': 'Source forward direction' });
    const length = h('input', { type: 'number', min: 0.05, max: 100, step: 0.1, value: isVehicle() ? 6.5 : 1.0, 'aria-label': 'Approximate object length in metres' });
    const triangles = h('input', { type: 'number', min: 100, max: 25000, step: 1000, value: 24000, 'aria-label': 'Target triangle count' });
    const resolution = select([['512', '512 px · light'], ['1024', '1024 px · balanced'], ['2048', '2048 px · detailed']], '1024', { 'aria-label': 'Baked texture resolution' });
    const prepare = h('button', { class: 'btn primary', onclick: async () => {
      const lengthM = Number(length.value), targetTriangles = Number(triangles.value);
      if (!Number.isFinite(lengthM) || lengthM <= 0 || !Number.isFinite(targetTriangles) || targetTriangles < 100 || targetTriangles > 25000) {
        return toast('Check preparation settings', 'Choose a positive object dimension and 100–25,000 target triangles.', 'warn');
      }
      prepare.disabled = true; prepare.textContent = 'Queueing preparation…';
      try {
        const job = await api.post(`/api/versions/${S.cur.version_id}/auto-process`, {
          length_m: lengthM, up: upAxis.value, forward: forwardAxis.value || null,
          target_triangles: targetTriangles, texture_resolution: Number(resolution.value), lod: true,
        });
        trackJob(job, {
          label: 'Automatic mesh preparation',
          onDone: (done) => {
            if (done.state === 'COMPLETED' && done.result?.final_version_id) {
              nav(`#/studio/${S.asset.asset_id}/${done.result.final_version_id}`);
            } else {
              const report = done.error?.details?.pipeline;
              const failed = report?.steps?.find((step) => step.status === 'FAIL');
              if (failed) toast('Preparation stopped', `${failed.step}: ${failed.detail?.error?.message || 'review the job error details'}`, 'warn');
              reloadStudio(S.cur?.version_id);
            }
          },
        });
      } catch (e) {
        errorToast(e, 'Could not queue preparation');
        prepare.disabled = false; prepare.textContent = 'Prepare mesh for use';
      }
    } }, icon('play'), 'Prepare mesh for use');
    c.append(h('div', { class: 'card', style: { marginTop: '12px', padding: '12px' } },
      h('h3', null, 'Automatic mesh preparation'),
      h('p', { class: 'hint' }, 'Creates new versions while preserving the raw reconstruction. It orients and scales the mesh, cleans geometry, reduces polygons, bakes colour into a texture, creates collision and LODs, then validates.'),
      h('p', { class: 'hint' }, 'One image cannot reveal every hidden surface or reliably identify the front of an object. Review the 3D views and validation report before using an asset in production.'),
      h('div', { class: 'row2', style: { marginTop: '8px' } }, field('Source up direction', upAxis), field('Source forward direction', forwardAxis)),
      h('div', { class: 'row2' }, field('Approximate object length (m)', length), field('Target triangles (max 25,000 for baking)', triangles)),
      field('Texture resolution', resolution), prepare
    ));
  }
  if (a.category === 'heavy_truck') c.append(h('div', { style: { marginTop: '8px' } }, h('button', { class: 'btn', onclick: async () => { try { const v = await api.post(`/api/assets/${a.asset_id}/reference/titan480`); toast('Reference created', 'Procedural ARO TITAN 480 (not AI-generated)', 'ok'); nav(`#/studio/${a.asset_id}/${v.version_id}`); } catch (e) { errorToast(e); } } }, 'Create ARO TITAN 480 reference'),
    h('div', { class: 'hint', style: { marginTop: '4px' } }, 'An original, procedurally authored 6×4 tractor: clearly labelled, never presented as AI output. It lets every stage after reconstruction run for real.')));
  if (gen) c.append(h('div', { style: { marginTop: '10px' } }, h('h3', null, 'Last generation'), kv({ Status: statusChip(gen.status), Engine: `${gen.engine_id}`, Device: gen.device || '—', Inference: gen.execution_time_s != null ? fmt.dur(gen.execution_time_s) : '—', 'Cache': gen.reused_from ? 'reused (no GPU time)' : 'fresh run' })));
  return c;
}
function importMesh() {
  const inp = h('input', { type: 'file', accept: '.glb,.gltf,.obj,.ply,.stl,.zip' });
  inp.onchange = async () => { if (!inp.files[0]) return; try { const r = await api.upload(`/api/assets/${S.asset.asset_id}/import`, inp.files[0]); toast('Mesh imported as raw version', `${fmt.int(r.report.triangles)} triangles, ${r.report.parts} part(s)`, 'ok'); nav(`#/studio/${S.asset.asset_id}/${r.version.version_id}`); } catch (e) { errorToast(e, 'Import failed'); } };
  inp.click();
}

function geoBody() {
  const c = h('div');
  const inspectOut = h('div');
  c.append(h('div', { class: 'btn-row' }, h('button', { class: 'btn sm', onclick: async () => { try { const r = await api.post(`/api/versions/${S.cur.version_id}/inspect`); inspectOut.replaceChildren(inspectView(r)); } catch (e) { errorToast(e); } } }, 'Inspect mesh')), inspectOut);
  const f = { orient: h('input', { type: 'checkbox' }), up: select(['+Y', '+Z', '-Z', '+X', '-X', '-Y'], '+Z'), fwd: select(['+Z', '+Y', '-Y', '+X', '-X', '-Z'], '+X'), scale: h('input', { type: 'checkbox' }), len: h('input', { type: 'number', value: 6.5, step: 0.1, min: 0.1 }), axis: select(['Z', 'X', 'Y'], 'Z'),
    pivot: h('input', { type: 'checkbox' }), clean: h('input', { type: 'checkbox', checked: true }), holes: h('input', { type: 'checkbox' }), maxh: h('input', { type: 'number', value: 200, min: 3 }), smooth: h('input', { type: 'checkbox' }), it: h('input', { type: 'number', value: 5, min: 1, max: 100 }), dec: h('input', { type: 'checkbox' }), tris: h('input', { type: 'number', value: 100000, min: 100 }) };
  c.append(h('h3', { style: { marginTop: '12px' } }, 'Operations (each run creates a new version)'),
    h('label', { class: 'check' }, f.orient, 'Re-orient to +Y up / +Z forward'), h('div', { class: 'row2' }, field('Current up', f.up), field('Current forward', f.fwd)),
    h('label', { class: 'check' }, f.scale, 'Scale to real-world length (m)'), h('div', { class: 'row2' }, field('Length', f.len), field('Axis', f.axis)),
    h('label', { class: 'check' }, f.pivot, 'Pivot at ground centre'), h('label', { class: 'check' }, f.clean, 'Standard cleanup (merge, degenerate, duplicates, fragments, normals)'),
    h('label', { class: 'check' }, f.holes, 'Fill holes up to'), field('Max hole edges', f.maxh), h('label', { class: 'check' }, f.smooth, 'Smooth (Taubin)'), field('Iterations', f.it), h('label', { class: 'check' }, f.dec, 'Decimate to'), field('Target triangles', f.tris),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn primary', onclick: () => {
      const steps = []; if (f.orient.checked) steps.push({ op: 'orient', params: { up: f.up.value, forward: f.fwd.value } }); if (f.scale.checked) steps.push({ op: 'scale', params: { length_m: Number(f.len.value), axis: f.axis.value } }); if (f.pivot.checked) steps.push({ op: 'set_pivot', params: { mode: 'ground_center' } });
      if (f.clean.checked) steps.push({ op: 'remove_invalid' }, { op: 'merge_vertices' }, { op: 'remove_degenerate' }, { op: 'remove_duplicate_faces' }, { op: 'remove_small_components', params: { min_face_ratio: 0.01 } }, { op: 'fix_normals' });
      if (f.holes.checked) steps.push({ op: 'fill_holes', params: { max_hole_edges: Number(f.maxh.value) } }); if (f.smooth.checked) steps.push({ op: 'smooth', params: { iterations: Number(f.it.value) } }); if (f.dec.checked) steps.push({ op: 'decimate', params: { target_faces: Number(f.tris.value) } });
      if (!steps.length) return toast('Select at least one operation', '', 'warn'); op('geometry', { steps }, 'Geometry processing'); } }, 'Run geometry processing')),
    h('p', { class: 'hint' }, 'Operations never modify the source: the result is saved as a new immutable version, and the raw reconstruction stays recoverable.'));
  return c;
}
function inspectView(r) {
  const sev = { critical: 'err', major: 'err', minor: 'warn', info: 'info' };
  return h('div', { style: { marginTop: '8px' } }, kv({ Triangles: fmt.int(r.face_count), Components: r.component_count, Watertight: r.is_watertight ? 'yes' : 'no', Holes: r.hole_count, 'Non-manifold edges': r.nonmanifold_edges, 'Self-intersections': `${r.self_intersections.intersecting_pairs} (${r.self_intersections.status})`, Extents: r.extents.map((x) => x.toFixed(2)).join(' × ') + ' m' }),
    r.issues.length ? h('ul', { style: { margin: '8px 0 0', padding: 0, listStyle: 'none' } }, ...r.issues.map((i) => h('li', { style: { marginBottom: '4px' } }, h('span', { class: `chip ${sev[i.severity]}` }, i.severity), ' ', i.message, i.fix ? h('span', { class: 'hint' }, ` → ${i.fix}`) : null))) : notice('ok', 'No geometry issues detected.'));
}

function matBody() {
  const m = man(); const c = h('div'); if (!m) return c.append(h('div', { class: 'hint' }, 'No geometry yet.')) || c;
  if (isVehicle()) { const ow = h('input', { type: 'checkbox' }); c.append(h('label', { class: 'check' }, ow, 'Overwrite existing assignments'), h('button', { class: 'btn', onclick: () => op('materials', { apply_vehicle_palette: true, overwrite: ow.checked }, 'Materials') }, 'Apply ARO vehicle palette by component role'), h('div', { class: 'hint', style: { margin: '4px 0 10px' } }, 'Paint, metal, chrome, rubber, glass, plastic, lights, interior — mapped from each part’s component role.')); }
  const sel = select(m.materials.map((x) => x.name), m.materials[0]?.name, { 'aria-label': 'Material' });
  const col = h('input', { type: 'color' }), met = h('input', { type: 'range', min: 0, max: 1, step: 0.01 }), rou = h('input', { type: 'range', min: 0, max: 1, step: 0.01 }), alpha = select(['OPAQUE', 'BLEND', 'MASK'], 'OPAQUE'), metv = h('span', { class: 'mono' }), rouv = h('span', { class: 'mono' });
  const hex = (c4) => '#' + c4.slice(0, 3).map((x) => Math.round(Math.pow(x, 1 / 2.2) * 255).toString(16).padStart(2, '0')).join('');
  const fromHex = (s) => [1, 3, 5].map((i) => Math.pow(parseInt(s.slice(i, i + 2), 16) / 255, 2.2));
  const load = () => { const x = m.materials.find((y) => y.name === sel.value); if (!x) return; col.value = hex(x.base_color); met.value = x.metallic; rou.value = x.roughness; alpha.value = x.alpha_mode; metv.textContent = x.metallic.toFixed(2); rouv.textContent = x.roughness.toFixed(2); };
  sel.onchange = load; met.oninput = () => { metv.textContent = Number(met.value).toFixed(2); }; rou.oninput = () => { rouv.textContent = Number(rou.value).toFixed(2); }; load();
  c.append(h('table', null, h('tbody', null, ...m.materials.map((x) => h('tr', null, h('td', null, h('span', { style: { display: 'inline-block', width: '14px', height: '14px', borderRadius: '3px', background: hex(x.base_color), border: '1px solid var(--line-2)', verticalAlign: 'middle' } })), h('td', null, x.name), h('td', { class: 'hint' }, x.category), h('td', { class: 'hint num' }, `M${x.metallic.toFixed(1)} R${x.roughness.toFixed(1)}`))))),
    h('h3', { style: { marginTop: '10px' } }, 'Edit material'), field('Material', sel), h('div', { class: 'row2' }, field('Base colour', col), field('Alpha mode', alpha)), field('Metallic', h('div', { class: 'btn-row' }, met, metv)), field('Roughness', h('div', { class: 'btn-row' }, rou, rouv)),
    h('button', { class: 'btn', onclick: () => { const x = m.materials.find((y) => y.name === sel.value); op('materials', { materials: [{ ...x, base_color: [...fromHex(col.value), x.base_color[3]], metallic: Number(met.value), roughness: Number(rou.value), alpha_mode: alpha.value }], prune_unused: false }, 'Material edit'); } }, 'Save material (new version)'));
  const part = select(m.parts.map((p) => p.name), m.parts[0]?.name), pm = select(m.materials.map((x) => x.name), m.materials[0]?.name);
  c.append(h('h3', { style: { marginTop: '10px' } }, 'Assign'), h('div', { class: 'row2' }, field('Part', part), field('Material', pm)), h('button', { class: 'btn', onclick: () => op('materials', { assignments: { [part.value]: pm.value }, prune_unused: false }, 'Assign material') }, 'Assign'));
  return c;
}

function texBody() {
  const c = h('div'); const m = man(); if (!m) return c;
  const action = select([['bake', 'Unwrap + bake vertex colours to texture'], ['resize', 'Resize textures'], ['compress', 'Compress colour textures (JPEG)']], 'bake'); const res = select(['512', '1024', '2048', '4096'], '1024');
  const raw = S.versions.find((v) => v.stage === 'raw'); const useRaw = h('input', { type: 'checkbox', checked: !!raw && S.cur?.stage !== 'raw' });
  c.append(field('Action', action), field('Resolution (max)', res), h('label', { class: 'check' }, useRaw, 'Project colour from the raw reconstruction (full-resolution source)'),
    h('button', { class: 'btn primary', onclick: () => { const a = action.value; op('textures', a === 'bake' ? { action: 'bake', resolution: Number(res.value), source_version_id: useRaw.checked && raw ? raw.version_id : undefined } : a === 'resize' ? { action: 'resize', resolution: Number(res.value) } : { action: 'compress', format: 'jpeg', quality: 88 }, 'Textures'); } }, 'Run'),
    h('p', { class: 'hint', style: { marginTop: '8px' } }, 'UV unwrapping is limited to 25,000 triangles per atlas (a native-library stability limit): decimate first, then bake colour from the raw mesh. Resolution is yours to choose; not every asset needs 4096.'),
    m.textures.length ? h('table', null, h('tbody', null, ...m.textures.map((x) => h('tr', null, h('td', null, x.name), h('td', { class: 'hint' }, `${x.width}×${x.height} ${x.format}`))))) : h('div', { class: 'hint' }, 'No textures yet: materials are flat-colour.'));
  return c;
}

function vehBody() {
  const m = man(); const c = h('div'); if (!m) return c;
  const v = m.vehicle;
  if (v) c.append(kv({ Vehicle: `${v.identity.manufacturer} ${v.identity.model}`, Category: v.identity.category, 'Drive': v.identity.drive_configuration, Axles: v.axles.length, Wheels: v.wheels.length, Pivots: v.pivots.length, Lights: v.lights.length, Attachments: v.attachment_points.length, Wheelbase: v.wheelbase != null ? `${v.wheelbase.toFixed(2)} m` : '—', 'Centre of mass': v.center_of_mass ? v.center_of_mass.map((x) => x.toFixed(2)).join(', ') : 'not set' }));
  else c.append(notice('warn', 'No vehicle metadata yet. Assign components and provide the vehicle spec below (wheel/axle positions in metres, +Y up, +Z forward).'));
  const roles = ['chassis', 'cabin', 'body', 'bumper', 'grille', 'door', 'window', 'mirror', 'headlight', 'taillight', 'exhaust', 'axle', 'wheel', 'tire', 'attachment', 'wiper', 'interior', 'other'];
  const selects = {}; const rows = m.parts.slice(0, 120).map((p) => { selects[p.name] = select(roles, p.component, { 'aria-label': `Role of ${p.name}`, style: { padding: '3px 6px' } }); return h('tr', null, h('td', { style: { wordBreak: 'break-all' } }, p.name), h('td', null, selects[p.name])); });
  c.append(h('details', null, h('summary', { class: 'hint', style: { cursor: 'pointer', margin: '8px 0' } }, `Component roles (${m.parts.length} parts)`), h('div', { class: 'scroll' }, h('table', null, h('tbody', null, ...rows))),
    h('button', { class: 'btn sm', style: { marginTop: '6px' }, onclick: () => { const map = {}; for (const p of m.parts) if (selects[p.name] && selects[p.name].value !== p.component) map[p.name] = selects[p.name].value; if (!Object.keys(map).length) return toast('No role changes', '', 'warn'); op('vehicle', { component_map: map }, 'Component roles'); } }, 'Apply roles')));
  const ta = h('textarea', { 'aria-label': 'Vehicle specification JSON', spellcheck: 'false', style: { minHeight: '180px' } }); ta.value = JSON.stringify(v ? { ...v, components: undefined } : { identity: { manufacturer: S.asset.metadata.manufacturer || '', brand: S.asset.metadata.brand || '', model: S.asset.metadata.model || '', category: S.asset.category, body_type: '', drive_configuration: S.asset.metadata.drive_configuration || '' }, axles: [], wheels: [], pivots: [], lights: [], attachment_points: [] }, null, 2);
  c.append(h('details', null, h('summary', { class: 'hint', style: { cursor: 'pointer', margin: '8px 0' } }, 'Vehicle specification (JSON, validated server-side)'), ta, h('button', { class: 'btn sm', style: { marginTop: '6px' }, onclick: () => { let spec; try { spec = JSON.parse(ta.value); } catch (e) { return errorToast(e, 'Invalid JSON'); } op('vehicle', { spec }, 'Vehicle spec'); } }, 'Apply vehicle spec')));
  c.append(h('div', { class: 'btn-row', style: { marginTop: '10px' } }, h('button', { class: 'btn', disabled: !v, onclick: () => op('rig', {}, 'Rig & pivots') }, 'Prepare rig & pivots'), h('span', { class: 'hint' }, 'Steering, wheel spin, suspension, doors, mirrors, wipers, lights, attachments.')), h('div', { class: 'hint' }, m.rig ? `Rig ready: ${m.rig.nodes.length} nodes (toggle “Rig” in the viewer).` : 'Rig not prepared yet.'));
  return c;
}

function colBody() {
  const c = h('div'); const m = man(); const kind = select([['vehicle', 'Vehicle (body + cabin hulls)'], ['convex_hull', 'Convex hull'], ['box', 'Box'], ['sphere', 'Sphere'], ['capsule', 'Capsule'], ['mesh', 'Custom collision mesh']], m?.vehicle ? 'vehicle' : 'convex_hull'); const tri = h('input', { type: 'number', value: 255, min: 12, max: 255 }); const wheels = h('input', { type: 'checkbox' });
  c.append(field('Collider type', kind), field('Max triangles per convex hull (Unity/PhysX limit 255)', tri), h('label', { class: 'check' }, wheels, 'Add rolling-sphere wheel colliders (use WheelColliders for real wheel physics)'),
    h('button', { class: 'btn primary', onclick: () => op('collision', { kind: kind.value, max_triangles: Number(tri.value), wheel_colliders: wheels.checked }, 'Collision') }, 'Generate collision'),
    h('p', { class: 'hint', style: { marginTop: '8px' } }, 'Collision is separate from visual geometry (node group “Collision”, COL_* names). Toggle “Collision” in the viewer to see it.'),
    m?.colliders.length ? h('table', null, h('tbody', null, ...m.colliders.map((x) => h('tr', null, h('td', null, x.name), h('td', { class: 'hint' }, x.kind), h('td', { class: 'hint num' }, x.triangle_count ? `${x.triangle_count} tris` : ''))))) : null);
  return c;
}

function lodBody() {
  const c = h('div'); const m = man(); const veh = isVehicle();
  const d = veh ? [[0.55, 0.30], [0.28, 0.15], [0.12, 0.05]] : [[0.5, 0.4], [0.25, 0.2], [0.1, 0.08]];
  const rows = d.map(([r, s], i) => ({ ratio: h('input', { type: 'number', step: 0.01, min: 0.01, max: 0.99, value: r }), sh: h('input', { type: 'number', step: 0.01, min: 0.01, max: 0.9, value: s }), lv: i + 1 }));
  c.append(h('table', null, h('thead', null, h('tr', null, h('th', null, 'Level'), h('th', null, 'Triangle ratio'), h('th', null, 'Screen height'))), h('tbody', null, h('tr', null, h('td', null, 'LOD0'), h('td', { class: 'hint' }, '1.00'), h('td', { class: 'hint' }, '0.60')), ...rows.map((r) => h('tr', null, h('td', null, `LOD${r.lv}`), h('td', null, r.ratio), h('td', null, r.sh))))),
    h('button', { class: 'btn primary', style: { marginTop: '8px' }, onclick: () => { const dropMap = { 1: [], 2: ['interior', 'wiper'], 3: ['interior', 'wiper', 'mirror'] }; const levels = rows.map((r) => ({ level: r.lv, ratio: Number(r.ratio.value), screen_height: Number(r.sh.value), drop_roles: veh ? dropMap[r.lv] : [], merge_static_by_material: veh && r.lv === 3 })); op('lod', { config: { levels, lod0_screen_height: 0.6 } }, 'LOD generation'); } }, 'Generate LODs'),
    h('p', { class: 'hint' }, 'Animated parts (wheels, doors, mirrors, wipers) are never merged; ratios must strictly decrease. LOD0 is never modified.'),
    m?.lods.length ? h('div', { class: 'hint' }, `Current: ${[`LOD0 ${fmt.int(S.detail.scene.stats.triangles)}`, ...m.lods.map((l) => `LOD${l.level} ${fmt.int(l.triangle_count)}`)].join(' → ')}`) : null);
  return c;
}

function valBody() {
  const c = h('div'); const v = S.detail?.validation;
  c.append(h('button', { class: 'btn primary', onclick: () => op('validate', {}, 'Validation') }, icon('play'), 'Run validation on this version'));
  if (v) {
    c.append(h('div', { style: { marginTop: '10px' } }, h('div', { class: 'btn-row' }, statusChip(v.status), h('b', null, `${v.overall}%`), h('span', { class: 'hint' }, `${v.critical_failures} critical · ${v.major_failures} major`)), ...Object.entries(v.categories).filter(([, x]) => x.applicable).map(([k, x]) => h('div', { class: 'scoreRow', style: { gridTemplateColumns: '90px 1fr 44px', margin: '4px 0' } }, h('span', { class: 'hint' }, fmt.title(k)), bar(x.score / 100, x.score >= 90 ? 'ok' : x.score >= 70 ? 'warn' : 'err'), h('span', { class: 'mono' }, fmt.pct(x.score)))),
      v.blocking_reasons.map((r) => h('div', { class: 'hint', style: { color: 'var(--err)' } }, '✕ ' + r)), h('a', { href: `#/validation/${v.validation_id}`, style: { display: 'inline-block', marginTop: '6px' } }, 'Open full report →')));
    if (v.status === 'PRODUCTION_READY' && !S.cur.is_production) { const sv = h('input', { value: '1.0.0', 'aria-label': 'Semantic version' }); c.append(h('div', { style: { marginTop: '12px' } }, field('Asset version', sv), h('button', { class: 'btn', onclick: async () => { try { await api.post(`/api/versions/${S.cur.version_id}/designate-production`, { semver: sv.value }); toast('Designated CURRENT PRODUCTION VERSION', S.cur.label, 'ok'); reloadStudio(S.cur.version_id); } catch (e) { errorToast(e); } } }, '★ Mark as current production version'))); }
  } else c.append(h('div', { class: 'hint', style: { marginTop: '8px' } }, 'Not validated yet. Production readiness is only granted by a validated version with no critical or major failures.'));
  return c;
}

function expBody() {
  const c = h('div'); const fm = { glb: h('input', { type: 'checkbox', checked: true }), gltf: h('input', { type: 'checkbox' }), obj: h('input', { type: 'checkbox' }), unity: h('input', { type: 'checkbox' }) };
  c.append(h('div', { class: 'btn-row', style: { marginBottom: '8px' } }, h('button', { class: 'btn', onclick: () => op('finalize', {}, 'Finalise version') }, 'Save as FINAL version')), h('h3', null, 'Export current version'),
    ...[['glb', 'GLB (single file, all LODs + collision + rig)'], ['gltf', 'glTF (separate .gltf/.bin/textures)'], ['obj', 'OBJ + MTL (LOD0)'], ['unity', 'Unity 6 package (Models, Materials, Textures, LOD, Collision, Metadata, README)']].map(([k, l]) => h('label', { class: 'check' }, fm[k], l)),
    h('button', { class: 'btn primary', onclick: async () => { const formats = Object.keys(fm).filter((k) => fm[k].checked); if (!formats.length) return; try { const j = await api.post(`/api/versions/${S.cur.version_id}/export`, { formats }); await trackJob(j, { label: 'Export' }); reloadStudio(S.cur.version_id); } catch (e) { errorToast(e); } } }, icon('download'), 'Export'),
    h('p', { class: 'hint', style: { marginTop: '8px' } }, 'Every export is re-opened and verified after writing. The Unity package has NOT been imported into Unity by the Studio — see its README for import steps (glTFast) and the status note.'));
  return c;
}

// ---------------------------------------------------------------- right: inspector / versions / validation / exports
function drawRight() {
  const r = S.right; clear(r);
  const tabs = [['inspect', 'Inspect'], ['versions', `Versions (${S.versions.length})`], ['validation', 'Validation'], ['exports', `Exports (${S.asset.exports.length})`]];
  r.append(h('div', { class: 'pad' }, h('div', { class: 'tabs', role: 'tablist' }, ...tabs.map(([k, l]) => h('button', { role: 'tab', class: S.tab === k ? 'on' : '', 'aria-selected': S.tab === k, onclick: () => { S.tab = k; drawRight(); } }, l))), ({ inspect: inspectTab, versions: versionsTab, validation: validationTab, exports: exportsTab })[S.tab]()));
}
function inspectTab() {
  const v = S.cur; if (!v) return empty('No version yet.');
  const sc = S.detail.scene; const m = sc.manifest; const st = S.stats;
  const parent = S.versions.find((x) => x.version_id === v.parent_version_id);
  return h('div', null, h('h3', null, 'Version'), kv({ Label: `${v.label} (${v.stage})`, Operation: v.operation, Parent: parent ? `${parent.label} · ${parent.operation}` : '— (origin)', Created: fmt.date(v.created_at), Integrity: h('span', { class: 'mono hint' }, v.manifest_sha256.slice(0, 16) + '…'), Production: v.is_production ? '★ current production version' : 'no' }),
    h('h3', { style: { marginTop: '14px' } }, 'Model statistics'), kv({ Vertices: fmt.int(sc.stats.vertices), Triangles: fmt.int(sc.stats.triangles), Parts: sc.stats.parts, Materials: sc.stats.materials, Textures: sc.stats.textures, Colliders: sc.stats.colliders, Dimensions: st ? st.dimensions.map((x) => x.toFixed(2)).join(' × ') + ' m' : '…', 'GLB size': st ? fmt.bytes(st.fileSize) : '…', LODs: Object.entries(sc.stats.lods).map(([k, x]) => `${k} ${fmt.int(x)}`).join(' · ') }),
    h('h3', { style: { marginTop: '14px' } }, 'Provenance'), kv({ Source: fmt.title(m.provenance.source), Engine: m.provenance.engine_id || '—', 'Model version': m.provenance.model_version || '—', 'Input hash': m.provenance.input_image_sha256 ? h('span', { class: 'mono hint' }, m.provenance.input_image_sha256.slice(0, 16) + '…') : '—' }), m.provenance.note ? h('div', { class: 'hint' }, m.provenance.note) : null,
    sc.reports.length ? h('div', { style: { marginTop: '14px' } }, h('h3', null, 'Reports stored with this version'), h('div', { class: 'btn-row' }, ...sc.reports.map((n) => h('button', { class: 'btn sm', onclick: async () => { const rep = await api.get(`/api/versions/${v.version_id}/reports/${n}`); modal(`Report: ${n}`, h('pre', { class: 'log', style: { maxHeight: '60vh' } }, JSON.stringify(rep, null, 2)), [{ label: 'Close' }]); } }, n)))) : null);
}
function versionsTab() {
  if (!S.versions.length) return empty('No versions yet.');
  const byId = Object.fromEntries(S.versions.map((v) => [v.version_id, v]));
  return h('ul', { class: 'timeline' }, ...[...S.versions].reverse().map((v) => {
    const p = byId[v.parent_version_id]; const delta = p ? v.triangle_count - p.triangle_count : null;
    return h('li', { style: { background: v.version_id === S.cur?.version_id ? 'var(--accent-dim)' : '', borderRadius: '6px' } }, h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('b', null, `${v.label} · ${v.operation}`), v.is_production ? h('span', { class: 'chip ok' }, '★ production') : null),
      h('div', { class: 'hint' }, `${v.stage} · ${fmt.int(v.triangle_count)} tris${delta ? ` (${delta > 0 ? '+' : ''}${fmt.int(delta)})` : ''} · ${fmt.ago(v.created_at)}`), v.description ? h('div', { class: 'hint' }, v.description) : null,
      h('div', { class: 'btn-row', style: { marginTop: '4px' } }, h('a', { class: 'btn sm', href: `#/studio/${S.asset.asset_id}/${v.version_id}` }, v.version_id === S.cur?.version_id ? 'Viewing' : 'Open'),
        v.stage !== 'raw' && !v.is_production ? h('button', { class: 'btn sm ghost', onclick: async () => { if (await confirmDialog('Delete version?', `${v.label} (${v.operation}) will be permanently removed. Raw reconstructions and production versions cannot be deleted.`, 'Delete', true)) { try { await api.del(`/api/versions/${v.version_id}`); reloadStudio(''); } catch (e) { errorToast(e); } } } }, icon('trash')) : null));
  }));
}
function validationTab() {
  const v = S.detail?.validation; if (!v) return empty('This version has not been validated. Use the Validate step.');
  return reportView(v);
}
function exportsTab() {
  const ex = S.asset.exports; if (!ex.length) return empty('No exports yet.');
  return h('div', null, ...ex.map((e) => h('div', { class: 'card', style: { marginBottom: '8px', padding: '10px' } }, h('div', { class: 'btn-row', style: { justifyContent: 'space-between' } }, h('b', null, e.format.toUpperCase()), statusChip(e.status)),
    h('div', { class: 'hint' }, `${fmt.bytes(e.size_bytes)} · ${fmt.ago(e.created_at)} · version ${S.versions.find((v) => v.version_id === e.version_id)?.label || ''}`),
    e.report.verification ? h('div', { class: 'hint', style: { color: e.report.verification.ok ? 'var(--ok)' : 'var(--err)' } }, e.report.verification.ok ? `✓ ${e.report.verification.checks.length} integrity checks passed` : '✕ verification failed') : null,
    e.status === 'COMPLETED' ? h('button', { class: 'btn sm', style: { marginTop: '4px' }, onclick: () => api.download(`/api/exports/${e.export_id}/download`, e.path.split('/').pop()).catch(errorToast) }, icon('download'), 'Download') : null)));
}
