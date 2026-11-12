'use strict';

// Shell: abas, badges, tooltip global e boot dos monitores (github.js / prefect.js).
const TABS = { gh: 'github', pf: 'prefect' };

window.setBadge = (prefix, n) => {
  const b = document.getElementById(`${prefix}-badge`);
  b.textContent = n;
  b.hidden = !n;
  b.title = `${n} com último run em falha`;
};

function selectTab(key) {
  for (const k of Object.keys(TABS)) {
    document.getElementById(`view-${k}`).hidden = k !== key;
    document.querySelector(`.tab[data-tab="${k}"]`).classList.toggle('on', k === key);
  }
  try { localStorage.setItem('monitor-tab', key); } catch (e) { /* sem storage */ }
}

function bindShell() {
  document.querySelector('.tabs').addEventListener('click', e => {
    const t = e.target.closest('.tab');
    if (t) selectTab(t.dataset.tab);
  });

  const tip = document.getElementById('tip');
  document.addEventListener('mouseover', e => {
    const el = e.target.closest('[data-tip]');
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener('mousemove', e => {
    if (tip.hidden) return;
    const pad = 12, w = tip.offsetWidth, h = tip.offsetHeight;
    const x = e.clientX + pad + w > innerWidth - 8 ? e.clientX - w - pad : e.clientX + pad;
    const y = e.clientY + pad + h > innerHeight - 8 ? e.clientY - h - pad : e.clientY + pad;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, y)}px`;
  });
}

let started = false;
function boot() {
  if (started) return;
  started = true;
  bindShell();
  let saved = null;
  try { saved = localStorage.getItem('monitor-tab'); } catch (e) { /* sem storage */ }
  if (saved in TABS) selectTab(saved);
  // Os dois carregam já na abertura: o badge de cada aba mostra falhas mesmo com a aba fechada.
  // Cada monitor trata o próprio erro (ex.: Prefect sem VPN) dentro do seu painel.
  for (const ns of Object.values(TABS)) window.Monitors[ns].init();
}

// pywebview pode disparar 'pywebviewready' antes deste script registrar o listener.
if (typeof window.pywebview?.api?.github?.config === 'function') boot();
else window.addEventListener('pywebviewready', boot);
