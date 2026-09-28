const C = window.NOVA_CONFIG;
const $ = (id) => document.getElementById(id);
const STORAGE_KEY = 'nova_jwt';

function getToken() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (obj.expires_at && Date.now() > obj.expires_at) {
      localStorage.removeItem(STORAGE_KEY); return null;
    }
    return obj.token;
  } catch { return null; }
}
function setToken(token, ttl = 3000) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    token, expires_at: Date.now() + ttl * 1000,
  }));
}
function clearToken() { localStorage.removeItem(STORAGE_KEY); }

function toast(msg, kind = 'ok') {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast show ${kind}`;
  setTimeout(() => el.className = 'toast', 3000);
}
function showResult(data) {
  $('result').textContent =
    typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}
function showDashboard() {
  $('login-card').style.display = 'none';
  $('dashboard').style.display = 'block';
  $('user-info').textContent = '✓ logged in';
}
function showLogin() {
  $('login-card').style.display = 'block';
  $('dashboard').style.display = 'none';
  $('user-info').textContent = '';
}

async function doLogin() {
  const username = $('username').value.trim();
  const password = $('password').value;
  if (!username || !password) { toast('Enter username and password', 'err'); return; }
  const btn = $('login-btn');
  btn.disabled = true; btn.textContent = 'Logging in…';
  try {
    const body = new URLSearchParams({ username, password });
    const r = await fetch(`${C.JARVIS_URL}/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (!data.access_token) throw new Error('No token');
    setToken(data.access_token, 3000);
    toast('Logged in', 'ok');
    showDashboard();
  } catch (e) {
    toast(`Login failed: ${e.message}`, 'err');
  } finally {
    btn.disabled = false; btn.textContent = 'Login';
  }
}

function doLogout() { clearToken(); showLogin(); toast('Logged out'); }

async function authedFetch(path, options = {}) {
  const token = getToken();
  if (!token) { toast('Session expired — log in again', 'err'); showLogin(); throw new Error('no_token'); }
  return fetch(`${C.WORKER_URL}${C.API_BASE}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  });
}

async function actionTicker() {
  const symbol = $('symbol').value.trim().toUpperCase();
  showResult(`Fetching ${symbol}…`);
  try { showResult(await (await authedFetch(`/ticker?symbol=${encodeURIComponent(symbol)}`)).json()); }
  catch (e) { showResult(`Error: ${e.message}`); }
}
async function actionBalance() {
  showResult('Reading vault → Bybit…');
  try { showResult(await (await authedFetch('/balance')).json()); }
  catch (e) { showResult(`Error: ${e.message}`); }
}
async function actionDkhyr() {
  const addr = $('wallet').value.trim();
  if (!addr.startsWith('0x') || addr.length !== 42) { toast('Enter a valid 0x address', 'err'); return; }
  showResult('Reading DKHYR balance…');
  try { showResult(await (await authedFetch(`/dkhyr?address=${encodeURIComponent(addr)}`)).json()); }
  catch (e) { showResult(`Error: ${e.message}`); }
}
async function actionAgent() {
  const prompt = $('prompt').value.trim();
  if (!prompt) { toast('Enter a prompt', 'err'); return; }
  showResult('Jarvis is analyzing…');
  try {
    const r = await authedFetch('/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, payload: {} }),
    });
    showResult(await r.json());
  } catch (e) { showResult(`Error: ${e.message}`); }
}

document.addEventListener('DOMContentLoaded', () => {
  $('login-btn').addEventListener('click', doLogin);
  $('logout-btn').addEventListener('click', doLogout);
  $('get-ticker').addEventListener('click', actionTicker);
  $('get-balance').addEventListener('click', actionBalance);
  $('get-dkhyr').addEventListener('click', actionDkhyr);
  $('run-agent').addEventListener('click', actionAgent);
  $('password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  if (getToken()) showDashboard(); else showLogin();
});
