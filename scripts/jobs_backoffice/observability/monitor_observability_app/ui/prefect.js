(() => {
'use strict';

// ---------- estados ----------
const OK = new Set(['Completed', 'Cached']);
const FAIL = new Set(['Failed', 'Crashed', 'TimedOut']);
const WARN = new Set(['Late', 'AwaitingRetry', 'Retrying', 'AwaitingConcurrencySlot']);
const CANCEL = new Set(['Cancelled', 'Cancelling', 'Paused', 'Suspended']);
const FINISHED = new Set([...OK, ...FAIL, 'Cancelled']);
const GROUPS = {
  ok: { label: 'Sucesso', icon: '✓' },
  fail: { label: 'Falha', icon: '✕' },
  warn: { label: 'Atraso / retry', icon: '!' },
  active: { label: 'Executando', icon: '▶' },
  cancel: { label: 'Cancelado / pausado', icon: '⊘' },
};
const group = s => OK.has(s) ? 'ok' : FAIL.has(s) ? 'fail' : WARN.has(s) ? 'warn' : CANCEL.has(s) ? 'cancel' : 'active';
const HIST = 30; // barras no histórico de cada deployment
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

const state = {
  cfg: null, started: false, runs: [], seq: 0, timer: null,
  sort: { key: null, dir: 1 },   // key null = padrão: último run em falha primeiro, depois nome
  open: new Set(), onlyFails: new Set(),
  periodKey: null, seenFails: null, newFails: new Set(),
};

const $ = id => document.getElementById('pf-' + id);
const api = () => window.pywebview.api.prefect;

// ---------- formatação ----------
const TZ = 'America/Sao_Paulo';
const fmtDT = new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const fmtT = new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit' });
const dt = iso => iso ? fmtDT.format(new Date(iso)).replace(',', '') : '–';
const num = n => n.toLocaleString('pt-BR');
const pct = v => v == null ? '–' : `${v.toFixed(1).replace('.', ',')}%`;
const dur = s => {
  if (s == null) return '–';
  s = Math.round(s);
  return `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = g => `<span class="ic ${g}" aria-hidden="true">${g ? GROUPS[g].icon : ''}</span>`;
const stateCell = st => `<span class="st">${icon(group(st))}${esc(st)}</span>`;
const runUrl = id => `${state.cfg.ui_url}/runs/flow-run/${id}`;
const monthStr = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const monthLabel = m => `${MESES[Number(m.slice(5)) - 1]}/${m.slice(2, 4)}`;
const toggle = (set, v) => set.has(v) ? set.delete(v) : set.add(v);

// ---------- dados ----------
function aggregate(runs) {
  const by = new Map();
  for (const r of runs) {
    if (!by.has(r.deployment)) by.set(r.deployment, []);
    by.get(r.deployment).push(r);
  }
  return [...by].map(([name, rs]) => {
    rs.sort((a, b) => b.t - a.t);
    const fails = rs.filter(r => FAIL.has(r.state));
    const oks = rs.filter(r => OK.has(r.state)).length;
    const last = rs.find(r => FINISHED.has(r.state)) || null;
    const completed = rs.filter(r => r.state === 'Completed' && r.duration != null);
    return {
      name, runs: rs, n: rs.length, fails: fails.length,
      active: rs.filter(r => !FINISHED.has(r.state)).length,
      okPct: oks + fails.length ? 100 * oks / (oks + fails.length) : null,
      last, lastFail: fails[0] || null,
      avg: completed.length ? completed.reduce((s, r) => s + r.duration, 0) / completed.length : null,
      alert: !!last && FAIL.has(last.state),
      isNew: fails.some(r => state.newFails.has(r.id)),
    };
  });
}

function applyFilters(rows) {
  const q = $('f-busca').value.trim().toLowerCase();
  const ult = $('f-ultimo').value;
  const comFalha = $('f-comfalha').checked;
  return rows.filter(d =>
    (!q || d.name.toLowerCase().includes(q)) &&
    (!comFalha || d.fails > 0) &&
    (!ult || (ult === 'active' ? d.active > 0 : !!d.last && group(d.last.state) === ult)));
}

const COLS = [
  { key: 'name', label: 'Deployment', val: d => d.name.toLowerCase() },
  { key: 'hist', label: `Últimos ${HIST} runs` },
  { key: 'n', label: 'Runs', num: true, val: d => d.n },
  { key: 'fails', label: 'Falhas', num: true, val: d => d.fails },
  { key: 'okPct', label: 'Sucesso', num: true, val: d => d.okPct ?? -1 },
  { key: 'last', label: 'Último run', val: d => d.last ? d.last.t : 0 },
  { key: 'lastFail', label: 'Últ. falha', val: d => d.lastFail ? d.lastFail.t : 0 },
  { key: 'avg', label: 'Dur. média', num: true, val: d => d.avg ?? -1 },
];

function sortRows(rows) {
  const col = COLS.find(c => c.key === state.sort.key);
  return rows.sort((a, b) => {
    if (col) {
      const x = col.val(a), y = col.val(b);
      if (x !== y) return (x < y ? -1 : 1) * state.sort.dir;
    } else if (a.alert !== b.alert) {
      return a.alert ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
}

// ---------- render ----------
function render() {
  const rows = sortRows(applyFilters(aggregate(state.runs)));
  renderHead();
  renderTiles(rows);
  renderTable(rows);
  renderNews();
  window.setBadge('pf', aggregate(state.runs).filter(d => d.alert).length);
  $('count').textContent = rows.length;
}

function renderHead() {
  $('thead').innerHTML = COLS.map(c => {
    const on = state.sort.key === c.key;
    const cls = [c.num && 'num', c.val && 'sortable', on && 'sorted'].filter(Boolean).join(' ');
    const aria = on ? ` aria-sort="${state.sort.dir > 0 ? 'ascending' : 'descending'}"` : '';
    return `<th class="${cls}" data-key="${c.key}"${aria}>${c.label}${on ? (state.sort.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`;
  }).join('');
}

function renderTiles(rows) {
  const runs = rows.flatMap(d => d.runs);
  const count = {};
  for (const r of runs) count[r.state] = (count[r.state] || 0) + 1;
  const fails = runs.filter(r => FAIL.has(r.state)).length;
  const oks = runs.filter(r => OK.has(r.state)).length;
  const active = runs.filter(r => !FINISHED.has(r.state)).length;
  const alerts = rows.filter(d => d.alert).length;
  const tiles = [
    ['Runs', num(runs.length), `${rows.length} deployments`],
    ['Sucesso', pct(oks + fails ? 100 * oks / (oks + fails) : null), `${num(oks)} concluídos`],
    ['Falhas', num(fails), [...FAIL].filter(s => count[s]).map(s => `${count[s]} ${s}`).join(' · ') || 'nenhuma', fails ? 'fail' : null],
    ['Em andamento', num(active), active ? 'rodando ou na fila' : 'nada rodando', active ? 'active' : null],
    ['Último run em falha', num(alerts), alerts ? (alerts === 1 ? 'deployment' : 'deployments') : 'todos ok', alerts ? 'fail' : 'ok'],
  ];
  $('tiles').innerHTML = tiles.map(([k, v, d, g]) =>
    `<div class="tile"><div class="k">${g ? icon(g) : ''}${k}</div><div class="v">${v}</div><div class="d" title="${esc(d)}">${esc(d)}</div></div>`).join('');
}

function histCell(d) {
  return `<div class="hist">${d.runs.slice(0, HIST).reverse().map(r =>
    `<a class="${group(r.state)}" href="${runUrl(r.id)}" target="_blank" aria-label="${esc(r.state)}"
        data-tip="${esc(`${dt(r.when)} · ${r.state} · ${dur(r.duration)}\n${r.name}`)}"><i></i></a>`).join('')}</div>`;
}

function renderTable(rows) {
  if (!rows.length) {
    $('tbody').innerHTML = `<tr><td colspan="${COLS.length}" class="empty">${state.runs.length ? 'Nenhum deployment com esses filtros.' : 'Sem runs no período.'}</td></tr>`;
    return;
  }
  $('tbody').innerHTML = rows.map(d => {
    const open = state.open.has(d.name);
    const tags = (d.isNew ? `<span class="tag">${icon('fail')}falha nova</span>` : '') +
      (d.active ? `<span class="tag">${icon('active')}${d.active} em andamento</span>` : '');
    const row = `<tr class="row${open ? ' open' : ''}" data-name="${esc(d.name)}">
      <td class="name"><span class="caret">${open ? '▾' : '▸'}</span>${icon(d.alert ? 'fail' : null)}${esc(d.name)}${tags}</td>
      <td>${histCell(d)}</td>
      <td class="num">${num(d.n)}</td>
      <td class="num">${num(d.fails)}</td>
      <td class="num">${pct(d.okPct)}</td>
      <td>${d.last ? `${stateCell(d.last.state)} <span class="muted">${dt(d.last.when)}</span>` : '–'}</td>
      <td>${d.lastFail ? dt(d.lastFail.when) : '–'}</td>
      <td class="num">${dur(d.avg)}</td>
    </tr>`;
    return open ? row + detailRow(d) : row;
  }).join('');
}

function detailRow(d) {
  const only = state.onlyFails.has(d.name);
  const rs = only ? d.runs.filter(r => FAIL.has(r.state)) : d.runs;
  return `<tr class="detail"><td colspan="${COLS.length}"><div class="detail-wrap">
    <div class="detail-head">
      <span class="muted">${num(rs.length)} de ${num(d.n)} runs</span>
      <button class="chip${only ? ' on' : ''}" data-only="${esc(d.name)}">Só falhas</button>
    </div>
    <table class="runs">
      <thead><tr><th>Início</th><th>Estado</th><th class="num">Duração</th><th>Run</th><th>Mensagem</th><th></th></tr></thead>
      <tbody>${rs.map(r => `<tr>
        <td>${dt(r.when)}</td>
        <td>${stateCell(r.state)}</td>
        <td class="num">${dur(r.duration)}</td>
        <td class="muted">${esc(r.name)}</td>
        <td><div class="msg"${r.message ? ` data-tip="${esc(r.message)}"` : ''}>${esc(r.message || '')}</div></td>
        <td><a class="lnk" href="${runUrl(r.id)}" target="_blank">abrir ↗</a></td>
      </tr>`).join('')}</tbody>
    </table>
  </div></td></tr>`;
}

function renderNews() {
  const box = $('news');
  if (!state.newFails.size) { box.hidden = true; return; }
  const deps = [...new Set(state.runs.filter(r => state.newFails.has(r.id)).map(r => r.deployment))];
  box.innerHTML = `${icon('fail')}<span class="grow">${state.newFails.size} falha(s) nova(s) desde que o monitor abriu: ${deps.map(esc).join(', ')}</span>
    <button class="btn" id="news-ok">Dispensar</button>`;
  box.hidden = false;
}

function renderLegend() {
  $('legend').innerHTML = Object.entries(GROUPS).map(([g, x]) => `<span><i class="sw ${g}"></i>${x.label}</span>`).join('');
}

function renderQuick() {
  const de = $('f-de').value, ate = $('f-ate').value, now = new Date();
  const passado = monthStr(new Date(now.getFullYear(), now.getMonth() - 1, 1));
  const match = { este: [monthStr(now), monthStr(now)], passado: [passado, passado], tudo: [state.cfg.start_month, monthStr(now)] };
  document.querySelectorAll('#view-pf [data-quick]').forEach(b => {
    const [a, z] = match[b.dataset.quick];
    b.classList.toggle('on', a === de && z === ate);
  });
  return match;
}

// ---------- carga ----------
async function load() {
  const seq = ++state.seq;
  const de = $('f-de').value, ate = $('f-ate').value;
  if (!de || !ate) return;
  $('btn-refresh').disabled = true;
  $('status-text').textContent = 'Buscando…';
  let res;
  try {
    res = await api().get_runs(de, ate);
  } catch (e) {
    res = { error: String(e) };
  }
  if (seq !== state.seq) return; // chegou resposta mais nova no meio do caminho
  $('btn-refresh').disabled = false;

  if (res.error) {
    $('error').innerHTML = `${icon('warn')}<span class="grow">${esc(res.error)}</span>`;
    $('error').hidden = false;
    $('status-text').textContent = 'Falhou a última atualização';
    return;
  }
  $('error').hidden = true;

  state.runs = res.runs.map(r => ({ ...r, t: Date.parse(r.when) }));
  const key = `${de}|${ate}`;
  if (key !== state.periodKey) { state.periodKey = key; state.seenFails = null; state.newFails.clear(); }
  const failIds = new Set(state.runs.filter(r => FAIL.has(r.state)).map(r => r.id));
  if (state.seenFails) for (const id of failIds) if (!state.seenFails.has(id)) state.newFails.add(id);
  state.seenFails = failIds;

  const auto = Number($('f-auto').value);
  $('status-text').textContent = `Atualizado ${fmtT.format(new Date(res.fetched_at))} · ${num(state.runs.length)} runs${auto ? ` · auto ${auto} min` : ''}`;
  render();
}

let debounce;
function periodChanged() {
  renderQuick();
  clearTimeout(debounce);
  debounce = setTimeout(load, 300);
}

function schedule() {
  clearInterval(state.timer);
  const min = Number($('f-auto').value);
  if (min) state.timer = setInterval(load, min * 60000);
}

// ---------- eventos ----------
function bind() {
  $('btn-refresh').addEventListener('click', load);
  $('f-de').addEventListener('change', periodChanged);
  $('f-ate').addEventListener('change', periodChanged);
  document.querySelectorAll('#view-pf [data-quick]').forEach(b => b.addEventListener('click', () => {
    const [de, ate] = renderQuick()[b.dataset.quick];
    $('f-de').value = de;
    $('f-ate').value = ate;
    periodChanged();
  }));
  $('f-busca').addEventListener('input', render);
  $('f-ultimo').addEventListener('change', render);
  $('f-comfalha').addEventListener('change', render);
  $('f-auto').addEventListener('change', () => { schedule(); load(); });

  $('thead').addEventListener('click', e => {
    const th = e.target.closest('th.sortable');
    if (!th) return;
    const key = th.dataset.key, first = key === 'name' ? 1 : -1;
    if (state.sort.key !== key) state.sort = { key, dir: first };      // 1º clique
    else if (state.sort.dir === first) state.sort.dir = -first;         // 2º inverte
    else state.sort = { key: null, dir: 1 };                            // 3º volta ao padrão
    render();
  });

  $('tbody').addEventListener('click', e => {
    if (e.target.closest('a')) return; // barra do histórico / "abrir" vão pro navegador
    const only = e.target.closest('[data-only]');
    if (only) { toggle(state.onlyFails, only.dataset.only); render(); return; }
    const tr = e.target.closest('tr.row');
    if (tr) { toggle(state.open, tr.dataset.name); render(); }
  });

  $('news').addEventListener('click', e => {
    if (e.target.id === 'news-ok') { state.newFails.clear(); render(); }
  });

}

// ---------- init ----------
async function init() {
  if (state.started) return;
  state.started = true;
  state.cfg = await api().config();
  $('sub').textContent = `tags ${state.cfg.tags.join(' + ')} · prefect3.srna.co`;
  $('quick-tudo').textContent = `Desde ${monthLabel(state.cfg.start_month)}`;
  $('f-de').value = state.cfg.start_month;
  $('f-ate').value = monthStr(new Date());
  renderLegend();
  renderQuick();
  bind();
  schedule();
  load();
}

window.Monitors = window.Monitors || {};
window.Monitors.prefect = { init };
})();
