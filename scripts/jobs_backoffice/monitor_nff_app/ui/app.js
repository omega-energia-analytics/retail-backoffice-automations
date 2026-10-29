const api = () => window.pywebview.api;

const state = {
  faturas: [],
  faturasFiltradas: [],
  nffs: [],
  nffsFiltradas: [],
  sortKey: null,
  sortAsc: true,
  quickFilter: 'all',
  lastUpdateTs: null,
  // seletor de mês (recorte por data de apresentação). Default = mês corrente.
  mesSelecionado: null,
  mesesDisponiveis: [],
  // Faturas Parceiro: lista da planilha de contratos + seu próprio seletor de
  // mês (fechamento), independente do das Faturas Usinas (recorte diferente).
  parceiros: [],
  parceirosFiltrados: [],
  parceirosQuickFilter: 'all',
  mesParceiroSelecionado: null,
  mesesParceiro: [],
  // Histórico: a busca por termo acontece no backend (SQL, indexado); o filtro
  // de campo é local, por cima do que voltou.
  historico: [],
  historicoFiltrado: [],
  // Total de linhas no log, independente do corte da consulta (ver hist-count).
  historicoTotal: 0
};

const MESES_NOMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];

function mesLabel(m) { return `${MESES_NOMES[m.mes - 1]}/${m.ano}`; }
function mesKey(m) { return `${m.ano}-${m.mes}`; }

function mesAtualValor() {
  const d = new Date();
  return { ano: d.getFullYear(), mes: d.getMonth() + 1 };
}

// mês efetivo pras chamadas da API (default = corrente)
function mesArgs() { return state.mesSelecionado || mesAtualValor(); }

// Filtros rápidos das faturas. Cada `pred` é a MESMA regra do card homônimo do
// dashboard (ver resumo_dashboard em api.py) — os cards são atalhos pra cá, então
// card e chip têm que contar igual. Ao mexer num, mexa no outro.
const FATURA_CHIPS = [
  { key: 'all',       label: 'Todas',      pred: () => true },
  { key: 'chegou',    label: 'Chegou',     pred: f => f.Status === 'Chegou' },
  { key: 'chegou_atr',label: 'Chegou atrasada', pred: f => f.Status === 'Chegou atrasada' },
  { key: 'atrasadas', label: 'Atrasadas',  pred: f => f.Status === 'Atrasada' },
  { key: 'vence3',    label: 'Vence ≤3d',  pred: f => f.Status === 'Pendente' && f['Dias Restantes'] != null && f['Dias Restantes'] <= 3 },
  { key: 'pagas',     label: 'Pagas',      pred: f => (f.Status === 'Chegou' || f.Status === 'Chegou atrasada') && !!f.Pago },
  { key: 'pagar',     label: 'A pagar',    pred: f => (f.Status === 'Chegou' || f.Status === 'Chegou atrasada') && !f.Pago }
];

// --- helpers ---
function toast(msg, type = '') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  setTimeout(() => t.className = '', 5000);
}

function showFatalError(where, err) {
  console.error('[fatal]', where, err);
  const main = document.querySelector('main');
  if (!main) return;
  const box = document.createElement('div');
  box.style.cssText = 'background:#7f1d1d;color:#fee2e2;padding:16px;border-radius:8px;margin:16px 0;font-family:Consolas,monospace;white-space:pre-wrap;font-size:12px;';
  box.textContent = `[${where}] ${err && err.stack ? err.stack : err}`;
  main.prepend(box);
}

function showLoading(show) {
  document.getElementById('loading').classList.toggle('hidden', !show);
}

// Copia texto pro clipboard com fallback (execCommand) caso a Clipboard API
// não esteja disponível no webview.
async function copyText(txt) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(txt);
      return true;
    }
  } catch (e) { /* cai no fallback */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = txt;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    return false;
  }
}

// célula clicável que copia seu valor
function copyCell(v) {
  if (v == null || v === '') return '—';
  const safe = String(v).replace(/"/g, '&quot;');
  return `<span class="copyable" data-copy="${safe}" title="Clique para copiar">${v} 📋</span>`;
}

async function call(fn) {
  showLoading(true);
  try {
    const r = await fn();
    if (!r) {
      console.error('Retorno null/undefined da API');
      toast('Erro: sem resposta da API', 'error');
      return null;
    }
    if (!r.ok) {
      console.error('Erro API:', r.error);
      toast('Erro: ' + r.error, 'error');
      return null;
    }
    return r.data;
  } catch (e) {
    console.error('Exception:', e);
    toast('Exception: ' + e.message, 'error');
    return null;
  } finally {
    showLoading(false);
  }
}

function renderTable(elId, data, columns, rowClassFn) {
  const tbl = document.getElementById(elId);
  if (!data || data.length === 0) {
    tbl.innerHTML = '<tbody><tr><td style="padding:32px;text-align:center;color:var(--muted)">Sem dados</td></tr></tbody>';
    return;
  }
  const thead = '<thead><tr>' + columns.map(c =>
    `<th data-key="${c.key}">${c.label}${state.sortKey === c.key ? (state.sortAsc ? ' ▲' : ' ▼') : ''}</th>`
  ).join('') + '</tr></thead>';

  const tbody = '<tbody>' + data.map(row => {
    const cls = rowClassFn ? rowClassFn(row) : '';
    return `<tr class="${cls}">` + columns.map(c => {
      const v = row[c.key];
      if (c.render) return `<td>${c.render(v, row)}</td>`;
      return `<td>${v == null ? '—' : v}</td>`;
    }).join('') + '</tr>';
  }).join('') + '</tbody>';

  tbl.innerHTML = thead + tbody;

  tbl.querySelectorAll('th').forEach((th, i) => {
    th.onclick = () => {
      const k = th.dataset.key;
      if (state.sortKey === k) state.sortAsc = !state.sortAsc;
      else { state.sortKey = k; state.sortAsc = true; }
      // sortValue: p/ colunas onde o texto exibido distingue mais estados que o valor
      // bruto do campo (ex.: "Pago" é sempre false p/ "A pagar" e "—", mas a UI mostra
      // dois textos diferentes) — sem isso ordenar não separa esses grupos.
      const col = columns[i];
      const getVal = col.sortValue ? (row => col.sortValue(row)) : (row => row[k]);
      const sorted = [...data].sort((a, b) => {
        const va = getVal(a), vb = getVal(b);
        if (va == null) return 1;
        if (vb == null) return -1;
        if (va < vb) return state.sortAsc ? -1 : 1;
        if (va > vb) return state.sortAsc ? 1 : -1;
        return 0;
      });
      renderTable(elId, sorted, columns, rowClassFn);
    };
  });
}

// --- views ---
function faturaCols() {
  return [
    { key: 'Projeto', label: 'Projeto' },
    { key: 'ACRONIMO', label: 'Acrônimo' },
    { key: 'Distribuidora', label: 'Distribuidora' },
    { key: 'Forma Recebimento', label: 'Forma' },
    { key: 'Data Esperada', label: 'Data Esperada' },
    { key: 'Data Chegada', label: 'Data Chegada' },
    // A aba é por mês de CHEGADA, então a competência é o que identifica QUAL fatura é
    // esta linha — e é comparando competência entre meses que se enxerga uma pulada.
    { key: 'Competência', label: 'Compet.', render: v => v || '—' },
    { key: 'Dias Restantes', label: 'Dias Rest.' },
    { key: 'Fatura ID', label: 'Fatura ID', render: v => copyCell(v) },
    { key: 'Total Fatura', label: 'Total Fatura', render: v => v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) },
    // Valor que o Oracle tem pra MESMA nota. "Pago" vem do Oracle e "Total Fatura" do
    // FattureWeb, então quando os dois não batem o painel dava a entender que o total do FW
    // foi quitado (NFF 047744547: 19.142,04 no FW, 7.525,59 no Oracle). Divergência
    // marcada em vermelho com a diferença no tooltip.
    { key: 'Valor Oracle', label: 'Valor Oracle', render: (v, row) => {
        if (v == null) return '—';
        const fmt = v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
        const dif = row['Divergência Valor'];
        // tolerância de 1 centavo: arredondamento das duas pontas não é divergência
        if (dif == null || Math.abs(dif) < 0.01) return fmt;
        const difFmt = dif.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
        return `<span class="valor-divergente" title="FattureWeb e Oracle não batem — diferença de ${difFmt} (FW menos Oracle)">${fmt} ⚠</span>`;
      }
    },
    { key: 'NFF', label: 'NFF', render: (v, row) => {
        // Chegou mais de uma fatura no mês pra esta usina. O painel é uma linha por
        // projeto, então a marca aqui é o que impede a 2ª de ficar invisível.
        const extras = row['NFF Adicionais'];
        if (!extras) return copyCell(v);
        const total = row['Faturas no Mês'];
        const safe = String(extras).replace(/"/g, '&quot;');
        return `${copyCell(v)} <span class="badge" title="${total} faturas chegaram neste mês para esta usina. Também: ${safe}">+${total - 1}</span>`;
      }
    },
    { key: 'UC', label: 'UC', render: v => copyCell(v) },
    { key: 'Status', label: 'Status', render: v => `<span class="status status-${(v||'').toLowerCase().replace(/\s+/g,'-')}">${v}</span>` },
    { key: 'Pago', label: 'Pago',
      // valor bruto é sempre false p/ "A pagar" e "—" (só distingue quem chegou); o
      // texto exibido é que separa os três estados, então o sort usa essa mesma régua.
      sortValue: row => {
        if (row.Pago) return 2;
        const chegou = row.Status === 'Chegou' || row.Status === 'Chegou atrasada';
        return chegou ? 1 : 0;
      },
      render: (v, row) => {
        if (v) {
          // 3ª fonte de pagamento (status da parcela no Oracle): não há data real de
          // pagamento, só o instante em que o Oracle virou o status — sinaliza com ≈ pra
          // ninguém tratar isso como data de liquidação.
          const aprox = row['Fonte Pagamento'] === 'ORACLE_INSTALLMENT';
          const data = row['Data Pagamento'] || '';
          const title = aprox
            ? 'Pago confirmado pela parcela do Oracle (sem registro em AP_PAYMENTS) — data aproximada'
            : 'Pago';
          return `<span class="status status-pago" title="${title}">✓ ${aprox ? '≈ ' : ''}${data}</span>`;
        }
        // só mostra "a pagar" pra faturas que já chegaram; senão fica neutro
        const chegou = row.Status === 'Chegou' || row.Status === 'Chegou atrasada';
        return chegou
          ? `<span class="status status-nao-pago">A pagar</span>`
          : `<span class="status status-neutro">—</span>`;
      }
    }
  ];
}

function faturaRowClass(row) {
  if (row.Status === 'Atrasada') return 'row-danger';
  if (row.Status === 'Chegou atrasada') return 'row-warn';
  if (row.Status === 'Pendente' && row['Dias Restantes'] != null && row['Dias Restantes'] <= 3) return 'row-warn';
  return '';
}

// --- Faturas Parceiro ---
const PARCEIRO_CHIPS = [
  { key: 'all',     label: 'Todas',        pred: () => true },
  { key: 'chegou',  label: 'Chegou',       pred: p => !!p.Chegou },
  { key: 'pendente',label: 'Não chegou',   pred: p => !p.Chegou }
];

function parceiroCols() {
  return [
    { key: 'Parceiro', label: 'Parceiro' },
    { key: 'FORNECEDOR', label: 'FORNECEDOR' },
    { key: 'PAGADOR', label: 'PAGADOR' },
    { key: 'Mês Fechamento', label: 'Mês Fechamento', render: v => dataBR(v) },
    { key: 'Data Emissão', label: 'Data Emissão', render: v => dataBR(v) },
    { key: 'Tipo de Nota', label: 'Tipo de Nota' },
    { key: 'Arrendamento', label: 'Arrendamento' },
    { key: 'Projeto', label: 'Projeto' },
    { key: 'Chegou', label: 'Chegou?',
      render: (v, row) => {
        // checkbox clicável — o clique é tratado por delegação (ver init), que
        // persiste via API e só então re-renderiza.
        const quem = row['Marcado Por'] ? ` por ${row['Marcado Por']}` : '';
        const title = v ? `Marcado em ${row['Marcado Em'] || '—'}${quem}` : 'Clique para marcar como recebida';
        return `<label class="chk-chegou" title="${String(title).replace(/"/g, '&quot;')}">` +
               `<input type="checkbox" data-chegou="${row._chave}"${v ? ' checked' : ''}></label>`;
      }
    }
  ];
}

// Datas vêm do backend em ISO (estável p/ ordenação); exibe no formato BR.
function dataBR(v) {
  if (!v) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : v;
}

function parceiroRowClass(row) {
  return row.Chegou ? 'row-ok' : '';
}

function renderMesParceiroSelector() {
  const sel = state.mesParceiroSelecionado;
  const opts = state.mesesParceiro.map(m => {
    const ativo = sel && m.ano === sel.ano && m.mes === sel.mes ? ' selected' : '';
    return `<option value="${mesKey(m)}"${ativo}>${mesLabel(m)}</option>`;
  }).join('');
  document.querySelectorAll('.sel-mes-parc').forEach(el => { el.innerHTML = opts; });
}

async function loadParceiros(forceRefresh = false) {
  // meses vêm da própria planilha; sem fechamento disponível não há o que filtrar
  if (!state.mesesParceiro.length || forceRefresh) {
    const meses = await call(() => api().meses_parceiros());
    if (!meses) return;
    state.mesesParceiro = meses;
    const cur = state.mesParceiroSelecionado;
    const existe = cur && meses.some(m => m.ano === cur.ano && m.mes === cur.mes);
    if (!existe) state.mesParceiroSelecionado = meses[0] || null;
    renderMesParceiroSelector();
  }
  const m = state.mesParceiroSelecionado;
  const data = await call(() => api().carregar_parceiros(m ? m.ano : null, m ? m.mes : null, forceRefresh));
  if (!data) return;
  state.parceiros = data;
  applyParceiroFilters();
}

function renderParceiroChips() {
  const el = document.getElementById('parceiros-chips');
  if (!el) return;
  el.innerHTML = PARCEIRO_CHIPS.map(c => {
    const n = state.parceiros.filter(c.pred).length;
    const active = state.parceirosQuickFilter === c.key ? ' active' : '';
    return `<button class="chip${active}" data-chip-parc="${c.key}">${c.label}<span class="chip-count">${n}</span></button>`;
  }).join('');
  el.querySelectorAll('.chip').forEach(btn => {
    btn.onclick = () => { state.parceirosQuickFilter = btn.dataset.chipParc; applyParceiroFilters(); };
  });
}

function applyParceiroFilters() {
  const txt = document.getElementById('filter-parceiros').value.toLowerCase();
  const chip = PARCEIRO_CHIPS.find(c => c.key === state.parceirosQuickFilter) || PARCEIRO_CHIPS[0];

  const filtered = state.parceiros.filter(p => {
    if (!chip.pred(p)) return false;
    if (txt) {
      const blob = `${p.Parceiro} ${p.FORNECEDOR} ${p.PAGADOR} ${p.Projeto} ${p['Tipo de Nota']} ${p.Arrendamento}`.toLowerCase();
      if (!blob.includes(txt)) return false;
    }
    return true;
  });
  state.parceirosFiltrados = filtered;
  renderParceiroChips();
  renderTable('tbl-parceiros', filtered, parceiroCols(), parceiroRowClass);
}

// Persiste o check e só reflete na UI depois do OK do backend — assim o que a
// tela mostra é sempre o que está salvo.
async function marcarChegou(chave, chegou) {
  const r = await call(() => api().marcar_chegou(chave, chegou));
  if (!r) { applyParceiroFilters(); return; }
  const linha = state.parceiros.find(p => p._chave === chave);
  if (linha) {
    linha.Chegou = r.chegou;
    if (!r.chegou) { linha['Marcado Em'] = null; linha['Marcado Por'] = null; }
  }
  applyParceiroFilters();
  toast(r.chegou ? 'Marcada como chegou' : 'Marcação removida', 'success');
}

function exportarParceiros() {
  const linhas = state.parceirosFiltrados.map(p => ({
    'Parceiro': p.Parceiro,
    'FORNECEDOR': p.FORNECEDOR,
    'PAGADOR': p.PAGADOR,
    'Mês Fechamento': dataBR(p['Mês Fechamento']),
    'Data Emissão': dataBR(p['Data Emissão']),
    'Tipo de Nota': p['Tipo de Nota'],
    'Arrendamento': p.Arrendamento,
    'Projeto': p.Projeto,
    'Chegou?': p.Chegou ? 'Sim' : 'Não',
    'Marcado Em': p['Marcado Em'] || '',
    'Marcado Por': p['Marcado Por'] || ''
  }));
  exportar(linhas, `faturas_parceiro_${hojeStr()}.xlsx`, 'faturas de parceiro');
}

// --- Histórico ---
// Rótulos dos estados de Pago no banco ('sim'/'nao', ver db._txt) — a tabela
// mostra a mesma palavra que o painel usa, não o valor cru.
const HIST_PAGO = { sim: 'Pago', nao: 'A pagar' };

// Campos de dinheiro — o backend grava sempre '1234.56' (ver db.CAMPOS_VALOR),
// independente de a fonte ter mandado float ou texto em formato BR.
const HIST_CAMPOS_VALOR = new Set(['Total Fatura', 'Valor Oracle']);

// 'AAAA-MM' (como o backend guarda, ordenável) -> 'MM/AAAA' (como o painel mostra)
function mesPainelBR(v) {
  const m = /^(\d{4})-(\d{2})$/.exec(v || '');
  return m ? `${m[2]}/${m[1]}` : (v || '—');
}

function histValor(campo, v) {
  if (v == null || v === '') return '<span class="muted">—</span>';
  if (campo === 'Pago') return HIST_PAGO[v] || v;
  if (HIST_CAMPOS_VALOR.has(campo)) {
    const n = Number(v);
    return isNaN(n) ? v : n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  }
  return v;
}

function historicoCols() {
  return [
    { key: 'observado_em', label: 'Quando',
      render: v => v ? new Date(v).toLocaleString('pt-BR') : '—' },
    { key: 'acronimo', label: 'Acrônimo', render: (v, row) => v || row.projeto || '—' },
    // Mês do painel (recorte por data de chegada) e competência da fatura são
    // coisas diferentes e podem divergir — a fatura que ainda não chegou tem
    // mês e não tem competência.
    { key: 'mes_painel', label: 'Mês', render: v => mesPainelBR(v) },
    { key: 'competencia', label: 'Compet.', render: v => v || '—' },
    { key: 'nff', label: 'NFF', render: v => v ? copyCell(v) : '—' },
    { key: 'campo', label: 'Campo' },
    { key: 'valor_de', label: 'De', render: (v, row) => histValor(row.campo, v) },
    { key: 'valor_para', label: 'Para',
      render: (v, row) => `<strong>${histValor(row.campo, v)}</strong>` }
  ];
}

// Linha em que o campo saiu do nada (primeira vez que a fatura apareceu com
// aquele valor) tem leitura diferente de uma troca de valor — marca as duas.
function historicoRowClass(row) {
  if (row.valor_de == null || row.valor_de === '') return 'row-ok';
  return '';
}

// 0 na caixa de limite = sem teto. O backend espera um número, então manda um
// valor alto o bastante pra cobrir o log inteiro em vez de um caso especial.
const HIST_SEM_LIMITE = 1000000;

function histLimite() {
  const v = parseInt(document.getElementById('filter-hist-limite').value, 10);
  return v > 0 ? v : HIST_SEM_LIMITE;
}

async function loadHistorico() {
  await ensureMesesHistorico();
  const termo = document.getElementById('filter-historico').value;
  const inicial = document.getElementById('chk-carga-inicial').checked;
  const mes = document.getElementById('filter-hist-mes').value || null;
  const data = await call(
    () => api().buscar_historico(termo, histLimite(), inicial, mes));
  if (!data) return;
  state.historico = data;
  applyHistoricoFilter();
  mostrarOrigemHistorico();
}

// Meses vêm do próprio log (uma vez por abertura da aba). Sem este filtro, o
// corte em 500 linhas alcança só os dois meses mais recentes e o resto do
// histórico fica invisível pela tela.
async function ensureMesesHistorico() {
  const sel = document.getElementById('filter-hist-mes');
  if (sel.options.length > 1) return;
  const meses = await call(() => api().meses_historico());
  if (!meses || !meses.length) return;
  sel.innerHTML = '<option value="">Todos os meses</option>' +
    meses.map(m => `<option value="${m}">${mesPainelBR(m)}</option>`).join('');
}

// Onde o log mora e desde quando — "onde isso fica salvo?" é a primeira
// pergunta de quem abre a aba, e o caminho não está em lugar nenhum da UI.
async function mostrarOrigemHistorico() {
  const el = document.getElementById('hist-origem');
  try {
    const r = await api().resumo_historico();
    if (!r || !r.ok) return;
    const d = r.data;
    const desde = d.carga_inicial_em
      ? ` · registrando desde ${new Date(d.carga_inicial_em).toLocaleString('pt-BR')}`
      : '';
    state.historicoTotal = d.total;
    el.textContent = `${d.total} linhas em ${d.caminho}${desde}`;
    applyHistoricoFilter();
  } catch (e) { /* rodapé informativo não bloqueia a aba */ }
}

function applyHistoricoFilter() {
  const campo = document.getElementById('filter-hist-campo').value;
  const filtered = campo ? state.historico.filter(h => h.campo === campo) : state.historico;
  state.historicoFiltrado = filtered;
  // A consulta corta no limite escolhido; diz sempre o tamanho do log inteiro,
  // senão "500 mudanças" se lê como se o histórico todo fosse esse.
  const limite = histLimite();
  const bateuTeto = state.historico.length >= limite;
  const total = state.historicoTotal;
  const deTotal = total ? ` de ${total} no log` : '';
  const el = document.getElementById('hist-count');
  el.textContent = `${filtered.length} mudanças${deTotal}` +
    (bateuTeto ? ` (${limite} mais recentes)` : '');
  el.title = bateuTeto
    ? 'A consulta bateu no limite escolhido — aumente o limite, filtre por mês ou busque uma usina para alcançar o resto.'
    : '';
  renderTable('tbl-historico', filtered, historicoCols(), historicoRowClass);

  // Tela vazia aqui é o estado NORMAL logo após a primeira carga, não falha —
  // sem esta explicação ela parece uma aba quebrada.
  if (!filtered.length && !document.getElementById('chk-carga-inicial').checked) {
    document.getElementById('tbl-historico').innerHTML =
      '<tbody><tr><td style="padding:32px;text-align:center;color:var(--muted)">' +
      'Nenhuma mudança ainda.<br>A partir daqui, só o que mudar no painel aparece aqui.<br>' +
      '<small>Marque "incluir carga inicial" para ver o retrato de quando o log começou.</small>' +
      '</td></tr></tbody>';
  }
}

function exportarHistorico() {
  const linhas = state.historicoFiltrado.map(h => ({
    'Quando': h.observado_em ? new Date(h.observado_em).toLocaleString('pt-BR') : '',
    'Projeto': h.projeto,
    'Acrônimo': h.acronimo,
    'Mês': mesPainelBR(h.mes_painel),
    'Competência': h.competencia,
    'NFF': h.nff,
    'Campo': h.campo,
    'De': h.valor_de,
    'Para': h.valor_para
  }));
  exportar(linhas, `historico_${hojeStr()}.xlsx`, 'mudanças');
}

// --- seletor de mês ---
// Popula todos os <select class="sel-mes"> (dashboard + faturas) a partir de
// state.mesesDisponiveis, marcando o mês selecionado.
function renderMesSelectors() {
  const sel = state.mesSelecionado;
  const opts = state.mesesDisponiveis.map(m => {
    const ativo = sel && m.ano === sel.ano && m.mes === sel.mes ? ' selected' : '';
    return `<option value="${mesKey(m)}"${ativo}>${mesLabel(m)}</option>`;
  }).join('');
  document.querySelectorAll('.sel-mes').forEach(el => { el.innerHTML = opts; });
}

// Garante que a lista de meses foi carregada (uma vez). A base do backend é
// cacheada, então isso só bate no Snowflake na primeira chamada.
async function ensureMeses() {
  if (state.mesesDisponiveis.length) return;
  const meses = await call(() => api().meses_disponiveis());
  if (!meses) return;
  state.mesesDisponiveis = meses;
  // se o mês selecionado sumiu da base (ou ainda não há um), cai no corrente
  const cur = state.mesSelecionado;
  const existe = cur && meses.some(m => m.ano === cur.ano && m.mes === cur.mes);
  if (!existe) state.mesSelecionado = mesAtualValor();
  renderMesSelectors();
}

function reloadActiveView() {
  const active = document.querySelector('.nav-btn.active').dataset.view;
  if (active === 'dashboard') loadDashboard();
  else if (active === 'faturas') loadFaturas();
}

// troca de mês em qualquer um dos seletores → sincroniza os demais e recarrega
function onMesChange(e) {
  const [ano, mes] = e.target.value.split('-').map(Number);
  state.mesSelecionado = { ano, mes };
  document.querySelectorAll('.sel-mes').forEach(el => { el.value = e.target.value; });
  reloadActiveView();
}

async function loadDashboard() {
  console.log('[loadDashboard] carregando faturas...');
  await ensureMeses();
  const m = mesArgs();
  const fat = await call(() => api().carregar_faturas(m.ano, m.mes, false));
  console.log('[loadDashboard] faturas retornou:', fat ? fat.length + ' registros' : 'null');
  if (!fat) return;
  state.faturas = fat;

  console.log('[loadDashboard] chamando resumo_dashboard...');
  const resumo = await call(() => api().resumo_dashboard(m.ano, m.mes));
  console.log('[loadDashboard] resumo retornou:', resumo);
  if (!resumo) return;

  // `chip` é o filtro que a lista de Faturas assume ao clicar no card. O dashboard
  // é só o placar; a lista de qualquer número mora em Faturas.
  const cards = [
    { label: 'Total projetos', value: resumo.total_projetos, cls: '', chip: 'all' },
    { label: 'Chegou', value: resumo.chegou, cls: 'ok', chip: 'chegou' },
    { label: 'Chegou atrasada', value: resumo.chegou_atrasada, cls: 'warn', chip: 'chegou_atr' },
    { label: 'Atrasadas', value: resumo.atrasadas, cls: 'danger', chip: 'atrasadas' },
    { label: 'Próx. vencimento (≤3d)', value: resumo.proximas_vencimento, cls: 'warn', chip: 'vence3' },
    { label: 'Pagas', value: resumo.pagas, cls: 'ok', chip: 'pagas' },
    { label: 'A pagar', value: resumo.nao_pagas, cls: 'warn', chip: 'pagar' },
    // { label: 'NFFs no banco', value: resumo.total_nffs_db, cls: '' }
  ];
  const el = document.getElementById('cards-dashboard');
  el.innerHTML = cards.map(c =>
    `<div class="card ${c.cls}" data-chip="${c.chip}" title="Ver estas faturas na lista">` +
    `<div class="label">${c.label}</div><div class="value">${c.value}</div></div>`
  ).join('');
  el.querySelectorAll('.card').forEach(card => {
    card.onclick = () => {
      state.quickFilter = card.dataset.chip;
      // zera os selects pra não cruzar com o filtro do card e devolver menos linhas
      // do que o número clicado
      document.getElementById('filter-text').value = '';
      document.getElementById('filter-status').value = '';
      document.getElementById('filter-pago').value = '';
      switchView('faturas');
    };
  });

  fetchLastUpdate();
}

async function loadFaturas() {
  console.log('[loadFaturas] carregando...');
  await ensureMeses();
  const m = mesArgs();
  const fat = await call(() => api().carregar_faturas(m.ano, m.mes, false));
  if (!fat) return;
  state.faturas = fat;
  applyFilters();
  fetchLastUpdate();
}

function renderChips() {
  const el = document.getElementById('faturas-chips');
  if (!el) return;
  el.innerHTML = FATURA_CHIPS.map(c => {
    const n = state.faturas.filter(c.pred).length;
    const active = state.quickFilter === c.key ? ' active' : '';
    return `<button class="chip${active}" data-chip="${c.key}">${c.label}<span class="chip-count">${n}</span></button>`;
  }).join('');
  el.querySelectorAll('.chip').forEach(btn => {
    btn.onclick = () => { state.quickFilter = btn.dataset.chip; applyFilters(); };
  });
}

function applyFilters() {
  const txt = document.getElementById('filter-text').value.toLowerCase();
  const status = document.getElementById('filter-status').value;
  const pago = document.getElementById('filter-pago').value;
  const chip = FATURA_CHIPS.find(c => c.key === state.quickFilter) || FATURA_CHIPS[0];

  const filtered = state.faturas.filter(f => {
    if (!chip.pred(f)) return false;
    if (status && f.Status !== status) return false;
    if (pago === 'pago' && !f.Pago) return false;
    if (pago === 'nao-pago' && f.Pago) return false;
    if (txt) {
      const blob = `${f.Projeto} ${f.ACRONIMO} ${f.Distribuidora} ${f.NFF ?? ''} ${f.UC ?? ''}`.toLowerCase();
      if (!blob.includes(txt)) return false;
    }
    return true;
  });
  state.faturasFiltradas = filtered;
  renderChips();
  renderTable('tbl-faturas', filtered, faturaCols(), faturaRowClass);
}

async function loadNffs() {
  console.log('[loadNffs] carregando...');
  const data = await call(() => api().listar_nffs());
  if (!data) return;
  state.nffs = data;
  document.getElementById('nff-count').textContent = `${data.length} registros`;
  applyNffFilter();
}

function applyNffFilter() {
  const q = document.getElementById('search-nff').value.toLowerCase();
  const filtered = q ? state.nffs.filter(n => n.numero_nff.toLowerCase().includes(q)) : state.nffs;
  state.nffsFiltradas = filtered;
  renderTable('tbl-nffs', filtered, [
    { key: 'numero_nff', label: 'Número NFF', render: v => copyCell(v) },
    { key: 'data_envio', label: 'Data Registro', render: v => v ? new Date(v).toLocaleString('pt-BR') : '—' }
  ]);
}

async function processarExcel() {
  const log = document.getElementById('excel-log');
  log.textContent = 'Processando...';
  const r = await call(() => api().processar_excel());
  if (!r) { log.textContent = 'Falha.'; return; }
  log.textContent = [
    `Total NFFs na planilha: ${r.total_planilha}`,
    `Já registradas: ${r.ja_registradas}`,
    `Novas detectadas: ${r.novas}`,
    `Inseridas no banco: ${r.inseridas.length}`,
    '',
    r.inseridas.length ? 'Inseridas:' : '',
    ...r.inseridas.map(n => `  ✔ ${n}`)
  ].join('\n');
  toast(`${r.inseridas.length} NFFs inseridas`, 'success');
}

// --- exportação Excel ---
function hojeStr() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

async function exportar(linhas, nomeSugerido, label) {
  if (!linhas || !linhas.length) { toast(`Sem ${label} para exportar`, 'error'); return; }
  const r = await call(() => api().exportar_excel(linhas, nomeSugerido));
  if (!r) return;
  if (r.cancelado) return;
  toast(`${r.linhas} ${label} exportadas`, 'success');
}

function exportarFaturas() {
  const linhas = state.faturasFiltradas.map(f => ({
    'Projeto': f.Projeto,
    'Acrônimo': f.ACRONIMO,
    'Distribuidora': f.Distribuidora,
    'Forma Recebimento': f['Forma Recebimento'],
    'Data Esperada': f['Data Esperada'],
    'Data Chegada': f['Data Chegada'],
    'Competência': f['Competência'],
    'Dias Restantes': f['Dias Restantes'],
    'Status': f.Status,
    'NFF': f.NFF,
    'UC': f.UC,
    'Pago': f.Pago ? 'Sim' : 'Não',
    'Data Pagamento': f['Data Pagamento'],
    // rastro de qual fonte confirmou o pagamento — ORACLE_INSTALLMENT = data aproximada
    'Fonte Pagamento': f['Fonte Pagamento'],
    // faturas que chegaram no mesmo mês e não são a exibida (o painel é 1 linha/projeto)
    'Faturas no Mês': f['Faturas no Mês'],
    'NFF Adicionais': f['NFF Adicionais'],
    'Fatura ID': f['Fatura ID'],
    'Total Fatura': f['Total Fatura'],
    // valor da MESMA nota no Oracle + a diferença contra o FattureWeb
    'Valor Oracle': f['Valor Oracle'],
    'Divergência Valor': f['Divergência Valor']
  }));
  exportar(linhas, `faturas_${hojeStr()}.xlsx`, 'faturas');
}

function exportarNffs() {
  const linhas = state.nffsFiltradas.map(n => ({
    'Número NFF': n.numero_nff,
    'Data Registro': n.data_envio ? new Date(n.data_envio).toLocaleString('pt-BR') : ''
  }));
  exportar(linhas, `nffs_${hojeStr()}.xlsx`, 'NFFs');
}

async function copiarNffsLista() {
  const linhas = state.nffsFiltradas.map(n => n.numero_nff);
  if (!linhas.length) { toast('Nenhuma NFF para copiar', 'error'); return; }
  const ok = await copyText(linhas.join('\n'));
  toast(ok ? `${linhas.length} NFFs copiadas` : 'Falha ao copiar', ok ? 'success' : 'error');
}

// --- atualização / auto-refresh ---
let autoRefreshTimer = null;

function relTime(iso) {
  if (!iso) return 'Sem dados carregados';
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return 'Atualizado agora';
  if (min < 60) return `Atualizado há ${min} min`;
  const h = Math.floor(min / 60);
  return `Atualizado há ${h}h${String(min % 60).padStart(2, '0')}`;
}

function renderLastUpdate() {
  document.getElementById('last-update').textContent = relTime(state.lastUpdateTs);
}

async function fetchLastUpdate() {
  try {
    const r = await api().ultima_atualizacao();
    if (r && r.ok) { state.lastUpdateTs = r.data.ts; renderLastUpdate(); }
  } catch (e) { /* não bloqueia a UI */ }
}

async function refreshData() {
  const active = document.querySelector('.nav-btn.active').dataset.view;
  // Faturas Parceiro lê a planilha de contratos, não o Snowflake — recarregar a
  // base aqui seria uma consulta cara que não alimenta nada desta aba.
  if (active === 'parceiros') {
    state.mesesParceiro = [];
    await loadParceiros(true);
    toast('Planilha recarregada', 'success');
    return;
  }
  // O histórico lê o SQLite local, que só ganha linha quando a base recarrega.
  // Reconsultar o banco aqui é barato e é o que o usuário espera; puxar o
  // Snowflake de novo não traria nada que ele já não tenha escrito.
  if (active === 'historico') {
    await loadHistorico();
    toast('Histórico recarregado', 'success');
    return;
  }
  const m = mesArgs();
  // force_refresh recarrega a base (Snowflake); demais chamadas reusam o cache
  await call(() => api().carregar_faturas(m.ano, m.mes, true));
  state.mesesDisponiveis = [];  // base pode ter meses novos → recomputa o seletor
  await fetchLastUpdate();
  switchView(active);
  toast('Dados atualizados', 'success');
}

function setAutoRefresh(on) {
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  if (on) autoRefreshTimer = setInterval(refreshData, 15 * 60 * 1000);
}

// --- configuração / arquivo ---
async function carregarConfig() {
  const cfg = await call(() => api().obter_config());
  if (!cfg) return;
  document.getElementById('excel-path').textContent = cfg.arquivo_excel || '—';
}

async function escolherArquivo() {
  const r = await call(() => api().selecionar_arquivo_excel());
  if (!r || r.cancelado) return;
  document.getElementById('excel-path').textContent = r.arquivo_excel;
  toast('Arquivo selecionado', 'success');
}

// --- navegação ---
function switchView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  document.querySelector(`.nav-btn[data-view="${view}"]`).classList.add('active');

  if (view === 'dashboard') loadDashboard();
  if (view === 'faturas') loadFaturas();
  if (view === 'parceiros') loadParceiros();
  if (view === 'historico') loadHistorico();
  if (view === 'nffs') loadNffs();
  if (view === 'excel') carregarConfig();
}

// --- init ---
function init() {
  console.log('[init] iniciando UI');
  try {
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.onclick = () => switchView(btn.dataset.view);
    });
    document.getElementById('btn-refresh').onclick = refreshData;
    document.getElementById('chk-auto').onchange = e => setAutoRefresh(e.target.checked);
    // mantém o "atualizado há X min" vivo sem rebater na API
    setInterval(renderLastUpdate, 30000);
    document.getElementById('filter-text').oninput = applyFilters;
    document.getElementById('filter-status').onchange = applyFilters;
    document.getElementById('filter-pago').onchange = applyFilters;
    document.querySelectorAll('.sel-mes').forEach(el => { el.onchange = onMesChange; });
    document.getElementById('filter-parceiros').oninput = applyParceiroFilters;
    document.getElementById('btn-export-parceiros').onclick = exportarParceiros;
    document.querySelectorAll('.sel-mes-parc').forEach(el => {
      el.onchange = e => {
        const [ano, mes] = e.target.value.split('-').map(Number);
        state.mesParceiroSelecionado = { ano, mes };
        renderMesParceiroSelector();
        loadParceiros();
      };
    });
    // Diferente dos outros filtros (locais), este consulta o banco — debounce
    // pra não disparar uma query por tecla digitada.
    let histTimer = null;
    document.getElementById('filter-historico').oninput = () => {
      clearTimeout(histTimer);
      histTimer = setTimeout(loadHistorico, 300);
    };
    document.getElementById('filter-hist-campo').onchange = applyHistoricoFilter;
    // Reconsulta o banco (o corte do mês é no SQL), como o check de carga inicial.
    document.getElementById('filter-hist-mes').onchange = loadHistorico;
    document.getElementById('filter-hist-limite').onchange = loadHistorico;
    // Este reconsulta o banco (o corte é no SQL), diferente do filtro de campo.
    document.getElementById('chk-carga-inicial').onchange = loadHistorico;
    document.getElementById('btn-export-historico').onclick = exportarHistorico;

    document.getElementById('search-nff').oninput = applyNffFilter;
    document.getElementById('btn-processar').onclick = processarExcel;
    document.getElementById('btn-export-faturas').onclick = exportarFaturas;
    document.getElementById('btn-export-nffs').onclick = exportarNffs;
    document.getElementById('btn-escolher-arquivo').onclick = escolherArquivo;
    document.getElementById('btn-copiar-nffs').onclick = copiarNffsLista;

    // check "Chegou?" — a tabela é re-renderizada a cada filtro, então o handler
    // vive no document em vez de ser religado em cada checkbox.
    document.addEventListener('change', e => {
      const chk = e.target.closest('input[data-chegou]');
      if (!chk) return;
      marcarChegou(chk.dataset.chegou, chk.checked);
    });

    // clique em qualquer célula .copyable copia o valor (delegação de evento)
    document.addEventListener('click', e => {
      const el = e.target.closest('.copyable');
      if (!el || !el.dataset.copy) return;
      copyText(el.dataset.copy).then(ok =>
        toast(ok ? `Copiado: ${el.dataset.copy}` : 'Falha ao copiar', ok ? 'success' : 'error')
      );
    });
  } catch (e) {
    showFatalError('init/wire', e);
    return;
  }

  loadDashboard().catch(e => showFatalError('loadDashboard', e));
}

// Captura erros globais que de outra forma sumiriam
window.addEventListener('error', e => showFatalError('window.error', e.error || e.message));
window.addEventListener('unhandledrejection', e => showFatalError('unhandledrejection', e.reason));

// pywebview pode disparar 'pywebviewready' ANTES deste script registrar o listener.
// Por isso checamos se a API já está disponível e, se sim, iniciamos direto.
// Fallback: se em 8s nada disparou, mostra erro visível em vez de ficar em branco.
let initialized = false;
function tryInit(source) {
  if (initialized) return;
  if (window.pywebview && window.pywebview.api) {
    initialized = true;
    console.log('[init] disparado por:', source);
    init();
  }
}
window.addEventListener('pywebviewready', () => tryInit('pywebviewready'));
document.addEventListener('DOMContentLoaded', () => tryInit('DOMContentLoaded'));
tryInit('inline');
setTimeout(() => {
  if (!initialized) {
    showFatalError('init/timeout', 'window.pywebview.api não ficou disponível em 8s. O backend Python provavelmente não está injetando a API — verifique o terminal onde rodou `python main.py`.');
  }
}, 8000);