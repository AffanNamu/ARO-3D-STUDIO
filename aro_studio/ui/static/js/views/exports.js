import { api } from '../api.js';
import { empty, errorToast, fmt, h, icon, statusChip, toast } from '../dom.js';

export async function mount(root) {
  const r = await api.get('/api/exports');
  root.append(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Exports'), h('p', { class: 'sub' }, 'Every export is re-opened and verified after writing. Failed exports are kept with their report.'))));
  if (!r.items.length) return root.append(empty('No exports yet. Open an asset in the 3D Studio → Export step.'));
  root.append(h('div', { class: 'card' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Format'), h('th', null, 'Status'), h('th', null, 'Verification'), h('th', { class: 'num' }, 'Size'), h('th', null, 'SHA-256'), h('th', null, 'Created'), h('th', null, ''))),
    h('tbody', null, ...r.items.map((e) => {
      const ver = e.report.verification; const kh = e.report.khronos;
      return h('tr', null, h('td', null, h('b', null, e.format.toUpperCase())), h('td', null, statusChip(e.status)),
        h('td', null, ver ? h('div', null, h('span', { class: `chip ${ver.ok ? 'ok' : 'err'}` }, ver.ok ? `${ver.checks.length} checks passed` : 'verification failed'), kh ? h('span', { class: `chip ${kh.ran ? (kh.ok ? 'ok' : 'err') : ''}`, style: { marginLeft: '4px' }, title: kh.reason || '' }, kh.ran ? `Khronos: ${kh.errors}E/${kh.warnings}W` : 'Khronos: not run') : null, ver.ok ? null : h('div', { class: 'hint' }, ver.checks.filter((c) => !c.ok).map((c) => c.message).join('; '))) : (e.report.error ? h('span', { class: 'hint' }, e.report.error.message) : '—')),
        h('td', { class: 'num' }, fmt.bytes(e.size_bytes)), h('td', { class: 'mono hint' }, e.sha256 ? e.sha256.slice(0, 12) + '…' : '—'), h('td', { class: 'hint' }, fmt.ago(e.created_at)),
        h('td', null, h('div', { class: 'btn-row' }, e.status === 'COMPLETED' ? h('button', { class: 'btn sm', onclick: () => api.download(`/api/exports/${e.export_id}/download`, e.path.split('/').pop()).catch(errorToast) }, icon('download'), 'Download') : null,
          h('button', { class: 'btn sm ghost', title: 'Delete export', onclick: async () => { try { await api.del(`/api/exports/${e.export_id}`); toast('Export deleted', '', 'ok'); location.reload(); } catch (x) { errorToast(x); } } }, icon('trash')))));
    })))));
}
