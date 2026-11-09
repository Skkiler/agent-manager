// Renderizador Markdown minimo e SEGURO: monta nos DOM (nunca innerHTML). Suporta titulos, listas, codigo, **negrito**,
// *italico*, `codigo` e [[wikilinks]] clicaveis (resolvidos pelo chamador).
import { el } from "./ui.js";

const WIKI = /\[\[([^\[\]|#\n]{1,200})(?:[#|]([^\[\]\n]*))?\]\]/g;
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[\[[^\[\]\n]+\]\])/g;

function inline(texto, aoWikilink, existe) {
  const saida = [];
  for (const parte of texto.split(INLINE)) {
    if (!parte) continue;
    if (parte.startsWith("**") && parte.endsWith("**") && parte.length > 4) saida.push(el("strong", { textContent: parte.slice(2, -2) }));
    else if (parte.startsWith("`") && parte.endsWith("`") && parte.length > 2) saida.push(el("code", { textContent: parte.slice(1, -1) }));
    else if (parte.startsWith("[[")) {
      WIKI.lastIndex = 0;
      const m = WIKI.exec(parte);
      if (!m) { saida.push(parte); continue; }
      const alvo = m[1].trim();
      const rotulo = m[2] && !parte.includes("#") ? m[2] : alvo;
      const ok = existe(alvo);
      saida.push(el("button", { type: "button", className: `wikilink${ok ? "" : " quebrado"}`, textContent: rotulo,
        title: ok ? `Abrir ${alvo}` : `${alvo} ainda nao existe — clique para criar`, onclick: () => aoWikilink(alvo, ok) }));
    } else if (parte.startsWith("*") && parte.endsWith("*") && parte.length > 2) saida.push(el("em", { textContent: parte.slice(1, -1) }));
    else saida.push(parte);
  }
  return saida;
}

export function renderizar(markdown, { aoWikilink = () => {}, existe = () => true } = {}) {
  const raiz = el("div", { className: "leitura" });
  let lista = null;
  let codigo = null;
  for (const linha of String(markdown || "").split("\n")) {
    if (linha.startsWith("```")) {
      if (codigo) { raiz.append(el("pre", {}, el("code", { textContent: codigo.join("\n") }))); codigo = null; } else codigo = [];
      continue;
    }
    if (codigo) { codigo.push(linha); continue; }
    const t = /^(#{1,3})\s+(.*)$/.exec(linha);
    const li = /^\s*[-*]\s+(.*)$/.exec(linha);
    if (li) {
      if (!lista) { lista = el("ul"); raiz.append(lista); }
      lista.append(el("li", {}, ...inline(li[1], aoWikilink, existe)));
      continue;
    }
    lista = null;
    if (t) raiz.append(el(`h${t[1].length}`, {}, ...inline(t[2], aoWikilink, existe)));
    else if (linha.trim()) raiz.append(el("p", {}, ...inline(linha, aoWikilink, existe)));
  }
  if (codigo) raiz.append(el("pre", {}, el("code", { textContent: codigo.join("\n") })));
  return raiz;
}
