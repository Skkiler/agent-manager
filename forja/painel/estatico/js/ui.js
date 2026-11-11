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
  setTimeout(() => { t.remove(); if (!caixa.children.length && caixa.hidePopover && caixa.matches(":popover-open")) caixa.hidePopover(); }, tipo === "erro" ? 7000 : 3500);
}

// ---------------------------------------------------------------- janelas flutuantes
function cabecalho(dlg, titulo, idTitulo, aoFechar) {
  const fechar = el("button", { type: "button", className: "fechar", "aria-label": "Fechar janela", title: "Fechar (Esc)", textContent: "✕", onclick: () => aoFechar() });
  const cab = el("div", { className: "janela-cabeca" }, el("h2", { id: idTitulo, textContent: titulo }), fechar);
  arrastavel(dlg, cab);
  return cab;
}

/** Arrastar a janela pelo cabecalho (ponteiro). Usa CSSOM (style.translate), permitido pela CSP. */
function arrastavel(dlg, alca) {
  let x = 0, y = 0, ini = null;
  alca.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    ini = { px: ev.clientX - x, py: ev.clientY - y }; alca.setPointerCapture(ev.pointerId);
  });
  alca.addEventListener("pointermove", (ev) => {
    if (!ini) return;
    const r = dlg.getBoundingClientRect(), mx = innerWidth / 2 - 40, my = innerHeight / 2 - 30;
    x = Math.max(-mx - r.width / 2 + 120, Math.min(mx + r.width / 2 - 120, ev.clientX - ini.px));
    y = Math.max(-my, Math.min(my, ev.clientY - ini.py));
    dlg.style.translate = `${x}px ${y}px`;
  });
  const soltar = () => { ini = null; };
  alca.addEventListener("pointerup", soltar); alca.addEventListener("pointercancel", soltar);
  alca.addEventListener("dblclick", () => { x = 0; y = 0; dlg.style.translate = ""; });
}

let seqJanela = 0;
/** Janela flutuante independente (empilhavel). `antesDeFechar` pode devolver false para manter aberta. */
export function janela(titulo, conteudo, { classe = "", id = "", antesDeFechar = null, aoFechar = null } = {}) {
  const idTitulo = `janela-t-${++seqJanela}`;
  const dlg = el("dialog", { className: `janela ${classe}`.trim(), id: id || undefined, "aria-labelledby": idTitulo });
  const fechar = () => { if (antesDeFechar && antesDeFechar() === false) return; if (dlg.open) dlg.close(); };
  dlg.append(cabecalho(dlg, titulo, idTitulo, fechar), el("div", { className: "janela-corpo" }, conteudo));
  dlg.addEventListener("cancel", (ev) => { if (antesDeFechar && antesDeFechar() === false) ev.preventDefault(); });
  dlg.addEventListener("close", () => { dlg.remove(); aoFechar?.(); });
  document.body.append(dlg);
  dlg.showModal();
  return { no: dlg, fechar, titulo: (t) => { dlg.querySelector(`#${idTitulo}`).textContent = t; } };
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
  const alvo = ev.target instanceof Element ? ev.target.closest("button, h1, h2, h3, .trunc, .tag, .pill, th, td, summary, .chip-anexo > span, #eventos li") : null;
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
