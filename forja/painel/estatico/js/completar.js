// Autocompletar do editor (IntelliSense leve, sem servidor de linguagem): palavras do arquivo, palavras-chave da linguagem e
// trechos prontos (snippets). Lista ARIA (listbox) ligada a textarea por aria-activedescendant; setas, Enter/Tab e Esc.
import { palavrasChave } from "./realce.js";
import { el } from "./ui.js";

const TRECHOS = {
  python: [["def", "def ${nome}(${args}):\n    ${0}", "função"], ["class", "class ${Nome}:\n    def __init__(self):\n        ${0}", "classe"],
    ["main", "if __name__ == \"__main__\":\n    ${0}", "ponto de entrada"], ["for", "for ${item} in ${itens}:\n    ${0}", "laço"],
    ["try", "try:\n    ${0}\nexcept ${Exception} as e:\n    raise", "tratamento de erro"], ["with", "with open(${arquivo}, encoding=\"utf-8\") as f:\n    ${0}", "abrir arquivo"],
    ["test", "def test_${nome}():\n    assert ${0}", "teste pytest"]],
  javascript: [["function", "function ${nome}(${args}) {\n  ${0}\n}", "função"], ["arrow", "const ${nome} = (${args}) => {\n  ${0}\n};", "função seta"],
    ["forof", "for (const ${item} of ${itens}) {\n  ${0}\n}", "laço"], ["try", "try {\n  ${0}\n} catch (e) {\n  console.error(e);\n}", "tratamento de erro"],
    ["import", "import { ${0} } from \"${modulo}\";", "importar"], ["fetch", "const resp = await fetch(${url});\nconst dados = await resp.json();${0}", "requisição"]],
  markdown: [["link", "[${texto}](${url})${0}", "link"], ["img", "![${descricao}](${caminho})${0}", "imagem"], ["code", "```${linguagem}\n${0}\n```", "bloco de código"],
    ["tabela", "| ${coluna} | ${coluna2} |\n|---|---|\n| ${0} |  |", "tabela"], ["tarefa", "- [ ] ${0}", "item de tarefa"]],
  html: [["html5", "<!DOCTYPE html>\n<html lang=\"pt-BR\">\n<head>\n  <meta charset=\"utf-8\">\n  <title>${titulo}</title>\n</head>\n<body>\n  ${0}\n</body>\n</html>", "documento"],
    ["div", "<div class=\"${classe}\">${0}</div>", "bloco"], ["a", "<a href=\"${url}\">${0}</a>", "link"]],
  css: [["media", "@media (max-width: ${768}px) {\n  ${0}\n}", "media query"], ["flex", "display: flex;\nalign-items: center;\ngap: ${8}px;${0}", "flexbox"],
    ["grid", "display: grid;\ngrid-template-columns: ${repeat(3, 1fr)};\ngap: ${8}px;${0}", "grade"]],
  sql: [["sel", "SELECT ${colunas}\nFROM ${tabela}\nWHERE ${0};", "consulta"], ["ins", "INSERT INTO ${tabela} (${colunas})\nVALUES (${0});", "inserir"]],
  yaml: [["servico", "${nome}:\n  image: ${imagem}\n  ports:\n    - \"${8080}:${80}\"${0}", "serviço compose"]],
};
TRECHOS.typescript = TRECHOS.javascript;
const IDENT = /[A-Za-z_$\u00c0-\u024f][\w$\u00c0-\u024f]*/g;
let seq = 0;

/** Converte "${x}" em texto e devolve [texto, posicao do cursor] (o ${0} marca onde o cursor fica; senao, o 1o campo). */
export function expandirTrecho(modelo) {
  let cursor = -1, primeiro = -1, saida = "";
  let i = 0;
  const re = /\$\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(modelo))) {
    saida += modelo.slice(i, m.index);
    if (m[1] === "0") cursor = saida.length;
    else { if (primeiro < 0) primeiro = saida.length; saida += m[1]; }
    i = re.lastIndex;
  }
  saida += modelo.slice(i);
  return [saida, cursor >= 0 ? cursor : primeiro >= 0 ? primeiro : saida.length];
}

/**
 * area: textarea; opcoes: { linguagem: () => string, coordenadas: () => {x, y}, inserir(texto, apagarAntes, cursorRelativo) }
 */
export function criarCompletador(area, opcoes) {
  const id = `comp-${++seq}`;
  const lista = el("ul", { id, className: "completar", role: "listbox", "aria-label": "Sugestões", hidden: true });
  let itens = [], marcado = 0, prefixo = "";
  area.setAttribute("aria-autocomplete", "list");
  area.setAttribute("aria-controls", id);

  const palavraAtual = () => {
    const v = area.value, fim = area.selectionStart;
    let ini = fim;
    while (ini > 0 && /[\w$\u00c0-\u024f]/.test(v[ini - 1])) ini -= 1;
    return v.slice(ini, fim);
  };

  function candidatos(p) {
    const ling = opcoes.linguagem();
    const vistos = new Set();
    const saida = [];
    const add = (texto, tipo, detalhe, modelo = null) => {
      const chave = `${tipo}:${texto}`;
      if (vistos.has(chave) || texto === p) return;
      vistos.add(chave); saida.push({ texto, tipo, detalhe, modelo });
    };
    const pl = p.toLowerCase();
    for (const [nome, modelo, det] of TRECHOS[ling] || []) if (nome.startsWith(pl)) add(nome, "trecho", det, modelo);
    for (const k of palavrasChave(ling)) if (k.toLowerCase().startsWith(pl)) add(k, "palavra-chave", "");
    const contagem = new Map();
    for (const m of area.value.slice(0, 400_000).matchAll(IDENT)) if (m[0].length > 2) contagem.set(m[0], (contagem.get(m[0]) || 0) + 1);
    [...contagem.entries()].filter(([w]) => w.toLowerCase().startsWith(pl) && w !== p).sort((a, b) => b[1] - a[1]).slice(0, 40)
      .forEach(([w, n]) => add(w, "palavra", `${n}× no arquivo`));
    return saida.slice(0, 12);
  }

  function marcar() {
    [...lista.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === marcado)));
    const ativo = lista.children[marcado];
    if (ativo) { area.setAttribute("aria-activedescendant", ativo.id); ativo.scrollIntoView({ block: "nearest" }); }
  }

  function abrir(forcar = false) {
    prefixo = palavraAtual();
    if (!forcar && prefixo.length < 2) return fechar();
    itens = candidatos(prefixo);
    if (!itens.length) return fechar();
    marcado = 0;
    lista.replaceChildren(...itens.map((it, i) => el("li", { id: `${id}-${i}`, role: "option", className: `comp-${it.tipo}`,
      onpointerdown: (ev) => { ev.preventDefault(); marcado = i; aceitar(); } },
    el("span", { className: "comp-ico", "aria-hidden": "true", textContent: it.tipo === "trecho" ? "⧉" : it.tipo === "palavra-chave" ? "◆" : "abc" }),
    el("span", { className: "comp-texto", textContent: it.texto }), el("span", { className: "comp-det mudo", textContent: it.detalhe || it.tipo }))));
    const { x, y } = opcoes.coordenadas();
    lista.style.left = `${Math.max(0, x)}px`;
    lista.style.top = `${y}px`;
    lista.hidden = false;
    area.setAttribute("aria-expanded", "true");
    marcar();
  }

  function fechar() {
    lista.hidden = true;
    area.setAttribute("aria-expanded", "false");
    area.removeAttribute("aria-activedescendant");
  }

  function aceitar() {
    const it = itens[marcado];
    if (!it) return fechar();
    if (it.modelo) {
      const [texto, cursor] = expandirTrecho(it.modelo);
      opcoes.inserir(texto, prefixo.length, cursor);
    } else opcoes.inserir(it.texto, prefixo.length, it.texto.length);
    fechar();
  }

  let t = null;
  return {
    no: lista,
    aberto: () => !lista.hidden,
    abrir: () => abrir(true),
    fechar,
    aoDigitar: (ev) => {
      clearTimeout(t);
      if (ev.inputType && !ev.inputType.startsWith("insert")) { if (!lista.hidden) abrir(); return; }
      t = setTimeout(() => abrir(false), 90);
    },
    /** true se a tecla foi consumida pela lista */
    tecla: (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === " ") { ev.preventDefault(); abrir(true); return true; }
      if (lista.hidden) return false;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); marcado = (marcado + (ev.key === "ArrowDown" ? 1 : -1) + itens.length) % itens.length; marcar(); return true; }
      if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); aceitar(); return true; }
      if (ev.key === "Escape") { ev.preventDefault(); fechar(); return true; }
      return false;
    },
  };
}
