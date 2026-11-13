(() => {
'use strict';

// Seletor de mês fechado, o mesmo nas três abas: select "Mês" + chips "Este mês" / "Mês passado".
// Cada aba tem um <div class="monthpick" data-monthpick="<prefixo>"> no bloco de filtros e chama
// MonthPicker.mount(prefixo, onChange). O select vira id="<prefixo>-f-mes".

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

const monthStr = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const monthLabel = m => `${MESES[Number(m.slice(5)) - 1]}/${m.slice(2, 4)}`;

// Meses AAAA-MM de `from` até o mês atual, em ordem crescente.
function range(from) {
  const now = new Date(), out = [];
  let y = Number(from.slice(0, 4)), m = Number(from.slice(5)) - 1;
  while (y < now.getFullYear() || (y === now.getFullYear() && m <= now.getMonth())) {
    out.push(monthStr(new Date(y, m, 1)));
    if (++m > 11) { m = 0; y++; }
  }
  return out;
}

// Mês atual e anterior (os dois chips).
function quick() {
  const now = new Date();
  return { este: monthStr(now), passado: monthStr(new Date(now.getFullYear(), now.getMonth() - 1, 1)) };
}

function mount(prefix, onChange) {
  const box = document.querySelector(`[data-monthpick="${prefix}"]`);
  box.innerHTML = `<label>Mês <select id="${prefix}-f-mes"></select></label>
    <div class="quick">
      <button class="chip" data-quick="este">Este mês</button>
      <button class="chip" data-quick="passado">Mês passado</button>
    </div>`;
  const sel = box.querySelector('select');
  const chips = [...box.querySelectorAll('[data-quick]')];
  let months = [], value = null;

  const paint = () => {
    const q = quick();
    chips.forEach(b => b.classList.toggle('on', q[b.dataset.quick] === value));
  };
  const select = m => {
    if (!months.includes(m) || m === value) return;
    value = m;
    sel.value = m;
    paint();
    onChange(m);
  };

  sel.addEventListener('change', () => select(sel.value));
  chips.forEach(b => b.addEventListener('click', () => select(quick()[b.dataset.quick])));

  return {
    get value() { return value; },
    // Define os meses disponíveis (crescente). Mantém o mês escolhido se ainda existir; senão, o último.
    // Não dispara onChange: quem chama decide quando carregar.
    setMonths(list) {
      months = list;
      sel.innerHTML = [...list].reverse().map(m => `<option value="${m}">${monthLabel(m)}</option>`).join('');
      if (!months.includes(value)) value = months[months.length - 1] ?? null;
      sel.value = value ?? '';
      paint();
    },
    select,
  };
}

window.MonthPicker = { mount, range, monthStr, monthLabel };
})();
