(() => {
'use strict';

// ---------- estados (conclusion do run, ou status enquanto não terminou) ----------
const OK = new Set(['success']);
const FAIL = new Set(['failure', 'timed_out', 'startup_failure']);
const WARN = new Set(['action_required']);
const ACTIVE = new Set(['in_progress', 'queued', 'waiting', 'pending', 'requested']);
const PT = {
  success: 'Sucesso', failure: 'Falha', timed_out: 'Timeout', startup_failure: 'Falha ao iniciar',
  cancelled: 'Cancelado', skipped: 'Ignorado', neutral: 'Neutro', stale: 'Obsoleto', action_required: 'Requer ação',
  in_progress: 'Executando', queued: 'Na fila', waiting: 'Aguardando', pending: 'Pendente', requested: 'Solicitado',
};
const GROUPS = {
  ok: { label: 'Sucesso', icon: '✓' },
  fail: { label: 'Falha', icon: '✕' },
  warn: { label: 'Requer ação', icon: '!' },
  active: { label: 'Executando / na fila', icon: '▶' },
  cancel: { label: 'Cancelado / ignorado', icon: '⊘' },
};
const group = s => OK.has(s) ? 'ok' : FAIL.has(s) ? 'fail' : WARN.has(s) ? 'warn' : ACTIVE.has(s) ? 'active' : 'cancel';
const label = s => PT[s] || s;
const HIST = 30;

const state = {
  cfg: null, started: false, runs: [], seq: 0, timer: null,
  sort: { key: null, dir: 1 },
  open: new Set(), onlyFails: new Set(),
  why: new Map(),                 // run id -> resposta de get_failure ('...' enquanto carrega)
  periodKey: null, seenFails: null, newFails: new Set(),
};

const $ = id => document.getElementById('gh-' + id);
const api = () => window.pywebview.api.github;

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
const stateCell = st => `<span class="st">${icon(group(st))}${esc(label(st))}</span>`;
const toggle = (set, v) => set.has(v) ? set.delete(v) : set.add(v);
const wfName = w => `${w.kind} · ${w.env}`;

// ---------- dados ----------
function aggregate(runs) {
  const by = new Map(state.cfg.workflows.map(w => [w.key, []]));
  for (const r of runs) if (by.has(r.wf)) by.get(r.wf).push(r);
  return state.cfg.workflows.map(w => {
    const rs = by.get(w.key);
    rs.sort((a, b) => b.t - a.t);
    const fails = rs.filter(r => FAIL.has(r.state));
    const oks = rs.filter(r => OK.has(r.state)).length;
    const last = rs.find(r => !ACTIVE.has(r.state)) || null;
    const done = rs.filter(r => OK.has(r.state) && r.duration != null);
    return {
      ...w, name: wfName(w), runs: rs, n: rs.length, fails: fails.length,
      active: rs.filter(r => ACTIVE.has(r.state)).length,
      okPct: oks + fails.length ? 100 * oks / (oks + fails.length) : null,
      last, lastFail: fails[0] || null,
      avg: done.length ? done.reduce((s, r) => s + r.duration, 0) / done.length : null,
      alert: !!last && FAIL.has(last.state),
      isNew: fails.some(r => state.newFails.has(r.id)),
    };
  });
}

function applyFilters(rows) {
  const q = $('f-busca').value.trim().toLowerCase();
  const env = $('f-env').value, kind = $('f-kind').value, ult = $('f-ultimo').value;
  const comFalha = $('f-comfalha').checked;
  return rows.filter(d =>
    (!q || `${d.name} ${d.file}`.toLowerCase().includes(q)) &&
    (!env || d.env === env) && (!kind || d.kind === kind) &&
    (!comFalha || d.fails > 0) &&
    (!ult || (ult === 'active' ? d.active > 0 : !!d.last && group(d.last.state) === ult)));
}

const COLS = [
  { key: 'name', label: 'Workflow', val: d => d.name.toLowerCase() },
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
  window.setBadge('gh', aggregate(state.runs).filter(d => d.alert).length);
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
  const active = runs.filter(r => ACTIVE.has(r.state)).length;
  const alerts = rows.filter(d => d.alert).length;
  const tiles = [
    ['Runs', num(runs.length), `${rows.length} workflows`],
    ['Sucesso', pct(oks + fails ? 100 * oks / (oks + fails) : null), `${num(oks)} concluídos`],
    ['Falhas', num(fails), [...FAIL].filter(s => count[s]).map(s => `${count[s]} ${label(s)}`).join(' · ') || 'nenhuma', fails ? 'fail' : null],
    ['Em andamento', num(active), active ? 'rodando ou na fila' : 'nada rodando', active ? 'active' : null],
    ['Último run em falha', num(alerts), alerts ? (alerts === 1 ? 'workflow' : 'workflows') : 'todos ok', alerts ? 'fail' : 'ok'],
  ];
  $('tiles').innerHTML = tiles.map(([k, v, d, g]) =>
    `<div class="tile"><div class="k">${g ? icon(g) : ''}${k}</div><div class="v">${v}</div><div class="d" title="${esc(d)}">${esc(d)}</div></div>`).join('');
}

function histCell(d) {
  return `<div class="hist">${d.runs.slice(0, HIST).reverse().map(r =>
    `<a class="${group(r.state)}" href="${esc(r.url)}" target="_blank" aria-label="${esc(label(r.state))}"
        data-tip="${esc(`${dt(r.when)} · ${label(r.state)} · ${dur(r.duration)}\n${r.title}\n${r.branch} @ ${r.sha}`)}"><i></i></a>`).join('')}</div>`;
}

function renderTable(rows) {
  if (!rows.length) {
    $('tbody').innerHTML = `<tr><td colspan="${COLS.length}" class="empty">Nenhum workflow com esses filtros.</td></tr>`;
    return;
  }
  $('tbody').innerHTML = rows.map(d => {
    const open = state.open.has(d.key);
    const tags = (d.isNew ? `<span class="tag">${icon('fail')}falha nova</span>` : '') +
      (d.active ? `<span class="tag">${icon('active')}${d.active} em andamento</span>` : '');
    const row = `<tr class="row${open ? ' open' : ''}" data-key="${esc(d.key)}">
      <td class="name" data-tip="${esc(`${d.file}\n${d.note}`)}"><span class="caret">${open ? '▾' : '▸'}</span>${icon(d.alert ? 'fail' : null)}${esc(d.name)}${tags}</td>
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

function whyRows(r, cols) {
  const w = state.why.get(r.id);
  if (!w) return '';
  let body;
  if (w === '...') body = '<span class="muted">Buscando detalhes…</span>';
  else if (w.error) body = `${icon('warn')} ${esc(w.error)}`;
  else {
    const steps = w.jobs.length
      ? w.jobs.map(j => `<a class="lnk" href="${esc(j.url)}" target="_blank">${esc(j.name)}</a>${j.steps.length ? ' › ' + j.steps.map(esc).join(', ') : ''}`).join('<br>')
      : '<span class="muted">Nenhum job com falha (run cancelado ou falha fora dos jobs).</span>';
    body = `<div class="steps">${steps}</div>${w.log ? `<pre>${esc(w.log)}</pre>` : ''}`;
  }
  return `<tr class="why"><td colspan="${cols}"><div class="why-box">${body}</div></td></tr>`;
}

function detailRow(d) {
  const only = state.onlyFails.has(d.key);
  const rs = only ? d.runs.filter(r => FAIL.has(r.state)) : d.runs;
  const cols = 9;
  return `<tr class="detail"><td colspan="${COLS.length}"><div class="detail-wrap">
    <div class="detail-head">
      <span class="muted">${num(rs.length)} de ${num(d.n)} runs · ${esc(d.note)}</span>
      <button class="chip${only ? ' on' : ''}" data-only="${esc(d.key)}">Só falhas</button>
    </div>
    <table class="runs">
      <thead><tr><th>Início</th><th>Estado</th><th class="num">Duração</th><th>Commit / PR</th><th>Branch</th><th>Quem</th><th>Evento</th><th></th><th></th></tr></thead>
      <tbody>${rs.map(r => `<tr>
        <td>${dt(r.when)}</td>
        <td>${stateCell(r.state)}${r.attempt > 1 ? ` <span class="muted">(tentativa ${r.attempt})</span>` : ''}</td>
        <td class="num">${dur(r.duration)}</td>
        <td><div class="title" data-tip="${esc(r.title)}">${esc(r.title)}</div></td>
        <td class="muted">${esc(r.branch)} @ ${esc(r.sha)}</td>
        <td>${esc(r.actor)}</td>
        <td class="muted">${esc(r.event)}</td>
        <td>${FAIL.has(r.state) ? `<button class="btn-s" data-why="${r.id}">${state.why.has(r.id) ? 'ocultar' : 'por quê?'}</button>` : ''}</td>
        <td><a class="lnk" href="${esc(r.url)}" target="_blank">abrir ↗</a></td>
      </tr>${whyRows(r, cols)}`).join('')}</tbody>
    </table>
  </div></td></tr>`;
}

function renderNews() {
  const box = $('news');
  if (!state.newFails.size) { box.hidden = true; return; }
  const wfs = [...new Set(state.runs.filter(r => state.newFails.has(r.id)).map(r => {
    const w = state.cfg.workflows.find(x => x.key === r.wf);
    return w ? wfName(w) : r.wf;
  }))];
  box.innerHTML = `${icon('fail')}<span class="grow">${state.newFails.size} falha(s) nova(s) desde que o monitor abriu: ${wfs.map(esc).join(', ')}</span>
    <button class="btn" id="news-ok">Dispensar</button>`;
  box.hidden = false;
}

function renderLegend() {
  $('legend').innerHTML = Object.entries(GROUPS).map(([g, x]) => `<span><i class="sw ${g}"></i>${x.label}</span>`).join('');
}

async function loadWhy(id) {
  if (state.why.has(id)) { state.why.delete(id); render(); return; }
  state.why.set(id, '...');
  render();
  let res;
  try { res = await api().get_failure(id); } catch (e) { res = { error: String(e) }; }
  state.why.set(id, res);
  render();
}

// ---------- carga ----------
async function load() {
  const seq = ++state.seq;
  const days = $('f-dias').value;
  $('btn-refresh').disabled = true;
  $('status-text').textContent = 'Buscando…';
  let res;
  try {
    res = await api().get_runs(days);
  } catch (e) {
    res = { error: String(e) };
  }
  if (seq !== state.seq) return;
  $('btn-refresh').disabled = false;

  if (res.error) {
    $('error').innerHTML = `${icon('warn')}<span class="grow">${esc(res.error)}</span>`;
    $('error').hidden = false;
    $('status-text').textContent = 'Falhou a última atualização';
    return;
  }
  if (res.truncated.length) {
    $('error').innerHTML = `${icon('warn')}<span class="grow">Período grande: ${res.truncated.length} workflow(s) com mais runs do que o limite lido (${res.truncated.join(', ')}). Reduza o período para ver tudo.</span>`;
    $('error').hidden = false;
  } else {
    $('error').hidden = true;
  }

  state.runs = res.runs.map(r => ({ ...r, t: Date.parse(r.when) }));
  if (days !== state.periodKey) { state.periodKey = days; state.seenFails = null; state.newFails.clear(); }
  const failIds = new Set(state.runs.filter(r => FAIL.has(r.state)).map(r => r.id));
  if (state.seenFails) for (const id of failIds) if (!state.seenFails.has(id)) state.newFails.add(id);
  state.seenFails = failIds;

  const auto = Number($('f-auto').value);
  $('status-text').textContent = `Atualizado ${fmtT.format(new Date(res.fetched_at))} · ${num(state.runs.length)} runs${auto ? ` · auto ${auto} min` : ''}`;
  render();
}

function schedule() {
  clearInterval(state.timer);
  const min = Number($('f-auto').value);
  if (min) state.timer = setInterval(load, min * 60000);
}

// ---------- eventos ----------
function bind() {
  $('btn-refresh').addEventListener('click', load);
  $('f-dias').addEventListener('change', load);
  $('f-busca').addEventListener('input', render);
  for (const id of ['f-env', 'f-kind', 'f-ultimo', 'f-comfalha']) $(id).addEventListener('change', render);
  $('f-auto').addEventListener('change', () => { schedule(); load(); });

  $('thead').addEventListener('click', e => {
    const th = e.target.closest('th.sortable');
    if (!th) return;
    const key = th.dataset.key, first = key === 'name' ? 1 : -1;
    if (state.sort.key !== key) state.sort = { key, dir: first };
    else if (state.sort.dir === first) state.sort.dir = -first;
    else state.sort = { key: null, dir: 1 };
    render();
  });

  $('tbody').addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const why = e.target.closest('[data-why]');
    if (why) { loadWhy(Number(why.dataset.why)); return; }
    const only = e.target.closest('[data-only]');
    if (only) { toggle(state.onlyFails, only.dataset.only); render(); return; }
    if (e.target.closest('tr.detail')) return;
    const tr = e.target.closest('tr.row');
    if (tr) { toggle(state.open, tr.dataset.key); render(); }
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
  $('sub').innerHTML = `GitHub Actions · <a class="lnk" href="${esc(state.cfg.repo_url)}/actions" target="_blank">${esc(state.cfg.repo)}</a>`;
  const kinds = [...new Set(state.cfg.workflows.map(w => w.kind))];
  $('f-kind').innerHTML = '<option value="">Todos</option>' + kinds.map(k => `<option>${esc(k)}</option>`).join('');
  renderLegend();
  bind();
  schedule();
  load();
}

window.Monitors = window.Monitors || {};
window.Monitors.github = { init };
})();
