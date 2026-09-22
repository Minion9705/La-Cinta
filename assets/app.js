/* La Cinta — lógica del sitio (sin dependencias) */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const root = document.documentElement;
  const params = new URLSearchParams(location.search);
  const DEMO = params.has('demo');
  const DATA_URL = DEMO ? 'data/ejemplo.json' : 'data/alertas.json';
  const REFRESCO_MS = 2 * 60 * 1000;

  // ---------- estado guardado en el navegador ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  let level = store.get('lc-level2', 'pri');
  let radar = store.get('lc-radar2', ['AAPL', 'NVDA', 'JPM']);
  let filtro = 'all';
  let verRutina = store.get('lc-rutina', false);
  let visibles = 15;
  let alertas = [];
  let actualizado = null;
  let simbolo = (params.get('t') || radar[0] || 'AAPL').toUpperCase();

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- fechas ----------
  const fmtHora = new Intl.DateTimeFormat('es-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' });
  const fmtDia = new Intl.DateTimeFormat('es-US', { day: 'numeric', month: 'short', timeZone: 'America/New_York' });
  function hace(iso) {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return `hace ${Math.floor(s)} s`;
    if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
    if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
    const d = Math.floor(s / 86400);
    return d === 1 ? 'ayer' : `hace ${d} días`;
  }
  const hoyET = (iso) => fmtDia.format(new Date(iso)) === fmtDia.format(new Date());
  const cuando = (iso) => hoyET(iso) ? fmtHora.format(new Date(iso)) : fmtDia.format(new Date(iso));

  // ---------- tema claro / oscuro ----------
  const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
  const MOON = '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const oscuro = () => root.dataset.theme ? root.dataset.theme === 'dark' : mq.matches;
  function pintarBotonTema() {
    const d = oscuro();
    $('#theme-ico').innerHTML = d ? SUN : MOON;
    $('#theme-txt').textContent = d ? 'Claro' : 'Oscuro';
    $('#theme-btn').setAttribute('aria-label', d ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro');
  }
  $('#theme-btn').addEventListener('click', () => {
    const next = oscuro() ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('lc-theme', next); } catch (e) {}
    pintarBotonTema();
  });
  if (mq.addEventListener) mq.addEventListener('change', pintarBotonTema);

  // ---------- nivel de explicación ----------
  function ponerNivel(l) {
    level = l; store.set('lc-level2', l);
    document.querySelectorAll('.level button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.level === l)));
    pintarTodo();
  }
  document.querySelectorAll('.level button').forEach((b) => b.addEventListener('click', () => ponerNivel(b.dataset.level)));

  // ---------- filtros ----------
  const TIPOS = [['all', 'Todas'], ['res', 'Resultados'], ['dir', 'Directivos'], ['int', 'Compras y ventas de directivos'],
    ['dil', 'Dilución'], ['deu', 'Deuda'], ['riesgo', 'Señales de riesgo'], ['rep', 'Reportes'], ['otros', 'Otros'], ['mine', '★ Mi radar']];
  $('#filters').innerHTML = TIPOS.map(([k, l]) => `<button type="button" class="chip" id="f-${k}" data-f="${k}" aria-pressed="${k === 'all'}">${l}</button>`).join('');
  $('#filters').addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]'); if (!b) return;
    filtro = b.dataset.f; visibles = 15;
    document.querySelectorAll('#filters .chip').forEach((c) => c.setAttribute('aria-pressed', String(c === b)));
    pintarFeed();
  });

  const SEV = { neg: 'Suele ser negativo', pos: 'Suele ser positivo', mix: 'Depende', neu: 'Informativo' };
  const nombreForm = (a) => a.form === '4' ? 'Form 4' : a.form + (a.items && a.items.length ? ' · ' + a.items.filter((i) => i !== '9.01').join(', ') : '');
  const texto = (a) => level === 'pri' ? a.pri : a.int;

  const cifras = (a) => (a.cifras && a.cifras.length) ? `<div class="cifras">${a.cifras.map((c) => `<span>${esc(c)}</span>`).join('')}</div>` : '';
  const esRutina = (a) => (a.relevancia || 2) <= 1;

  function tarjeta(a) {
    const on = radar.includes(a.ticker);
    return `<article class="alert" data-sev="${esc(a.sev)}">
      <div class="a-time"><b>${esc(cuando(a.fecha))}</b>${esc(hace(a.fecha))}</div>
      <div>
        <div class="a-meta">
          <button type="button" class="tk-btn pill" data-ver="${esc(a.ticker)}" title="Ver todo de ${esc(a.ticker)}">${esc(a.ticker)}</button>
          <span class="a-co">${esc(a.empresa)}</span>
          <span class="pill ${esc(a.sev)}">${SEV[a.sev] || ''}</span>
          <span class="pill">${esc(nombreForm(a))}</span>
          ${a.ia ? '<span class="pill ai" title="Resumen generado con IA a partir del documento">Resumen IA</span>' : ''}
        </div>
        <h3><a href="${esc(a.doc || a.url)}" target="_blank" rel="noopener">${esc(a.titulo)}</a></h3>
        <p>${esc(texto(a))}</p>
        ${cifras(a)}
        <div class="why"><b>Por qué importa:</b> ${esc(a.porque)}</div>
        <div class="a-links"><a href="${esc(a.doc || a.url)}" target="_blank" rel="noopener">Documento original ↗</a><a href="${esc(a.url)}" target="_blank" rel="noopener">Expediente en la SEC ↗</a></div>
      </div>
      <div class="a-side">
        <button type="button" class="star" data-star="${esc(a.ticker)}" aria-pressed="${on}" aria-label="${on ? 'Quitar' : 'Añadir'} ${esc(a.ticker)} ${on ? 'de' : 'a'} mi radar">★</button>
      </div>
    </article>`;
  }

  function pintarFeed() {
    const lista = alertas.filter((a) => (verRutina || !esRutina(a) || filtro === 'mine') &&
      (filtro === 'all' || (filtro === 'mine' ? radar.includes(a.ticker) : a.tipo === filtro)));
    const ocultas = verRutina ? 0 : alertas.filter(esRutina).length;
    $('#rutina-txt').textContent = ocultas ? `Mostrar trámites de rutina (${ocultas})` : 'Mostrar trámites de rutina';
    if (!alertas.length) {
      $('#feed').innerHTML = `<div class="skeleton">Todavía no hay alertas. Aparecerán aquí después de la primera actualización automática (cada 10 minutos).</div>`;
      return;
    }
    if (!lista.length) {
      $('#feed').innerHTML = `<div class="empty">${filtro === 'mine' ? 'Ninguna empresa de tu radar tiene alertas recientes.' : 'No hay alertas de este tipo por ahora.'}</div>`;
      return;
    }
    $('#feed').innerHTML = lista.slice(0, visibles).map(tarjeta).join('') +
      (lista.length > visibles ? `<button type="button" class="more" id="more">Ver más (${lista.length - visibles})</button>` : '');
  }
  $('#rutina').checked = verRutina;
  $('#rutina').addEventListener('change', (e) => { verRutina = e.target.checked; store.set('lc-rutina', verRutina); visibles = 15; pintarFeed(); });
  $('#feed').addEventListener('click', (e) => {
    const s = e.target.closest('[data-star]');
    if (s) { alternarRadar(s.dataset.star); return; }
    const v = e.target.closest('[data-ver]');
    if (v) { verEmpresa(v.dataset.ver, true); return; }
    if (e.target.id === 'more') { visibles += 15; pintarFeed(); }
  });

  // ---------- radar ----------
  function alternarRadar(t) {
    t = t.toUpperCase();
    radar = radar.includes(t) ? radar.filter((x) => x !== t) : [...radar, t];
    store.set('lc-radar2', radar);
    pintarRadar(); pintarFeed();
  }
  function pintarRadar() {
    $('#radar').innerHTML = radar.length ? radar.map((t) => {
      const n = alertas.filter((a) => a.ticker === t).length;
      const emp = (alertas.find((a) => a.ticker === t) || {}).empresa || '';
      return `<li><span><button type="button" class="tk-btn tk" data-ver="${esc(t)}">${esc(t)}</button><span class="nm">${esc(emp)}</span></span>
        <span><span class="nm">${n ? n + ' alerta' + (n > 1 ? 's' : '') : 'sin alertas'}</span><button type="button" class="x" data-quitar="${esc(t)}" aria-label="Quitar ${esc(t)}">×</button></span></li>`;
    }).join('') : '<li style="color:var(--ink-3)">Aún no sigues ninguna empresa.</li>';
  }
  $('#radar').addEventListener('click', (e) => {
    const q = e.target.closest('[data-quitar]'); if (q) { alternarRadar(q.dataset.quitar); return; }
    const v = e.target.closest('[data-ver]'); if (v) verEmpresa(v.dataset.ver, true);
  });
  $('#radar-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const t = $('#radar-input').value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
    if (t && !radar.includes(t)) alternarRadar(t);
    $('#radar-input').value = '';
  });

  // ---------- ¿Qué pasa con…? ----------
  function verEmpresa(t, desplazar) {
    t = String(t || '').trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
    if (!t) return;
    simbolo = t;
    $('#why-input').value = t;
    pintarEmpresa();
    if (desplazar) document.getElementById('why-form').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function pintarEmpresa() {
    const t = simbolo;
    const docs = alertas.filter((a) => a.ticker === t).slice(0, 8);
    $('#co-filings').innerHTML = docs.length
      ? `<div class="hint" style="margin:0">Lo último que presentó ante la SEC:</div>` + docs.map((a) =>
        `<a href="${esc(a.doc || a.url)}" target="_blank" rel="noopener"><small>${esc(cuando(a.fecha))} · ${esc(nombreForm(a))}</small>${esc(a.titulo)}</a>`).join('')
      : `<div class="hint" style="margin:0">Sin documentos importantes de ${esc(t)} en los últimos días${alertas.length ? '' : ' (o aún no hay datos)'}.</div>`;
  }
  $('#why-form').addEventListener('submit', (e) => { e.preventDefault(); verEmpresa($('#why-input').value); });

  // ---------- portada, resultados, teléfono ----------
  function pintarPortada() {
    const a = alertas.find((x) => (x.relevancia || 2) >= 3) || alertas.find((x) => x.sev !== 'neu') || alertas[0];
    $('#stat-count').textContent = alertas.filter((x) => Date.now() - new Date(x.fecha) < 3 * 864e5).length;
    if (!a) {
      $('#hero-title').textContent = 'Esperando la primera actualización';
      $('#hero-text').textContent = 'En cuanto una empresa presente algo importante ante la SEC, aparecerá aquí explicado en español.';
      $('#hero-age').textContent = '—';
      return;
    }
    $('#hero-pill').className = 'pill ' + a.sev;
    $('#hero-pill').textContent = `${a.ticker} · ${nombreForm(a)}`;
    $('#hero-age').textContent = hace(a.fecha);
    $('#hero-title').textContent = a.titulo;
    $('#hero-text').textContent = texto(a);
    $('#hero-cifras').innerHTML = cifras(a);
    const w = $('#hero-why'); w.hidden = false; w.textContent = a.porque;
    $('#hero-links').innerHTML = `<a href="${esc(a.doc || a.url)}" target="_blank" rel="noopener">Leer el documento original ↗</a>`;
  }
  function pintarResultados() {
    const res = alertas.filter((a) => a.tipo === 'res').slice(0, 6);
    $('#res-grid').innerHTML = res.length ? res.map((a) => `<article class="res-card">
        <div class="top"><span class="pill ${esc(a.sev)}">${esc(a.ticker)}</span><span class="updated">${esc(cuando(a.fecha))}</span></div>
        <h3>${esc(a.titulo)}</h3>
        <p>${esc(texto(a))}</p>
        ${cifras(a)}
        <div class="a-links"><a href="${esc(a.doc || a.url)}" target="_blank" rel="noopener">Ver reporte ↗</a><button type="button" class="tk-btn" style="color:var(--accent);font-weight:600" data-ver="${esc(a.ticker)}">Más de ${esc(a.ticker)}</button></div>
      </article>`).join('')
      : '<div class="notice">Ninguna empresa de la lista reportó resultados en los últimos días. En temporada de resultados (enero, abril, julio y octubre) esta sección se llena.</div>';
  }
  $('#res-grid').addEventListener('click', (e) => { const v = e.target.closest('[data-ver]'); if (v) verEmpresa(v.dataset.ver, true); });

  function pintarTodo() {
    pintarFeed(); pintarRadar(); pintarPortada(); pintarResultados(); pintarEmpresa();
    $('#updated').textContent = actualizado ? `Actualizado ${hace(actualizado)}` : '';
  }

  // ---------- datos ----------
  async function cargar() {
    if (window.LC_DATOS) { const d = window.LC_DATOS; alertas = d.alertas || []; actualizado = d.actualizado || null; pintarTodo(); return; }
    try {
      const r = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      alertas = (d.alertas || []).filter((a) => a && a.ticker && a.fecha);
      actualizado = d.actualizado || null;
    } catch (e) {
      if (!alertas.length) {
        $('#feed').innerHTML = `<div class="skeleton">No se pudieron cargar las alertas. Si abriste el archivo directamente en tu computadora, publícalo (por ejemplo en GitHub Pages) o usa un servidor local.</div>`;
      }
      return;
    }
    pintarTodo();
  }

  // ---------- arranque ----------
  if (DEMO) $('#demo-banner').hidden = false;
  document.querySelectorAll('.level button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.level === level)));
  $('#why-input').value = simbolo;
  pintarBotonTema();
  pintarRadar();
  cargar();
  setInterval(cargar, REFRESCO_MS);
  setInterval(() => { if (alertas[0]) { pintarPortada(); $('#updated').textContent = actualizado ? `Actualizado ${hace(actualizado)}` : ''; } }, 30000);
})();
