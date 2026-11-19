// Autocompletar do editor (ADR-027). Fontes, na ordem: servidor de linguagem (LSP, se instalado), catalogo de funcoes/metodos/
// bibliotecas/padroes por linguagem (Python, C#, JS/TS, HTML, CSS; ramos ligados pelos imports do arquivo), trechos prontos,
// palavras-chave e palavras do proprio arquivo. Entende o contexto: membro depois de "obj." (resolve apelidos como
// `import pandas as pd`), tag depois de "<", atributo dentro da tag, propriedade/valor/regra @ no CSS. Painel lateral explica o
// item marcado (assinatura e documentacao). Lista ARIA (listbox) ligada a textarea por aria-activedescendant. Tudo configuravel
// em Configuracoes > Editor (ligar/desligar, automatico, fontes, ramos, atraso, tamanho da lista).
import { catalogoDe, prefsEditor } from "./editorcfg.js";
import { palavrasChave } from "./realce.js";
import { el } from "./ui.js";

const TRECHOS = {
  markdown: [["link", "[${texto}](${url})${0}", "link"], ["img", "![${descricao}](${caminho})${0}", "imagem"], ["code", "```${linguagem}\n${0}\n```", "bloco de código"],
    ["tabela", "| ${coluna} | ${coluna2} |\n|---|---|\n| ${0} |  |", "tabela"], ["tarefa", "- [ ] ${0}", "item de tarefa"]],
  sql: [["sel", "SELECT ${colunas}\nFROM ${tabela}\nWHERE ${0};", "consulta"], ["ins", "INSERT INTO ${tabela} (${colunas})\nVALUES (${0});", "inserir"]],
  yaml: [["servico", "${nome}:\n  image: ${imagem}\n  ports:\n    - \"${8080}:${80}\"${0}", "serviço compose"]],
};
const CATALOGO = new Set(["python", "csharp", "javascript", "typescript", "html", "css"]);
const IDENT = /[A-Za-z_$\u00c0-\u024f][\w$\u00c0-\u024f]*/g;
const ICONES = { funcao: "ƒ", metodo: "ƒ", classe: "◇", modulo: "▣", propriedade: "▪", constante: "π", palavra: "abc", "palavra-chave": "◆",
  trecho: "⧉", tag: "<>", atributo: "=", valor: "·", arroba: "@" };
const ROTULO_TIPO = { funcao: "função", metodo: "método", classe: "classe", modulo: "módulo", propriedade: "propriedade", constante: "constante",
  palavra: "palavra", "palavra-chave": "palavra-chave", trecho: "trecho", tag: "elemento", atributo: "atributo", valor: "valor", arroba: "regra @" };
let seq = 0;

/** Converte "${x}" em texto e devolve [texto, posicao do cursor] (${0} marca o cursor; senao, o 1o campo). "$${" = "${" literal. */
export function expandirTrecho(modelo) {
  let cursor = -1, primeiro = -1, saida = "", i = 0, m;
  const re = /\$\$\{|\$\{([^}]*)\}/g;
  while ((m = re.exec(modelo))) {
    saida += modelo.slice(i, m.index);
    if (m[0] === "$${") saida += "${";
    else if (m[1] === "0") cursor = saida.length;
    else { if (primeiro < 0) primeiro = saida.length; saida += m[1]; }
    i = re.lastIndex;
  }
  saida += modelo.slice(i);
  return [saida, cursor >= 0 ? cursor : primeiro >= 0 ? primeiro : saida.length];
}

const caractereDe = (ling) => (ling === "css" || ling === "html" ? /[\w\-\u00c0-\u024f]/ : /[\w$\u00c0-\u024f]/);
const linguagemCatalogo = (ling) => (ling === "typescript" ? "javascript" : ling);

/** Contexto da posicao: {prefixo, ini, modo, alvo}. modo: livre | membro | tag | atributo | propriedade | valor | arroba */
export function contexto(texto, pos, linguagem) {
  const ling = linguagemCatalogo(linguagem);
  const ch = caractereDe(ling);
  let ini = pos;
  while (ini > 0 && ch.test(texto[ini - 1])) ini -= 1;
  const prefixo = texto.slice(ini, pos);
  const antes = texto.slice(Math.max(0, ini - 400), ini);
  if (ling === "python" || ling === "javascript" || ling === "csharp") {
    const m = antes.match(/([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\.$/);
    if (m) return { prefixo, ini, modo: "membro", alvo: m[1] };
    return { prefixo, ini, modo: "livre", alvo: null };
  }
  if (ling === "html") {
    if (antes.endsWith("<")) return { prefixo, ini, modo: "tag", alvo: null };
    const lt = texto.lastIndexOf("<", ini - 1), gt = texto.lastIndexOf(">", ini - 1);
    if (lt > gt && lt >= 0) {
      const tag = (texto.slice(lt + 1).match(/^([A-Za-z][\w-]*)/) || [])[1];
      const dentro = texto.slice(lt, ini);
      const aspas = (dentro.match(/"/g) || []).length % 2 === 1;
      if (tag && !aspas && /\s$/.test(antes)) return { prefixo, ini, modo: "atributo", alvo: tag.toLowerCase() };
    }
    return { prefixo, ini, modo: "livre", alvo: null };
  }
  if (ling === "css") {
    if (antes.endsWith("@")) return { prefixo, ini, modo: "arroba", alvo: null };
    const ab = texto.lastIndexOf("{", ini - 1), fe = texto.lastIndexOf("}", ini - 1);
    if (ab > fe) {
      const trecho = texto.slice(Math.max(ab, texto.lastIndexOf(";", ini - 1)) + 1, ini);
      const dois = trecho.indexOf(":");
      if (dois >= 0 && !/[{}]/.test(trecho)) return { prefixo, ini, modo: "valor", alvo: trecho.slice(0, dois).trim().toLowerCase() };
      if (!/[A-Za-z]\s+[A-Za-z]/.test(trecho.trim())) return { prefixo, ini, modo: "propriedade", alvo: null };
    }
    return { prefixo, ini, modo: "livre", alvo: null };
  }
  return { prefixo, ini, modo: "livre", alvo: null };
}

/** Apelidos do arquivo: nome local -> modulo (import pandas as pd; import fs from "node:fs"; const x = require("y")). */
export function apelidos(texto, linguagem) {
  const ling = linguagemCatalogo(linguagem), mapa = new Map();
  const t = texto.slice(0, 200_000);
  if (ling === "python") {
    for (const m of t.matchAll(/^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?/gm)) mapa.set(m[2] || m[1].split(".")[0], m[2] ? m[1] : m[1].split(".")[0]);
    for (const m of t.matchAll(/^\s*from\s+([\w.]+)\s+import\s+([^\n#]+)/gm)) {
      for (const parte of m[2].replace(/[()]/g, "").split(",")) {
        const [nome, , alias] = parte.trim().split(/\s+/);
        if (nome) mapa.set(alias || nome, `${m[1]}.${nome}`);
      }
    }
  } else if (ling === "javascript") {
    for (const m of t.matchAll(/import\s+(?:\*\s+as\s+)?(\w+)\s+from\s+["']([^"']+)["']/g)) mapa.set(m[1], m[2].replace(/^node:/, ""));
    for (const m of t.matchAll(/(?:const|let|var)\s+(\w+)\s*=\s*require\(\s*["']([^"']+)["']\s*\)/g)) mapa.set(m[1], m[2].replace(/^node:/, ""));
  }
  return mapa;
}

/** Pontuacao de casamento: 0 comeca com, 1 contem/segmento, 2 subsequencia; -1 nao casa. */
export function casar(texto, prefixo) {
  if (!prefixo) return 0;
  const t = texto.toLowerCase(), p = prefixo.toLowerCase();
  if (t.startsWith(p)) return 0;
  if (t.includes(p)) return 1;
  let j = 0;
  for (let i = 0; i < t.length && j < p.length; i++) if (t[i] === p[j]) j++;
  return j === p.length && p.length >= 2 ? 2 : -1;
}

function ramosAtivos(ramos, texto) {
  const amostra = texto.slice(0, 200_000);
  return ramos.filter((r) => !r.detectar.length || r.detectar.some((rx) => rx.test(amostra)));
}

/** Itens do catalogo que valem no contexto (sem filtrar pelo prefixo). */
export function itensDoCatalogo(ramos, texto, ctx, linguagem, comTrechos = true) {
  const ativos = ramosAtivos(ramos, texto);
  const alvos = new Set();
  if (ctx.modo === "membro" && ctx.alvo) {
    const mapa = apelidos(texto, linguagem);
    const a = ctx.alvo;
    [a, mapa.get(a), mapa.get(a.split(".")[0]), a.split(".").pop()].forEach((x) => x && alvos.add(x));
    for (const v of [...alvos]) { alvos.add(v.split(".")[0]); alvos.add(v.split(".").pop()); }
    for (const r of ativos) if (r.modulo && [...alvos].includes(r.modulo)) alvos.add(r.modulo);
  }
  const saida = [];
  for (const r of ativos) {
    for (const it of r.itens) {
      if (it.tipo === "trecho" && !comTrechos) continue;
      let rank = null;
      if (ctx.modo === "membro") {
        if (!it.apos.length) continue;
        if (it.apos.some((x) => alvos.has(x))) rank = 0;
        else if (it.apos.includes("*")) rank = 1;
      } else if (ctx.modo === "tag") { if (it.tipo === "tag") rank = 0; }
      else if (ctx.modo === "atributo") { if (it.tipo === "atributo") rank = it.apos.includes(ctx.alvo) ? 0 : it.apos.includes("*") ? 1 : null; }
      else if (ctx.modo === "valor") { if (it.tipo === "valor") rank = it.apos.includes(ctx.alvo) ? 0 : it.apos.includes("*") ? 1 : null; }
      else if (ctx.modo === "arroba") { if (it.tipo === "arroba") rank = 0; }
      else if (ctx.modo === "propriedade") { if (it.tipo === "propriedade" || it.tipo === "trecho") rank = it.tipo === "propriedade" ? 0 : 1; }
      else if (!it.apos.length && !["tag", "atributo", "valor", "arroba", "propriedade"].includes(it.tipo)) rank = 0;
      if (rank === null) continue;
      saida.push({ texto: it.rotulo, tipo: it.tipo, detalhe: it.assinatura, doc: it.doc, modelo: it.inserir || null, fonte: r.rotulo,
        revisado: it.revisado !== false, rank });
    }
  }
  return saida;
}

/** Explicacao do catalogo para uma palavra (dica ao parar o mouse quando nao ha LSP): {rotulo, assinatura, doc} ou null. */
export async function explicacaoDoCatalogo(linguagem, palavra, texto) {
  const ling = linguagemCatalogo(linguagem);
  if (!CATALOGO.has(ling) || !palavra || !prefsEditor().autocompletar_codigo) return null;
  const ramos = ramosAtivos(await catalogoDe(ling), texto);
  let achado = null;
  for (const r of ramos) {
    for (const it of r.itens) {
      if (it.rotulo !== palavra || it.tipo === "trecho" || !(it.doc || it.assinatura)) continue;
      if (!achado || (achado.apos.includes("*") && !it.apos.includes("*"))) achado = it;
    }
  }
  return achado;
}

/**
 * area: textarea; opcoes: { linguagem: () => string, coordenadas: () => {x, y}, inserir(texto, apagarAntes, cursorRelativo),
 *   lsp?: (gatilho) => Promise<{itens}|null> }
 */
export function criarCompletador(area, opcoes) {
  const id = `comp-${++seq}`;
  const lista = el("ul", { id, className: "completar-lista", role: "listbox", "aria-label": "Sugestões" });
  const detalhe = el("div", { className: "completar-doc", id: `${id}-doc`, "aria-hidden": "true" });
  const caixa = el("div", { className: "completar-caixa", hidden: true }, lista, detalhe);
  const anuncio = el("span", { className: "sr-only", role: "status", "aria-live": "polite" });
  caixa.append(anuncio);
  let itens = [], marcado = 0, ctxAtual = null, pedidoLsp = 0, catalogo = [], linguagemCarregada = null;
  area.setAttribute("aria-autocomplete", "list");
  area.setAttribute("aria-controls", id);

  async function carregarCatalogo() {
    const ling = linguagemCatalogo(opcoes.linguagem());
    if (ling === linguagemCarregada || !CATALOGO.has(ling)) return;
    linguagemCarregada = ling;
    catalogo = await catalogoDe(ling);
  }
  carregarCatalogo();

  function candidatos(ctx) {
    const ling = opcoes.linguagem(), p = prefsEditor(), fontes = new Set(p.autocompletar_fontes || []);
    const vistos = new Set(), saida = [];
    const add = (it, prioridade) => {
      const chave = it.texto;
      if (vistos.has(chave) || (it.texto === ctx.prefixo && !it.modelo)) return;
      const s = casar(it.filtro || it.texto, ctx.prefixo);
      if (s < 0) return;
      vistos.add(chave); saida.push({ ...it, ordem: s * 10 + (it.rank || 0) * 3 + prioridade });
    };
    if (fontes.has("catalogo") || fontes.has("trechos")) {
      for (const it of itensDoCatalogo(catalogo, area.value, ctx, ling, fontes.has("trechos"))) {
        if (it.tipo === "trecho" ? fontes.has("trechos") : fontes.has("catalogo")) add(it, it.tipo === "trecho" ? 2 : 1);
      }
    }
    if (ctx.modo === "livre") {
      if (fontes.has("trechos")) for (const [nome, modelo, det] of TRECHOS[ling] || []) add({ texto: nome, tipo: "trecho", detalhe: det, modelo }, 2);
      for (const k of palavrasChave(ling)) add({ texto: k, tipo: "palavra-chave", detalhe: "" }, 3);
    }
    if (fontes.has("palavras") && ctx.prefixo.length >= 1 && ["livre", "membro"].includes(ctx.modo)) {
      const contagem = new Map();
      for (const m of area.value.slice(0, 400_000).matchAll(IDENT)) if (m[0].length > 2) contagem.set(m[0], (contagem.get(m[0]) || 0) + 1);
      [...contagem.entries()].filter(([w]) => w !== ctx.prefixo && casar(w, ctx.prefixo) === 0).sort((a, b) => b[1] - a[1]).slice(0, 30)
        .forEach(([w, n]) => add({ texto: w, tipo: "palavra", detalhe: `${n}× no arquivo` }, 6));
    }
    return saida.sort((a, b) => a.ordem - b.ordem || a.texto.length - b.texto.length);
  }

  function mostrarDoc() {
    const it = itens[marcado];
    detalhe.replaceChildren();
    if (!it || (!it.detalhe && !it.doc)) { detalhe.hidden = true; return; }
    detalhe.hidden = false;
    if (it.detalhe) detalhe.append(el("code", { className: "completar-assinatura", textContent: it.detalhe }));
    if (it.doc) detalhe.append(el("p", { textContent: it.doc.replace(/[*_`#]/g, "").slice(0, 600) }));
    detalhe.append(el("p", { className: "mudo completar-fonte", textContent: `${ROTULO_TIPO[it.tipo] || it.tipo}${it.fonte ? ` · ${it.fonte}` : ""}${it.revisado === false ? " · sugerido pela IA (não revisado)" : ""}` }));
  }

  function marcar() {
    [...lista.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === marcado)));
    const ativo = lista.children[marcado];
    if (ativo) { area.setAttribute("aria-activedescendant", ativo.id); ativo.scrollIntoView({ block: "nearest" }); }
    mostrarDoc();
  }

  function desenhar() {
    const max = Math.max(3, Math.min(50, prefsEditor().autocompletar_max || 12));
    itens = itens.slice(0, max);
    if (!itens.length) return fechar();
    marcado = Math.min(marcado, itens.length - 1);
    lista.replaceChildren(...itens.map((it, i) => el("li", { id: `${id}-${i}`, role: "option", className: `comp-${it.tipo}${it.fonte === "LSP" ? " comp-lsp" : ""}`,
      onpointerdown: (ev) => { ev.preventDefault(); marcado = i; aceitar(); }, onpointermove: () => { if (marcado !== i) { marcado = i; marcar(); } } },
    el("span", { className: `comp-ico comp-ico-${it.tipo}`, "aria-hidden": "true", textContent: ICONES[it.tipo] || "·" }),
    el("span", { className: "comp-texto", textContent: it.texto }),
    el("span", { className: "comp-det mudo", textContent: it.fonte === "LSP" ? (it.detalhe || "").slice(0, 60) : (ROTULO_TIPO[it.tipo] || it.tipo) }))));
    const { x, y } = opcoes.coordenadas();
    caixa.style.left = `${Math.max(0, x)}px`;
    caixa.style.top = `${y}px`;
    const novo = caixa.hidden;
    caixa.hidden = false;
    if (novo) { caixa.classList.remove("entrando"); void caixa.offsetWidth; caixa.classList.add("entrando"); }
    area.setAttribute("aria-expanded", "true");
    anuncio.textContent = `${itens.length} sugest${itens.length === 1 ? "ão" : "ões"}`;
    marcar();
  }

  async function abrir(forcar = false, gatilho = "") {
    const p = prefsEditor();
    if (!p.autocompletar_codigo) return fechar();
    await carregarCatalogo();
    ctxAtual = contexto(area.value, area.selectionStart, opcoes.linguagem());
    const contextual = ctxAtual.modo !== "livre" && ctxAtual.modo !== "propriedade";
    if (!forcar && !contextual && ctxAtual.prefixo.length < 2) return fechar();
    itens = candidatos(ctxAtual);
    marcado = 0;
    if (itens.length) desenhar(); else if (!opcoes.lsp) return fechar();
    if (opcoes.lsp && ((p.autocompletar_fontes || []).includes("lsp"))) {
      const meu = ++pedidoLsp, pos = area.selectionStart, ctx = ctxAtual;
      const r = await opcoes.lsp(gatilho).catch(() => null);
      if (meu !== pedidoLsp || area.selectionStart !== pos || !r?.itens?.length) { if (!itens.length) fechar(); return; }
      const vistos = new Set();
      const doLsp = r.itens.filter((x) => casar(x.filtro || x.rotulo, ctx.prefixo) >= 0).map((x) => {
        vistos.add(x.rotulo);
        return { texto: x.rotulo, tipo: x.tipo, detalhe: x.assinatura, doc: x.doc, modelo: x.inserir && x.inserir !== x.rotulo ? x.inserir : null, fonte: "LSP",
          filtro: x.filtro, ordem: casar(x.filtro || x.rotulo, ctx.prefixo) * 10 };
      });
      const doCatalogo = new Map(itens.map((x) => [x.texto, x]));
      for (const x of doLsp) { const c = doCatalogo.get(x.texto); if (c && !x.doc) { x.doc = c.doc; x.detalhe ||= c.detalhe; } }
      itens = [...doLsp, ...itens.filter((x) => !vistos.has(x.texto))].sort((a, b) => a.ordem - b.ordem);
      desenhar();
    }
  }

  function fechar() {
    pedidoLsp++;
    caixa.hidden = true;
    area.setAttribute("aria-expanded", "false");
    area.removeAttribute("aria-activedescendant");
  }

  function aceitar() {
    const it = itens[marcado];
    if (!it || !ctxAtual) return fechar();
    const apagar = area.selectionStart - ctxAtual.ini;
    if (it.modelo) {
      const [texto, cursor] = expandirTrecho(it.modelo);
      opcoes.inserir(texto, apagar, cursor);
    } else opcoes.inserir(it.texto, apagar, it.texto.length);
    fechar();
  }

  let t = null;
  return {
    no: caixa,
    aberto: () => !caixa.hidden,
    abrir: () => abrir(true),
    fechar,
    aoDigitar: (ev) => {
      clearTimeout(t);
      const p = prefsEditor();
      if (!p.autocompletar_codigo) return;
      if (ev.inputType && !ev.inputType.startsWith("insert")) { if (!caixa.hidden) abrir(); return; }
      const ch = ev.data || "";
      const gatilho = [".", "<", "@", ":"].includes(ch) ? ch : "";
      if (!p.autocompletar_automatico && caixa.hidden) return;
      if (/[\s;(){}\[\],]/.test(ch) && !gatilho && ch !== " ") { fechar(); return; }
      t = setTimeout(() => abrir(false, gatilho), Math.max(0, Math.min(2000, p.autocompletar_atraso_ms ?? 120)));
    },
    /** true se a tecla foi consumida pela lista */
    tecla: (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === " ") { ev.preventDefault(); abrir(true); return true; }
      if (caixa.hidden) return false;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); marcado = (marcado + (ev.key === "ArrowDown" ? 1 : -1) + itens.length) % itens.length; marcar(); return true; }
      if (ev.key === "PageDown" || ev.key === "PageUp") { ev.preventDefault(); marcado = Math.max(0, Math.min(itens.length - 1, marcado + (ev.key === "PageDown" ? 5 : -5))); marcar(); return true; }
      if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); aceitar(); return true; }
      if (ev.key === "Escape") { ev.preventDefault(); fechar(); return true; }
      return false;
    },
  };
}
