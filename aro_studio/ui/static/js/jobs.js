// Job tracking: polls the API (cheap read, exempt from rate limiting) and drives the global tray + pills.
import { api } from './api.js';
import { bar, errorToast, fmt, h, statusChip, toast } from './dom.js';

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'RESOURCE_LIMIT', 'MODEL_ERROR', 'INVALID_INPUT']);
export const isTerminal = (s) => TERMINAL.has(s);
const tracked = new Map();

export function trackJob(job, { label, onDone, onUpdate, silent } = {}) {
  const id = job.job_id;
  if (tracked.has(id)) return tracked.get(id).promise;
  const card = h('div', { class: 'job' });
  const state = { card, label: label || `${job.kind}`, promise: null };
  tracked.set(id, state);
  document.getElementById('jobtray').append(card);
  const paint = (j) => {
    card.replaceChildren(
      h('div', { class: 'top' }, h('b', null, state.label), statusChip(j.state)),
      bar(j.progress, j.state === 'COMPLETED' ? 'ok' : isTerminal(j.state) ? 'err' : ''),
      h('div', { class: 'msg', title: j.message }, j.message || ''),
      !isTerminal(j.state) ? h('div', { class: 'btn-row', style: { marginTop: '6px' } }, h('button', { class: 'btn sm', onclick: () => api.post(`/api/jobs/${id}/cancel`).catch(errorToast) }, 'Cancel')) : null,
    );
  };
  state.promise = new Promise((resolve) => {
    const tick = async () => {
      let j;
      try { j = await api.get(`/api/jobs/${id}`); } catch (e) { setTimeout(tick, 2000); return; }
      paint(j); onUpdate?.(j);
      document.dispatchEvent(new CustomEvent('aro:job', { detail: j }));
      if (!isTerminal(j.state)) { setTimeout(tick, 450); return; }
      setTimeout(() => { card.remove(); tracked.delete(id); }, j.state === 'COMPLETED' ? 2500 : 12000);
      if (!silent) {
        if (j.state === 'COMPLETED') toast(`${state.label} finished`, j.message, 'ok');
        else toast(`${state.label}: ${j.state.replace(/_/g, ' ')}`, [j.error?.message, j.error?.recommended_action ? `→ ${j.error.recommended_action}` : ''].filter(Boolean).join('\n'), j.state === 'CANCELLED' ? 'warn' : 'err');
      }
      try { onDone?.(j); } catch (e) { errorToast(e); }
      resolve(j);
    };
    tick();
  });
  return state.promise;
}

export function jobSummary(j) {
  return h('div', null,
    h('div', { class: 'btn-row' }, statusChip(j.state), h('span', { class: 'hint' }, `${j.kind} · ${fmt.ago(j.created_at)}`)),
    j.error ? h('div', { class: 'notice err', style: { marginTop: '8px' } }, h('b', null, j.error.message), j.error.recommended_action ? h('div', null, `→ ${j.error.recommended_action}`) : null) : null);
}

export async function refreshPills() {
  try {
    const [sys, eng] = await Promise.all([api.get('/api/system'), api.get('/api/engines')]);
    const q = sys.queue; const running = q.running || 0; const queued = (q.by_state?.QUEUED || 0);
    const qp = document.getElementById('queue-pill');
    qp.className = `pill ${running || queued ? 'busy' : 'ok'}`; qp.lastChild.textContent = running || queued ? `${running} running · ${queued} queued` : 'idle';
    const e = eng.items[0]; const ep = document.getElementById('engine-pill');
    if (e) { ep.className = `pill ${e.runnable ? 'ok' : 'warn'}`; ep.lastChild.textContent = `${e.info.name}: ${e.runnable ? (e.loaded ? 'loaded' : 'ready') : 'not runnable here'}`; }
    return { sys, eng };
  } catch { return null; }
}
