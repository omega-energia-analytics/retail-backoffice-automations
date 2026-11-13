(() => {
'use strict';

// Aba KPIs CUSD. Os dados vêm inteiros de uma chamada (todos os meses); trocar de mês é só
// re-render. A regra de negócio fica em kpis.py — aqui é só exibição.

const { monthStr: mesStr, monthLabel: mesLabel } = window.MonthPicker;
const ORIGEM = {
  automacao: { label: 'Automação', g: 'ok', icon: '✓' },
  ajustada: { label: 'Ajustada', g: 'warn', icon: '!' },
  manual: { label: 'Manual', g: 'fail', icon: '✕' },
};
const STATUS = {
  atrasada: { label: 'Paga com atraso', g: 'warn', icon: '!' },
  vencida: { label: 'Vencida sem pagamento', g: 'fail', icon: '✕' },
  paga_sem_data: { label: 'Paga (sem data no Oracle)', g: 'cancel', icon: '?' },
  sem_vencimento: { label: 'Sem vencimento no FattureWeb', g: 'cancel', icon: '?' },
  substituida: { label: 'Substituída (refaturamento)', g: 'cancel', icon: '⊘' },
  cancelada: { label: 'NFF cancelada no Oracle', g: 'cancel', icon: '⊘' },
};

const state = { started: false, data: null, mes: null, seq: 0, picker: null };
const $ = id => document.getElementById('kp-' + id);
const api = () => window.pywebview.api.kpis;

// ---------- formatação ----------
const fmtT = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit', second: '2-digit' });
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const brl = v => v == null ? '–' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const mi = v => v == null ? '–' : `R$ ${(v / 1e6).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mi`;
const pct = v => v == null ? '–' : `${v.toFixed(1).replace('.', ',')}%`;
const data = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '–';
const tag = (txt, tip) => `<span class="tag"${tip ? ` data-tip="${esc(tip)}"` : ''}>${esc(txt)}</span>`;
const st = s => `<span class="st"><span class="ic ${s.g}" aria-hidden="true">${s.icon}</span>${esc(s.label)}</span>`;
const sinal = (v, casas = 0) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v).toFixed(casas).replace('.', ',')}`;

function metaChip(ok, txt) {
  return `<span class="st"><span class="ic ${ok ? 'ok' : 'fail'}" aria-hidden="true">${ok ? '✓' : '✕'}</span>${esc(txt)}</span>`;
}

function mesAnterior(m) {
  const i = state.data.meses.indexOf(m);
  return i > 0 ? state.data.meses[i - 1] : null;
}

// ---------- cards ----------
function renderCard1() {
  const d = state.data, m = state.mes, meta = d.metas.kpi1_pct;
  const k = d.kpi1.por_mes[m];
  const el = $('card1');
  const titulo = '<div class="k">KPI 1 · % do valor das NFFs CUSD lançadas pela automação</div>';

  if (!d.logs) {
    el.innerHTML = `${titulo}<div class="v na">indisponível</div><div class="det">Os logs do quickinvoices não puderam ser lidos (ver aviso acima).</div>`;
    return;
  }
  if (!k || k.sem_log) {
    const desde = d.logs.inicio ? ` O log existe desde ${data(d.logs.inicio)}.` : ' Nenhum run com log ainda.';
    el.innerHTML = `${titulo}<div class="v na">sem log</div><div class="det">Antes do log não há como saber quem lançou cada NFF.${desde}</div>`;
    return;
  }
  if (k.pct == null) {
    el.innerHTML = `${titulo}<div class="v na">sem NFFs</div><div class="det">Nenhuma NFF CUSD com data neste mês${k.parcial ? ' (desde o início do log)' : ''}.</div>`;
    return;
  }

  const ant = mesAnterior(m), ka = ant && d.kpi1.por_mes[ant];
  const delta = ka && !ka.sem_log && ka.pct != null
    ? `vs ${mesLabel(ant)}: ${sinal(k.pct - ka.pct, 1)} p.p.` : `vs mês anterior: sem base`;
  el.innerHTML = `${titulo}
    <div class="v">${pct(k.pct)}</div>
    <div class="meta">${metaChip(k.pct >= meta, `meta ≥ ${meta}%`)}<span>${esc(delta)}</span>
      ${k.parcial ? tag('mês parcial', `Só NFFs com data a partir de ${data(d.logs.inicio)}, início do log`) : ''}</div>
    <div class="det">${k.n_automacao} da automação (${mi(k.valor_automacao)}) · ${k.n_ajustada} ajustadas (${mi(k.valor_ajustada)}) · ${k.n_manual} manuais (${mi(k.valor_manual)}) · total ${mi(k.valor_total)}</div>`;
}

function renderCard2() {
  const d = state.data, m = state.mes, meta = d.metas.kpi2_max;
  const k = d.kpi2.por_mes[m];
  const ant = mesAnterior(m), ka = ant && d.kpi2.por_mes[ant];
  const delta = ka ? `vs ${mesLabel(ant)}: ${sinal(k.kpi - ka.kpi)}` : 'vs mês anterior: sem base';
  const aberto = m >= mesStr(new Date()) && k.n_a_vencer > 0;
  $('card2').innerHTML = `
    <div class="k">KPI 2 · faturas CUSD não pagas no prazo (mês do vencimento)</div>
    <div class="v">${k.kpi}</div>
    <div class="meta">${metaChip(k.kpi <= meta, `meta ≤ ${meta}`)}<span>${esc(delta)}</span>
      ${aberto ? tag('mês em aberto', `${k.n_a_vencer} fatura(s) ainda a vencer — o número pode subir`) : ''}</div>
    <div class="det">${k.n_atrasada} pagas com atraso · ${k.n_vencida} vencidas sem pagamento · ${k.n_a_vencer} a vencer · ${k.n_no_prazo} no prazo
      ${k.n_paga_sem_data ? ` · ${k.n_paga_sem_data} pagas sem data` : ''} · ${k.n_total} faturas · fora do prazo ${brl(k.valor_fora)}</div>
    ${k.kpi ? `<div class="det">Causas: ${k.n_nff_tardia} com NFF lançada após o vencimento · ${k.n_sem_nff} sem NFF no Oracle${k.n_data_aproximada ? ` · ${k.n_data_aproximada} com data de pagamento aproximada` : ''}</div>` : ''}
    ${k.n_sem_vencimento ? `<div class="det">${k.n_sem_vencimento} fatura(s) chegaram neste mês sem vencimento no FattureWeb e ficaram fora da conta (ver lista).</div>` : ''}
    ${k.n_substituida || k.n_cancelada ? `<div class="det">Fora da conta: ${k.n_substituida} substituída(s) por refaturamento · ${k.n_cancelada} com NFF cancelada no Oracle (mesma regra do monitor de NFF).</div>` : ''}`;
}

// ---------- tabelas ----------
function renderMeses() {
  const d = state.data;
  const linhas = [...d.meses].reverse().map(m => {
    const a = d.kpi1.por_mes[m], b = d.kpi2.por_mes[m];
    const k1 = !d.logs ? '–' : a.sem_log ? '<span class="muted">sem log</span>' : `${pct(a.pct)}${a.parcial ? ' <span class="muted">*</span>' : ''}`;
    const nffs = !d.logs || a.sem_log ? '–' : `${a.n_automacao} · ${a.n_ajustada} · ${a.n_manual}`;
    const ok2 = b.kpi <= d.metas.kpi2_max;
    return `<tr class="row${m === state.mes ? ' sel' : ''}" data-mes="${m}">
      <td class="name">${mesLabel(m)}</td>
      <td class="num">${k1}</td>
      <td class="num">${nffs}</td>
      <td class="num"><span class="st"><span class="ic ${ok2 ? 'ok' : 'fail'}" aria-hidden="true">${ok2 ? '✓' : '✕'}</span>${b.kpi}</span></td>
      <td class="num">${b.n_atrasada}</td>
      <td class="num">${b.n_vencida}</td>
      <td class="num">${b.n_a_vencer}</td>
      <td class="num">${b.n_no_prazo}</td>
    </tr>`;
  });
  $('meses').innerHTML = linhas.join('');
}

function renderLista1() {
  const d = state.data, k = d.kpi1.por_mes[state.mes];
  const rows = d.kpi1.linhas.filter(r => r.mes === state.mes && r.origem !== 'automacao');
  $('count1').textContent = d.logs && k && !k.sem_log ? rows.length : '';
  let html;
  if (!d.logs) html = '<tr><td colspan="8" class="empty">Logs indisponíveis.</td></tr>';
  else if (!k || k.sem_log) html = '<tr><td colspan="8" class="empty">Mês sem log do quickinvoices.</td></tr>';
  else if (!rows.length) html = '<tr><td colspan="8" class="empty">Todas as NFFs do mês vieram da automação, sem ajuste.</td></tr>';
  else html = rows.map(r => `<tr>
      <td class="name">${esc(r.usina || '–')}</td><td>${esc(r.nff)}</td><td>${esc(r.distribuidora || '–')}</td>
      <td>${data(r.data_nff)}</td><td class="num">${brl(r.valor_oracle)}</td><td class="num">${brl(r.valor_log)}</td>
      <td>${st(ORIGEM[r.origem])}</td><td>${esc(r.usuario_log || '–')}</td></tr>`).join('');
  $('lista1').innerHTML = html;
}

function renderLista2() {
  const rows = state.data.kpi2.linhas.filter(r => r.mes === state.mes);
  const fora = rows.filter(r => r.status === 'atrasada' || r.status === 'vencida').length;
  $('count2').textContent = rows.length ? `${fora}${rows.length > fora ? ` + ${rows.length - fora} a conferir` : ''}` : '';
  if (!rows.length) {
    $('lista2').innerHTML = '<tr><td colspan="8" class="empty">Nenhuma fatura fora do prazo neste mês.</td></tr>';
    return;
  }
  $('lista2').innerHTML = rows.map(r => {
    const flags = [
      r.sem_nff ? tag('sem NFF no Oracle', 'A fatura existe no FattureWeb, mas nenhuma NFF válida foi lançada') : '',
      r.nff_tardia ? tag('NFF após o vencimento', `NFF lançada em ${data(r.data_nff)}, depois do prazo da distribuidora — não havia como pagar em dia`) : '',
      r.data_aproximada ? tag('data aproximada', 'Pagamento pela parcela do Oracle: a data é a da atualização do status, não a de caixa (mesma regra do monitor de NFF)') : '',
    ].join('');
    const venc = r.status === 'sem_vencimento' || !r.vencimento_fw
      ? `<span class="muted" data-tip="Chegou em ${data(r.data_chegada)}">–</span>`
      : `${data(r.vencimento_fw)}${r.prazo && r.prazo !== r.vencimento_fw ? ` <span class="muted" data-tip="Vencimento no fim de semana: prazo até ${data(r.prazo)}">→ ${data(r.prazo)}</span>` : ''}`;
    return `<tr>
      <td class="name">${esc(r.usina || '–')}</td><td>${esc(r.nff || '–')}</td><td>${esc(r.distribuidora || '–')}</td>
      <td>${venc}</td><td>${data(r.data_pagamento)}</td>
      <td class="num">${r.dias_atraso ?? '–'}</td><td class="num">${brl(r.valor)}</td>
      <td>${st(STATUS[r.status])}${flags}</td></tr>`;
  }).join('');
}

function renderFoot() {
  const d = state.data;
  const log = !d.logs ? 'logs indisponíveis'
    : d.logs.qtd_runs ? `${d.logs.qtd_runs} run(s) do quickinvoices com log desde ${data(d.logs.inicio)}, ${d.logs.qtd_nffs} NFFs distintas`
    : 'nenhum run do quickinvoices com log ainda';
  $('foot').textContent = `Log: ${log}. KPI 1 pela data da NFF no Oracle; KPI 2 pelo mês do vencimento. * mês parcial (início do log).`;
}

function render() {
  if (!state.data) return;
  renderCard1();
  renderCard2();
  renderMeses();
  renderLista1();
  renderLista2();
  renderFoot();
}

async function load(force) {
  const seq = ++state.seq;
  $('btn-refresh').disabled = true;
  $('status-text').textContent = state.data ? 'Atualizando…' : 'Carregando… (o login do Snowflake pode abrir no navegador)';
  let res;
  try {
    res = await api().get_kpis(!!force);
  } catch (e) {
    res = { error: String(e) };
  }
  if (seq !== state.seq) return;
  $('btn-refresh').disabled = false;

  if (res.error) {
    $('error').innerHTML = `<span class="ic warn" aria-hidden="true">!</span><span class="grow">${esc(res.error)}</span>`;
    $('error').hidden = false;
    $('status-text').textContent = 'Falhou a última atualização';
    return;
  }
  $('error').hidden = true;
  $('avisos').hidden = !res.avisos.length;
  $('avisos').innerHTML = res.avisos.map(a => `<span class="ic warn" aria-hidden="true">!</span><span class="grow">${esc(a)}</span>`).join('');

  state.data = res;
  state.picker.setMonths(res.meses);
  state.mes = state.picker.value;
  const n = res.kpi2.n_vencidas_agora;
  window.setBadge('kp', n, `${n} fatura(s) CUSD vencida(s) sem pagamento`);
  $('status-text').textContent = `Atualizado ${fmtT.format(new Date(res.fetched_at))}`;
  render();
}

// ---------- eventos ----------
function bind() {
  $('btn-refresh').addEventListener('click', () => load(true));
  $('meses').addEventListener('click', e => {
    const tr = e.target.closest('tr.row');
    if (tr) state.picker.select(tr.dataset.mes);
  });
}

// ---------- init ----------
function init() {
  if (state.started) return;
  state.started = true;
  state.picker = window.MonthPicker.mount('kp', m => { state.mes = m; render(); });
  bind();
  load(false);
}

window.Monitors = window.Monitors || {};
window.Monitors.kpis = { init };
})();
