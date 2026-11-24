// Utilidades de DOM. Conteudo vindo do backend (agente, memoria, e-mail) e DADO: so textContent, nunca innerHTML.
export const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
export const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

export function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k in n && !k.includes("-")) {
      // Algumas propriedades do DOM sao somente leitura (ex.: input.list, form.elements): cai no atributo.
      try { n[k] = v; } catch { n.setAttribute(k, v === true ? "" : String(v)); }
    }
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined && f !== false) n.append(f);
  return n;
}

export const limpar = (no) => no.replaceChildren();
export const tag = (texto, cls = "") => el("span", { className: `tag ${cls}`.trim(), textContent: texto });

export function toast(mensagem, tipo = "") {
  const caixa = document.getElementById("avisos");
  const t = el("div", { className: `toast ${tipo}`.trim(), textContent: mensagem });
  caixa.append(t);
  // Popover na top layer: o aviso fica ACIMA de janelas modais abertas (reabrir o traz para o topo da pilha).
  if (caixa.showPopover) { try { if (caixa.matches(":popover-open")) caixa.hidePopover(); caixa.showPopover(); } catch { /* sem suporte */ } }
  const sair = () => {  // sai deslizando (movimento.css); sem animacao (reduzir movimento) some na hora
    t.classList.add("saindo");
    setTimeout(() => { t.remove(); if (!caixa.children.length && caixa.hidePopover && caixa.matches(":popover-open")) caixa.hidePopover(); },
      matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180);
  };
  t.addEventListener("click", sair, { once: true });
  setTimeout(sair, tipo === "erro" ? 7000 : 3500);
}

// ---------------------------------------------------------------- janelas flutuantes
function cabecalho(dlg, titulo, idTitulo, aoFechar) {
  const fechar = el("button", { type: "button", className: "fechar", "aria-label": "Fechar janela", title: "Fechar (Esc)", textContent: "✕", onclick: () => aoFechar() });
  const cab = el("div", { className: "janela-cabeca", tabIndex: 0, title: "Arraste para mover (ou Alt+setas) · duplo clique centraliza" },
    el("h2", { id: idTitulo, textContent: titulo }), fechar);
  arrastavel(dlg, cab);
  return cab;
}

/** Arrastar a janela pelo cabecalho (ponteiro) ou, com o foco nele, com Alt+setas. Usa CSSOM (style.translate), permitido pela CSP.
 *  Os limites valem para qualquer posicao inicial (centralizada ou encostada no canto): o cabecalho nunca sai da tela. */
function arrastavel(dlg, alca) {
  let x = 0, y = 0, ini = null;
  const mover = (nx, ny) => {
    const r = dlg.getBoundingClientRect(), baseEsq = r.left - x, baseTopo = r.top - y;
    x = Math.max(120 - r.width - baseEsq, Math.min(innerWidth - 120 - baseEsq, nx));
    y = Math.max(-baseTopo, Math.min(innerHeight - 44 - baseTopo, ny));
    dlg.style.translate = `${x}px ${y}px`;
  };
  alca.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    ini = { px: ev.clientX - x, py: ev.clientY - y }; alca.setPointerCapture(ev.pointerId);
  });
  alca.addEventListener("pointermove", (ev) => { if (ini) mover(ev.clientX - ini.px, ev.clientY - ini.py); });
  alca.addEventListener("keydown", (ev) => { // teclado: o cabecalho recebe foco (tabindex 0) e Alt+setas movem a janela
    const d = { ArrowLeft: [-24, 0], ArrowRight: [24, 0], ArrowUp: [0, -24], ArrowDown: [0, 24] }[ev.key];
    if (!d || !ev.altKey || ev.target !== alca) return;
    ev.preventDefault(); mover(x + d[0], y + d[1]);
  });
  const soltar = () => { ini = null; };
  alca.addEventListener("pointerup", soltar); alca.addEventListener("pointercancel", soltar);
  alca.addEventListener("dblclick", () => { x = 0; y = 0; dlg.style.translate = ""; });
}

let seqJanela = 0, zJanela = 45; // 45: acima dos paineis (30) e menus (40), abaixo dos avisos (60)
const ENTRADA_FOCAVEL = 'input:not([type=hidden]):not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled):not(.fechar), [tabindex="0"]';
/** Janela flutuante independente (empilhavel). `antesDeFechar` pode devolver false para manter aberta.
 *  `modal: false` abre uma janela NAO BLOQUEANTE: a tela de fundo continua clicavel e navegavel (Tab, F6), Esc fecha a janela com o foco
 *  e o foco volta a quem a abriu. Com `id`, abrir de novo traz a janela ja aberta para a frente em vez de duplicar. */
export function janela(titulo, conteudo, { classe = "", id = "", antesDeFechar = null, aoFechar = null, modal = true } = {}) {
  const existente = id ? document.getElementById(id) : null;
  if (existente?.open && existente.dataset.janela) { existente.janelaFlutuante.trazer(); return existente.janelaFlutuante; }
  const idTitulo = `janela-t-${++seqJanela}`;
  const dlg = el("dialog", { className: `janela ${modal ? "" : "flutuante"} ${classe}`.trim(), id: id || undefined, "aria-labelledby": idTitulo, dataset: { janela: "1" } });
  const origem = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const fechar = () => { if (antesDeFechar && antesDeFechar() === false) return; if (dlg.open) dlg.close(); };
  dlg.append(cabecalho(dlg, titulo, idTitulo, fechar), el("div", { className: "janela-corpo" }, conteudo));
  dlg.addEventListener("cancel", (ev) => { if (antesDeFechar && antesDeFechar() === false) ev.preventDefault(); });
  dlg.addEventListener("close", () => {
    const tinhaFoco = dlg.contains(document.activeElement) || document.activeElement === document.body;
    dlg.remove(); aoFechar?.();
    if (tinhaFoco && origem?.isConnected) origem.focus({ preventScroll: true }); // devolve o foco a quem abriu (teclado)
  });
  const primeiroFoco = () => (dlg.querySelector(".janela-corpo")?.querySelector(ENTRADA_FOCAVEL) || dlg.querySelector(".janela-cabeca") || dlg).focus({ preventScroll: true });
  const trazer = () => { dlg.style.zIndex = String(++zJanela); if (!dlg.querySelector(".janela-corpo")?.contains(document.activeElement)) primeiroFoco(); };
  if (!modal) { // nao modal: o <dialog> nao trata Esc nem fica por cima sozinho
    dlg.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !ev.defaultPrevented) { ev.preventDefault(); ev.stopPropagation(); fechar(); } });
    dlg.addEventListener("pointerdown", () => { dlg.style.zIndex = String(++zJanela); }, { capture: true });
    dlg.style.zIndex = String(++zJanela);
  }
  document.body.append(dlg);
  if (modal) dlg.showModal(); else dlg.show();
  const resultado = { no: dlg, fechar, trazer, titulo: (t) => { dlg.querySelector(`#${idTitulo}`).textContent = t; } };
  dlg.janelaFlutuante = resultado;
  requestAnimationFrame(() => { if (dlg.open && !dlg.querySelector(".janela-corpo")?.contains(document.activeElement)) primeiroFoco(); });
  return resultado;
}

/** Janela unica de formularios curtos (#dlg-geral): mesma aparencia das outras janelas. */
export function dialogo(titulo, conteudo) {
  const d = document.getElementById("dlg-geral");
  const corpo = document.getElementById("dlg-geral-corpo");
  d.setAttribute("aria-labelledby", "dlg-geral-t");
  if (!d.querySelector(":scope > .janela-cabeca")) {
    d.prepend(cabecalho(d, titulo, "dlg-geral-t", () => d.open && d.close()));
    corpo.className = "janela-corpo";
  }
  d.querySelector("#dlg-geral-t").textContent = titulo;
  d.style.translate = "";
  corpo.replaceChildren(conteudo);
  if (!d.open) d.showModal();
  return { fechar: () => d.open && d.close() };
}

// ---------------------------------------------------------------- texto longo
/** Marca um elemento como recolhivel ("ler mais"): mostra `linhas` linhas e um botao so se o texto passar disso. */
export function recolhivel(no, linhas = 4) {
  no.classList.add("recolhivel");
  no.style.setProperty("--linhas", String(linhas));
  return no;
}

function prepararRecolhivel(no) {
  if (no.dataset.lerMais) return;
  no.dataset.lerMais = "1";
  requestAnimationFrame(() => {
    if (!no.isConnected || no.scrollHeight <= no.clientHeight + 2) return; // cabe inteiro: sem botao
    const b = el("button", { type: "button", className: "ler-mais", "aria-expanded": "false", textContent: "Ler mais" });
    b.addEventListener("click", () => {
      const aberto = no.classList.toggle("aberto");
      b.textContent = aberto ? "Ler menos" : "Ler mais"; b.setAttribute("aria-expanded", String(aberto));
    });
    no.after(b);
  });
}

/** Texto cortado com reticencias ganha dica com o texto inteiro (botoes, titulos, celulas, .trunc). */
function dicaSeCortado(ev) {
  const alvo = ev.target instanceof Element ? ev.target.closest("button, h1, h2, h3, .trunc, .tag, .pill, th, td, summary, .chip-anexo > span, #eventos li, #barra-status > span, label.chip-rotulo, .fio, .bloco") : null;
  if (!alvo || (alvo.title && !alvo.dataset.dicaAuto)) return;
  const cortado = alvo.scrollWidth > alvo.clientWidth + 1 || alvo.scrollHeight > alvo.clientHeight + 2;
  const texto = alvo.textContent.trim();
  if (cortado && texto) { alvo.title = texto; alvo.dataset.dicaAuto = "1"; }
  else if (alvo.dataset.dicaAuto) { alvo.removeAttribute("title"); delete alvo.dataset.dicaAuto; }
}

export function iniciarTexto() {
  document.addEventListener("pointerover", dicaSeCortado, { passive: true });
  document.addEventListener("focusin", dicaSeCortado);
  const varrer = (raiz) => { if (raiz.matches?.(".recolhivel")) prepararRecolhivel(raiz); raiz.querySelectorAll?.(".recolhivel").forEach(prepararRecolhivel); };
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => n.nodeType === 1 && varrer(n)))).observe(document.body, { childList: true, subtree: true });
  varrer(document.body);
}

export function dataCurta(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function abas(raiz, definicoes, ativa, aoMudar) {
  // Padrao ARIA de tabs: setas esquerda/direita movem o foco, Enter/Espaco ativam (botoes nativos).
  limpar(raiz);
  const botoes = definicoes.map((d) => el("button", {
    type: "button", role: "tab", id: `aba-${d.id}`, textContent: d.rotulo, "aria-selected": String(d.id === ativa),
    tabIndex: d.id === ativa ? 0 : -1, onclick: () => aoMudar(d.id),
    onkeydown: (ev) => {
      const i = botoes.indexOf(ev.currentTarget);
      const alvo = ev.key === "ArrowRight" ? botoes[(i + 1) % botoes.length] : ev.key === "ArrowLeft" ? botoes[(i - 1 + botoes.length) % botoes.length] : null;
      if (alvo) { ev.preventDefault(); alvo.focus(); alvo.click(); }
    },
  }));
  raiz.append(...botoes);
  return botoes;
}
