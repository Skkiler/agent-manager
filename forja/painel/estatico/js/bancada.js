// Bancada (estilo VS Code/Kiro): abas do editor (arquivos, telas da Forja e boas-vindas), barra lateral por atividade,
// divisorias arrastaveis (mouse e teclado), trilha de navegacao e barra de status do arquivo aberto.
// Arquivos passam SEMPRE pela API da area de trabalho (/area/*): pastas do projeto, sem segredos, consulta somente leitura.
import { api, consulta } from "./api.js";
import { criarDiff } from "./diff.js";
import { criarEditor } from "./editor.js";
import { configEditor, lspLigado } from "./editorcfg.js";
import { agrupar, definirPainel, emitir, estado, ouvir, painelAberto, selecionarTarefa, tamanhoAtual, tamanhoPadrao, tamanhoPainel } from "./estado.js";
import { icone } from "./icones.js";
import { $, dialogo, el, limpar, toast } from "./ui.js";

const st = { atividades: [], abas: [], ativa: null, lateral: null, projetos: new Map() };
const vista = () => $("#vista");
const MAX_ABAS = 20;

// ------------------------------------------------------------------ persistencia das abas (so referencias; o conteudo vem do disco)
function salvarAbas() {
  const leves = st.abas.filter((a) => a.tipo !== "texto" && a.tipo !== "diff").map(({ chave, tipo, id, projeto, raiz, rel, nome, titulo }) => ({ chave, tipo, id, projeto, raiz, rel, nome, titulo }));
  localStorage.setItem("forja_abas", JSON.stringify({ abas: leves, ativa: st.ativa }));
}
function lerAbas() { try { return JSON.parse(localStorage.getItem("forja_abas") || "{}"); } catch { return {}; } }

function lembrarRecente(a) {
  let r = []; try { r = JSON.parse(localStorage.getItem("forja_recentes") || "[]"); } catch { r = []; }
  r = [{ projeto: a.projeto, raiz: a.raiz, rel: a.rel, nome: a.nome }, ...r.filter((x) => !(x.projeto === a.projeto && x.raiz === a.raiz && x.rel === a.rel))].slice(0, 10);
  localStorage.setItem("forja_recentes", JSON.stringify(r));
}
export function recentes() { try { return JSON.parse(localStorage.getItem("forja_recentes") || "[]"); } catch { return []; } }

export async function projeto(id) {
  if (!st.projetos.has(id)) st.projetos.set(id, api("GET", `/projetos/${id}`).catch(() => null));
  return st.projetos.get(id);
}
ouvir("projetos-mudaram", () => st.projetos.clear());

// ------------------------------------------------------------------ faixa de abas
const abaPor = (chave) => st.abas.find((a) => a.chave === chave);
const extensao = (a) => (a.tipo === "arquivo" ? ((a.nome || "").toLowerCase().match(/\.([a-z0-9]+)$/) || [, a.nome?.startsWith(".env") ? "env" : "txt"])[1] : a.tipo);

function desenharAbas() {
  const ul = $("#editor-abas");
  limpar(ul);
  for (const a of st.abas) {
    const ativa = a.chave === st.ativa;
    const sujo = a.editor?.sujo();
    const li = el("li", { className: `aba-editor${ativa ? " ativa" : ""}${sujo ? " suja" : ""}`, dataset: { chave: a.chave } },
      el("button", { type: "button", className: "aba-rotulo", "aria-current": ativa ? "page" : "false", title: a.rel ? `${a.rel}${a.somente_leitura ? " (somente leitura)" : ""}` : a.titulo,
        onclick: () => ativar(a.chave), onauxclick: (ev) => { if (ev.button === 1) fechar(a.chave); } },
      el("span", { className: `ico-aba ext-${extensao(a)}`, "aria-hidden": "true" }, icone(a.tipo === "diff" ? "git" : a.tipo === "arquivo" || a.tipo === "texto" ? (a.segredo ? "cadeado" : "arquivo") : a.icone || "inicio", 14)),
      el("span", { className: "trunc", textContent: a.titulo })),
      el("button", { type: "button", className: "aba-fechar", "aria-label": `Fechar ${a.titulo}${sujo ? " (não salvo)" : ""}`, title: "Fechar (Ctrl+W)",
        textContent: sujo ? "●" : "✕", onclick: () => fechar(a.chave) }));
    ul.append(li);
  }
  ul.querySelector(".ativa")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function trilha(a) {
  const t = $("#trilha");
  limpar(t);
  if (!a) return;
  const partes = a.tipo === "arquivo" ? [a.projetoNome || a.projeto, ...(a.pastaNome ? [a.pastaNome] : []), ...a.rel.split("/")]
    : a.tipo === "texto" ? ["Forja", a.titulo] : ["Forja", a.titulo];
  t.append(el("ol", {}, ...partes.map((p, i) => el("li", { "aria-current": i === partes.length - 1 ? "location" : undefined, textContent: p }))));
}

function status(a) {
  $("#st-linguagem").textContent = a?.editor ? a.editor.linguagem() : "";
  if (!a?.editor) $("#st-cursor").textContent = "";
  const p = a?.problemas || [];
  const erros = p.filter((x) => x.gravidade === "erro").length;
  $("#st-problemas").textContent = `⊗ ${erros} ⚠ ${p.length - erros}`;
  $("#st-problemas").setAttribute("aria-label", `${erros} erro(s) e ${p.length - erros} aviso(s) no arquivo aberto`);
  if (a?.tipo === "arquivo") atualizarGit(a); else $("#st-git").hidden = true;
}

const atualizarGit = (() => {
  let ultimo = "";
  return async (a) => {
    const chave = `${a.projeto}:${a.raiz}`;
    if (chave === ultimo && !$("#st-git").hidden) return;
    ultimo = chave;
    try {
      const r = await api("GET", `/area/git?${consulta({ projeto: a.projeto, raiz: a.raiz })}`);
      const b = $("#st-git");
      if (r.dados.repositorio === false) { b.hidden = true; return; }
      b.hidden = false; b.textContent = `⑂ ${(r.dados.branch || "").split("...")[0] || "?"}${r.dados.alterados?.length ? ` · ${r.dados.alterados.length}` : ""}`;
      b.title = `Git: ${r.dados.alterados?.length || 0} arquivo(s) alterado(s). Clique para abrir o controle de código.`;
    } catch { $("#st-git").hidden = true; }
  };
})();

// ------------------------------------------------------------------ ativar / fechar
export function ativar(chave) {
  const a = abaPor(chave);
  if (!a) return;
  if (st.ativa === chave && vista().dataset.chave === chave && estado.modo === "editor") return; // ja montada: nao monta de novo (2 montagens async duplicavam a tela)
  st.ativa = chave;
  desenharAbas(); salvarAbas(); trilha(a); status(a);
  if (estado.modo === "agentes") return; // a oficina ocupa a area; a aba volta quando o modo editor voltar
  montarAba(a);
  emitir("aba", a);
}

async function montarAba(a) {
  const v = vista();
  v.dataset.tipo = a.tipo;
  v.dataset.chave = a.chave;
  $("#principal").setAttribute("aria-label", a.titulo);
  if (a.tipo === "vista") {
    const at = st.atividades.find((x) => x.id === a.id);
    at?.modulo.montar(v);
    return;
  }
  if (a.tipo === "inicio") { limpar(v); v.append(boasVindas()); return; }
  if (a.tipo === "diff") {
    limpar(v); v.append(el("p", { className: "mudo carregando", textContent: `Comparando ${a.rel}…` }));
    try {
      const consultaDiff = { projeto: a.projeto, raiz: a.raiz, rel: a.rel };
      const [antes, depois] = await Promise.all([
        api("GET", `/area/git/versao?${consulta({ ...consultaDiff, versao: a.versao || "HEAD" })}`),
        a.versaoDireita ? api("GET", `/area/git/versao?${consulta({ ...consultaDiff, versao: a.versaoDireita })}`)
          : api("GET", `/area/arquivo?${consulta(consultaDiff)}`).catch(() => ({ conteudo: "" }))]);
      const rotulos = [`${a.versao === "index" ? "Preparado (index)" : a.versao || "HEAD"}${antes.existe ? "" : " (novo)"}`, a.versaoDireita === "index" ? "Preparado (index)" : "Pasta de trabalho"];
      const d = criarDiff(antes.conteudo, depois.conteudo, { rotulos, titulo: a.rel });
      limpar(v); v.append(d.no); d.proxima();
    } catch (e) { limpar(v); v.append(el("div", { className: "aviso", role: "alert", textContent: `Não foi possível comparar: ${e.message}` })); }
    return;
  }
  if (a.tipo === "texto") {
    a.editor ||= criarEditor({ texto: a.texto, linguagem: a.linguagem, somenteLeitura: true, rotulo: a.titulo, aoCursor: cursor });
    limpar(v); v.append(a.editor.no); return;
  }
  if (!a.editor) {
    limpar(v); v.append(el("p", { className: "mudo carregando", textContent: `Abrindo ${a.rel}…` }));
    try {
      const [r, p] = await Promise.all([api("GET", `/area/arquivo?${consulta({ projeto: a.projeto, raiz: a.raiz, rel: a.rel })}`), projeto(a.projeto),
        configEditor()]);
      a.sha = r.sha; a.crlf = r.fim_de_linha === "crlf"; a.somente_leitura = r.somente_leitura; a.segredo = r.segredo; a.projetoNome = p?.nome; a.pastaNome = (p?.pastas?.[a.raiz]?.caminho || "").split(/[\\/]/).pop();
      a.editor = criarEditor({ texto: r.conteudo, linguagem: r.linguagem, somenteLeitura: r.somente_leitura, rotulo: `Editor: ${a.rel}`,
        aoSalvar: (texto) => salvarArquivo(a, texto), aoMudar: () => desenharAbas(), aoCursor: cursor, aoDefinicao: (nome) => irDefinicao(a, nome),
        lsp: (acao, corpo) => api("POST", `/area/lsp/${acao}`, { projeto: a.projeto, raiz: a.raiz, rel: a.rel, ...corpo }),
        aoDefinicaoLsp: (nome, defs) => irDefinicaoLsp(a, nome, defs),
        aoAlterarTexto: agrupar(() => verificarProblemas(a, a.editor.valor()), 1200) });
      lembrarRecente(a);
      verificarProblemas(a);
    } catch (e) {
      limpar(v); v.append(el("div", { className: "aviso", role: "alert", textContent: `Não foi possível abrir ${a.rel}: ${e.message}` }));
      return;
    }
    if (st.ativa !== a.chave) return;
    trilha(a); status(a);
  }
  limpar(v);
  if (a.segredo) v.append(el("div", { className: "faixa-segredo", role: "note" }, icone("cadeado", 14),
    el("span", { textContent: "Arquivo de segredo: aparece só para você. A Forja nunca o envia ao Kiro/Codex nem o registra em log." })));
  v.append(a.editor.no);
  if (a.linha) { a.editor.irPara(a.linha); a.linha = null; } else a.editor.focar();
}

function cursor(l, c) { $("#st-cursor").textContent = `Ln ${l}, Col ${c}`; }

async function irDefinicao(a, nome) {
  try {
    const r = await api("GET", `/area/definicao?${consulta({ projeto: a.projeto, raiz: a.raiz, nome })}`);
    const defs = r.definicoes || [];
    if (!defs.length) return toast(`Definição de "${nome}" não encontrada (Python, JS e TS são indexados).`);
    if (defs.length === 1) return abrirArquivo({ projeto: a.projeto, raiz: a.raiz, rel: defs[0].caminho, linha: defs[0].linha });
    const d = dialogo(`Definições de ${nome}`, el("ul", { className: "lista-definicoes" }, ...defs.map((x) => el("li", {},
      el("button", { type: "button", className: "bloco", onclick: () => { d.fechar(); abrirArquivo({ projeto: a.projeto, raiz: a.raiz, rel: x.caminho, linha: x.linha }); } },
        el("span", { className: "trunc", textContent: `${x.nome} (${x.tipo})` }), el("span", { className: "mudo", textContent: `${x.caminho}:${x.linha}` }))))));
  } catch (e) { toast(e.message, "erro"); }
}

/** F12 pelo servidor de linguagem: definicoes dentro do projeto abrem; fora dele (biblioteca instalada) so sao mostradas. */
function irDefinicaoLsp(a, nome, defs) {
  const dentro = defs.filter((d) => !d.externo);
  if (dentro.length === 1 && defs.length === 1) return abrirArquivo({ projeto: a.projeto, raiz: a.raiz, rel: dentro[0].rel, linha: dentro[0].linha });
  if (!dentro.length) return toast(`"${nome}" é definido fora do projeto (${defs[0].nome}:${defs[0].linha}), em uma biblioteca instalada.`);
  const d = dialogo(`Definições de ${nome}`, el("ul", { className: "lista-definicoes" }, ...defs.map((x) => el("li", {},
    x.externo ? el("span", { className: "bloco mudo", textContent: `${x.nome}:${x.linha} (fora do projeto)` })
      : el("button", { type: "button", className: "bloco", onclick: () => { d.fechar(); abrirArquivo({ projeto: a.projeto, raiz: a.raiz, rel: x.rel, linha: x.linha }); } },
        el("span", { className: "trunc", textContent: x.rel }), el("span", { className: "mudo", textContent: `linha ${x.linha}` }))))));
}

/** Simbolos do arquivo da aba ativa (para a paleta: @). */
export async function simbolosDaAba() {
  const a = abaAtiva();
  if (a?.tipo !== "arquivo") return [];
  try { return (await api("GET", `/area/simbolos?${consulta({ projeto: a.projeto, raiz: a.raiz, rel: a.rel })}`)).simbolos; } catch { return []; }
}

async function salvarArquivo(a, texto) {
  try {
    const conteudo = a.crlf ? texto.replace(/\r?\n/g, "\r\n") : texto; // mantem o fim de linha original do arquivo
    const r = await api("PUT", "/area/arquivo", { projeto: a.projeto, raiz: a.raiz, rel: a.rel, conteudo, sha: a.sha });
    a.sha = r.sha; toast(`Salvo: ${a.nome}`, "ok");
    a.editor.marcarSalvo(texto); desenharAbas(); verificarProblemas(a);
    emitir("arquivo-salvo", a);
    return true;
  } catch (e) {
    if (e.status === 409 && confirm(`${e.message}\n\nRecarregar do disco? Suas alterações não salvas serão perdidas.`)) {
      const r = await api("GET", `/area/arquivo?${consulta({ projeto: a.projeto, raiz: a.raiz, rel: a.rel })}`);
      a.sha = r.sha; a.editor.definirTexto(r.conteudo); desenharAbas();
    } else toast(e.message, "erro");
    return false;
  }
}

async function verificarProblemas(a, conteudo) {
  try {
    const minha = (a.geracaoProblemas = (a.geracaoProblemas || 0) + 1);
    const r = await api("POST", "/area/problemas", { projeto: a.projeto, raiz: a.raiz, rel: a.rel, ...(conteudo !== undefined ? { conteudo } : {}) });
    const publicar = (itens) => {
      if (minha !== a.geracaoProblemas) return;
      a.problemas = itens;
      a.editor?.marcarProblemas(itens);
      if (st.ativa === a.chave) status(a);
      emitir("problemas", { aba: a.chave, titulo: a.rel, itens });
    };
    publicar(r.problemas);
    if (a.editor && lspLigado(a.editor.linguagem())) {  // erros do compilador/analisador do servidor de linguagem, sem travar a tela
      const texto = conteudo !== undefined ? conteudo : a.editor.valor();
      const d = await api("POST", "/area/lsp/diagnosticos", { projeto: a.projeto, raiz: a.raiz, rel: a.rel, texto }).catch(() => null);
      if (d?.problemas?.length) {
        const vistos = new Set(r.problemas.map((p) => `${p.linha}|${p.mensagem}`));
        publicar([...r.problemas, ...d.problemas.filter((p) => !vistos.has(`${p.linha}|${p.mensagem}`))]);
      }
    }
  } catch { /* diagnostico e conveniencia */ }
}

export function fechar(chave) {
  const i = st.abas.findIndex((a) => a.chave === chave);
  if (i < 0) return;
  const a = st.abas[i];
  if (a.editor?.sujo() && !confirm(`${a.titulo} tem alterações não salvas. Fechar mesmo assim?`)) return;
  st.abas.splice(i, 1);
  if (a.problemas) emitir("problemas", { aba: a.chave, titulo: a.rel, itens: [] });
  if (st.ativa === chave) {
    const prox = st.abas[i] || st.abas[i - 1];
    st.ativa = prox?.chave || null;
    if (prox) ativar(prox.chave); else { abrirInicio(); return; }
  }
  desenharAbas(); salvarAbas();
}

function adicionar(a, ativa = true) {
  if (!abaPor(a.chave)) {
    st.abas.push(a);
    while (st.abas.length > MAX_ABAS) { const velha = st.abas.find((x) => x.chave !== a.chave && !x.editor?.sujo()); if (!velha) break; st.abas.splice(st.abas.indexOf(velha), 1); }
  }
  if (ativa) ativar(a.chave); else desenharAbas();
  return abaPor(a.chave);
}

// ------------------------------------------------------------------ API publica das abas
export function abrirInicio() { return adicionar({ chave: "inicio", tipo: "inicio", titulo: "Boas-vindas", icone: "inicio" }); }

export function abrirVista(id) {
  const at = st.atividades.find((x) => x.id === id);
  if (!at) return null;
  return adicionar({ chave: `vista:${id}`, tipo: "vista", id, titulo: at.rotulo, icone: at.icone });
}

export function abrirArquivo({ projeto: p, raiz = 0, rel, nome, linha = null }) {
  const chave = `arq:${p}:${raiz}:${rel}`;
  const ex = abaPor(chave);
  if (ex) { if (linha) { if (ex.editor) { ativar(chave); ex.editor.irPara(linha); return ex; } ex.linha = linha; } ativar(chave); return ex; }
  return adicionar({ chave, tipo: "arquivo", projeto: p, raiz, rel, nome: nome || rel.split("/").pop(), titulo: nome || rel.split("/").pop(), linha });
}

/** Revisao lado a lado: versao do Git (HEAD, index ou commit) x pasta de trabalho (ou x outra versao). */
export function abrirDiff({ projeto: p, raiz = 0, rel, versao = "HEAD", versaoDireita = "" }) {
  const chave = `diff:${p}:${raiz}:${rel}:${versao}:${versaoDireita}`;
  const ex = abaPor(chave);
  if (ex) { ativar(chave); montarAba(ex); return ex; }
  return adicionar({ chave, tipo: "diff", projeto: p, raiz, rel, versao, versaoDireita, titulo: `${rel.split("/").pop()} ↔ ${versao === "index" ? "index" : versao}` });
}

/** Texto somente leitura numa aba (logs do Docker, saida de comandos). */
export function abrirTexto(titulo, texto, linguagem = "texto") {
  const chave = `txt:${titulo}`;
  const ex = abaPor(chave);
  if (ex) { ex.texto = texto; ex.editor = null; ativar(chave); return ex; }
  return adicionar({ chave, tipo: "texto", titulo, texto, linguagem });
}

export const abaAtiva = () => abaPor(st.ativa);
export const abas = () => [...st.abas];
export const temAlteracoes = () => st.abas.some((a) => a.editor?.sujo());
export function reexibir() { const a = abaAtiva(); if (a) montarAba(a); else abrirInicio(); }

// ------------------------------------------------------------------ boas-vindas (estilo VS Code)
let ultimoQuadro = null;
ouvir("kanban", (q) => { ultimoQuadro = q; if (abaAtiva()?.tipo === "inicio" && estado.modo === "editor") reexibir(); });

function boasVindas() {
  const atalho = (rotulo, teclas, acao) => el("li", {}, el("button", { type: "button", className: "link", onclick: acao, textContent: rotulo }),
    el("kbd", { textContent: teclas }));
  const precisa = (ultimoQuadro?.colunas || []).flatMap((c) => c.cartoes).filter((c) => c.precisa_de_voce).slice(0, 6);
  const rec = recentes();
  return el("div", { className: "boas-vindas" },
    el("div", { className: "bv-marca" }, el("img", { src: "/estatico/logo.svg", alt: "Forja", width: 120, height: 150 }),
      el("div", {}, el("h1", { textContent: "Forja" }), el("p", { className: "mudo", textContent: "Orquestrador local de agentes Kiro e Codex. Tudo roda no seu computador." }))),
    el("div", { className: "bv-grade" },
      el("section", { "aria-labelledby": "bv-precisa" }, el("h2", { id: "bv-precisa", textContent: "Precisa de você" }),
        precisa.length ? el("ul", { className: "bv-lista" }, ...precisa.map((c) => el("li", {}, el("button", { type: "button", className: "link",
          onclick: () => { selecionarTarefa(c.id); emitir("abrir-direita", c.estado === "aguardando_aprovacao" ? "decisoes" : "conversa"); },
          textContent: c.titulo })))) : el("p", { className: "mudo", textContent: "Nada esperando por você agora." })),
      el("section", { "aria-labelledby": "bv-comecar" }, el("h2", { id: "bv-comecar", textContent: "Começar" }),
        el("ul", { className: "bv-atalhos" },
          atalho("Novo pedido ao master", "Ctrl+Alt+2", () => emitir("modo-pedido", "chat")),
          atalho("Abrir arquivo…", "Ctrl+P", () => emitir("paleta", "")),
          atalho("Mostrar todos os comandos", "Ctrl+Shift+P", () => emitir("paleta", ">")),
          atalho("Buscar nos arquivos", "Ctrl+Shift+F", () => emitir("atividade", "busca")),
          atalho("Abrir o chat", "Ctrl+Alt+I", () => definirPainel("direita", true)),
          atalho("Abrir o terminal", "Ctrl+`", () => emitir("inferior", "terminal")),
          atalho("Configurações", "Ctrl+,", () => emitir("ir", "config")))),
      el("section", { "aria-labelledby": "bv-dica" }, el("h2", { id: "bv-dica", textContent: "Dica" }), dicaDoDia()),
      el("section", { "aria-labelledby": "bv-recentes" }, el("h2", { id: "bv-recentes", textContent: "Recentes" }),
        rec.length ? el("ul", { className: "bv-lista" }, ...rec.map((r) => el("li", {}, el("button", { type: "button", className: "link", title: r.rel,
          onclick: () => abrirArquivo(r), textContent: r.nome }), el("span", { className: "mudo trunc", textContent: r.rel }))))
          : el("p", { className: "mudo", textContent: "Abra um arquivo pelo Explorador (barra à esquerda) ou com Ctrl+P." }))));
}

const DICAS = [
  ["No terminal, comece a digitar: o assistente explica cada parte, mostra a sintaxe e completa com Tab.", "Abrir o terminal", () => emitir("inferior", "terminal")],
  ["Receitas guiam processos inteiros (ex.: vincular a pasta ao GitHub e enviar) com variáveis que você preenche.", "Ver receitas", () => emitir("receitas", "")],
  ["Clique num arquivo alterado no Git para revisar as diferenças lado a lado antes do commit.", "Abrir o Git", () => emitir("atividade", "git")],
  ["Teste APIs sem sair da Forja em Requisições HTTP: coleções, variáveis {{nome}} e \"copiar como curl\".", "Abrir Requisições", () => emitir("ir", "http")],
  ["F12 (ou Ctrl+clique) leva à definição de uma função; Ctrl+Shift+O lista os símbolos do arquivo.", "Ver atalhos", () => emitir("paleta", ">atalhos")],
  ["Defina um teto diário de créditos em Configurações > Consumo: a Forja para de iniciar execuções quando ele é atingido.", "Configurações", () => emitir("ir", "config")],
  ["No modo Agentes, cada execução real aparece como um personagem: clique para abrir a conversa.", "Ver agentes", () => emitir("ir", "agentes")],
];
function dicaDoDia() {
  let i = new Date().getDate() % DICAS.length;
  const texto = el("p"), botao = el("button", { type: "button", className: "link" });
  const mostrar = () => { const [t, rotulo, acao] = DICAS[i]; texto.textContent = t; botao.textContent = `${rotulo} →`; botao.onclick = acao; };
  mostrar();
  return el("div", { className: "dica-dia" }, icone("lampada", 18), el("div", {}, texto, el("div", { className: "linha" }, botao,
    el("button", { type: "button", className: "pequeno", textContent: "Próxima dica", onclick: () => { i = (i + 1) % DICAS.length; mostrar(); } }))));
}

// ------------------------------------------------------------------ barra lateral
export function mostrarLateral(id, { abrir = true } = {}) {
  const at = st.atividades.find((x) => x.id === id);
  if (!at) return;
  const corpo = $("#lateral-corpo"), acoes = $("#lateral-acoes");
  const montar = at.montarLateral || at.modulo?.montarLateral;
  if (!montar) return;
  st.lateral = id;
  // conteudo novo a cada troca: um desenho assincrono antigo (ex.: o Explorador ainda carregando) cai num no solto, sem apagar este
  const alvo = el("div", { className: "lateral-conteudo" }), botoes = el("span", { className: "linha" });
  corpo.replaceChildren(alvo); acoes.replaceChildren(botoes);
  $("#lateral-titulo").textContent = at.rotulo;
  montar(alvo, botoes);
  marcarAtividade();
  if (abrir) definirPainel("lateral", true);
}
export const lateralAtual = () => st.lateral;

export function marcarAtividade() {
  const aba = abaAtiva();
  for (const b of document.querySelectorAll("#atividades button[data-id]")) {
    const id = b.dataset.id;
    const atual = estado.modo === "editor" && ((painelAberto("lateral") && st.lateral === id) || (aba?.tipo === "vista" && aba.id === id));
    b.setAttribute("aria-current", atual ? "page" : "false");
  }
}
ouvir("painel", marcarAtividade);
ouvir("aba", marcarAtividade);

// ------------------------------------------------------------------ divisorias (arrastar ou setas; duplo clique restaura)
function divisoria(nome, orientacao) {
  const painel = $(`#${nome}`);
  const d = el("div", { className: `divisor divisor-${nome}`, role: "separator", tabIndex: 0, "aria-orientation": orientacao,
    "aria-label": `Redimensionar ${nome === "lateral" ? "barra lateral" : nome === "direita" ? "conversa" : "painel inferior"}`,
    "aria-valuemin": "120", "aria-valuemax": "900", "aria-valuenow": String(tamanhoAtual(nome)), title: "Arraste para redimensionar · duplo clique restaura" });
  const medir = (ev) => {
    const r = painel.getBoundingClientRect();
    return nome === "lateral" ? ev.clientX - r.left : nome === "direita" ? r.right - ev.clientX : r.bottom - ev.clientY;
  };
  const aplicar = (px, salvar = true) => { const v = tamanhoPainel(nome, px, { salvar }); d.setAttribute("aria-valuenow", String(v)); };
  d.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault(); d.setPointerCapture(ev.pointerId); document.body.classList.add("redimensionando");
    const mover = (e) => aplicar(medir(e), false);
    const soltar = (e) => { aplicar(medir(e)); d.removeEventListener("pointermove", mover); document.body.classList.remove("redimensionando"); };
    d.addEventListener("pointermove", mover);
    d.addEventListener("pointerup", soltar, { once: true }); d.addEventListener("pointercancel", soltar, { once: true });
  });
  d.addEventListener("dblclick", () => aplicar(tamanhoPadrao(nome)));
  d.addEventListener("keydown", (ev) => {
    const mais = nome === "lateral" ? "ArrowRight" : nome === "direita" ? "ArrowLeft" : "ArrowUp";
    const menos = nome === "lateral" ? "ArrowLeft" : nome === "direita" ? "ArrowRight" : "ArrowDown";
    if (ev.key === mais || ev.key === menos) { ev.preventDefault(); aplicar(tamanhoAtual(nome) + (ev.key === mais ? 24 : -24)); }
    if (ev.key === "Home" || ev.key === "Enter") { ev.preventDefault(); aplicar(tamanhoPadrao(nome)); }
  });
  painel.append(d);
}

// ------------------------------------------------------------------ inicio
export function iniciarBancada(atividades) {
  st.atividades = atividades;
  for (const n of ["lateral", "direita", "inferior"]) { tamanhoPainel(n, undefined, { salvar: false }); divisoria(n, n === "inferior" ? "horizontal" : "vertical"); }
  $("#alternar-lateral").append(icone("painel_lateral", 16));
  $("#alternar-inferior").append(icone("painel_inferior", 16));
  $("#alternar-direita").append(icone("painel_direito", 16));
  $("#st-problemas").addEventListener("click", () => emitir("inferior", "problemas"));
  $("#st-git").addEventListener("click", () => emitir("atividade", "git"));
  addEventListener("beforeunload", (ev) => { if (temAlteracoes()) ev.preventDefault(); });
  const salvo = lerAbas();
  for (const a of salvo.abas || []) if (a.tipo === "arquivo" || (a.tipo === "vista" && atividades.some((x) => x.id === a.id)) || a.tipo === "inicio") st.abas.push({ ...a });
  return salvo.ativa;
}
