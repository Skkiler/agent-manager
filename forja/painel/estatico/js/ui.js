// Utilidades de DOM. Conteudo vindo do backend (agente, memoria, e-mail) e DADO: so textContent, nunca innerHTML.
export const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
export const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

export function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k in n && !k.includes("-")) n[k] = v;
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined && f !== false) n.append(f);
  return n;
}

export const limpar = (no) => no.replaceChildren();
export const tag = (texto, cls = "") => el("span", { className: `tag ${cls}`.trim(), textContent: texto });

export function toast(mensagem, tipo = "") {
  const t = el("div", { className: `toast ${tipo}`.trim(), textContent: mensagem });
  document.getElementById("avisos").append(t);
  setTimeout(() => t.remove(), tipo === "erro" ? 7000 : 3500);
}

export function dialogo(titulo, conteudo) {
  const d = document.getElementById("dlg-geral");
  const corpo = document.getElementById("dlg-geral-corpo");
  d.setAttribute("aria-labelledby", "dlg-geral-t");
  corpo.replaceChildren(el("h2", { id: "dlg-geral-t", textContent: titulo }), conteudo);
  if (!d.open) d.showModal();
  return { fechar: () => d.open && d.close() };
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
