// Thin fetch wrapper. The access token (if the deployment sets one) lives in sessionStorage only.
const TOKEN_KEY = 'aro.token';
export const token = {
  get() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } },
  set(v) { try { v ? sessionStorage.setItem(TOKEN_KEY, v) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

export class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || `Request failed (${status})`);
    this.status = status; this.code = e.code || 'ERROR'; this.action = e.recommended_action || null; this.details = e.details || {};
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(method, url, body, opts = {}) {
  const headers = { Accept: 'application/json' };
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(url, { method, headers, body: payload, signal: opts.signal });
  if (opts.raw) { if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null)); return res; }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) onUnauthorized();
    throw new ApiError(res.status, data);
  }
  return data;
}

export const api = {
  get: (u, o) => request('GET', u, undefined, o),
  post: (u, b, o) => request('POST', u, b ?? {}, o),
  patch: (u, b) => request('PATCH', u, b),
  del: (u) => request('DELETE', u),
  upload: (u, file, fields = {}) => { const f = new FormData(); f.append('file', file); for (const [k, v] of Object.entries(fields)) if (v != null) f.append(k, v); return request('POST', u, f); },
  async blob(u) { const r = await request('GET', u, undefined, { raw: true }); return r.blob(); },
  async buffer(u) { const r = await request('GET', u, undefined, { raw: true }); return r.arrayBuffer(); },
  // authenticated download (an <a href> cannot send the Authorization header)
  async download(u, filename) {
    const b = await api.blob(u); const a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  },
};
