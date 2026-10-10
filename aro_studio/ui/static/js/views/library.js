import { api } from '../api.js';
import { empty, fmt, h, nav, select } from '../dom.js';
import { assetCard, taxonomy } from './common.js';

export async function mount(root) {
  const t = await taxonomy();
  const st = { cat: '', group: '', q: '', status: '' };
  const list = h('div', { class: 'cat-list' });
  const grid = h('div', { class: 'grid auto' });
  const q = h('input', { placeholder: 'Search name or metadata…', 'aria-label': 'Search assets', style: { maxWidth: '300px' } });
  const status = select([['', 'Any status'], 'DRAFT', 'GENERATING', 'PROCESSING', 'VALIDATING', 'NEEDS_REVIEW', 'APPROVED', 'PRODUCTION_READY', 'FAILED', 'ARCHIVED'], '', { 'aria-label': 'Status filter', style: { maxWidth: '190px' } });
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Asset Library'), h('p', { class: 'sub' }, 'Organised by category, with structured metadata and status.')), h('div', { class: 'spacer' }), q, status),
    h('div', { style: { display: 'grid', gridTemplateColumns: '230px 1fr', gap: '18px' } }, h('div', { class: 'card', style: { alignSelf: 'start' } }, list), grid));
  let counts = {};
  const drawList = () => {
    list.replaceChildren(h('a', { class: st.cat === '' && st.group === '' ? 'on' : '', onclick: () => { st.cat = st.group = ''; go(); } }, 'All assets', h('span', { class: 'hint' }, fmt.int(Object.values(counts).reduce((a, b) => a + b, 0)))));
    for (const g of t.groups) {
      list.append(h('div', { class: 'grp' }, g.label));
      for (const c of g.categories) list.append(h('a', { class: st.cat === c.id ? 'on' : '', title: c.available ? '' : 'Reserved for a future release', style: c.available ? null : { opacity: 0.45 }, onclick: () => { st.cat = c.id; go(); } }, c.label, h('span', { class: 'hint' }, counts[c.id] ? String(counts[c.id]) : c.available ? '' : 'soon')));
    }
  };
  const go = async () => {
    const all = await api.get('/api/assets'); counts = {}; for (const a of all.items) counts[a.category] = (counts[a.category] || 0) + 1;
    const r = await api.get(`/api/assets?${new URLSearchParams({ ...(st.cat ? { category: st.cat } : {}), ...(st.q ? { q: st.q } : {}), ...(st.status ? { status: st.status } : {}) })}`);
    drawList(); grid.replaceChildren(...(r.items.length ? r.items.map((a) => assetCard(a, t, () => nav(`#/studio/${a.asset_id}`))) : [empty('No assets in this view yet. Create one from a project.')]));
  };
  q.oninput = () => { st.q = q.value; go(); }; status.onchange = () => { st.status = status.value; go(); };
  await go();
}
