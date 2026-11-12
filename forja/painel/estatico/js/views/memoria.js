// Segundo cerebro: grafo (estilo Obsidian), busca, leitura e edicao de notas com [[wikilinks]] e backlinks.
import { api } from "../api.js";
import { agrupar, emitir, ouvir, selecionarTarefa } from "../estado.js";
import { desenhar } from "../grafo.js";
import { renderizar } from "../markdown.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";
import { abrirRotulagem } from "./rotulagem.js";

const NAMESPACES = ["publico", "pessoal"];
const sel = { namespaces: new Set(["publico"]), q: "", inativas: false, base: false, vizinhos: 1, nota: null, editando: false };
let ctx = {};
let grafoAtual = { nos: [], arestas: [] };

const chaveTitulo = () => new Map(grafoAtual.nos.filter((n) => n.grupo === "memoria").map((n) => [n.rotulo.toLowerCase(), n]));

async function carregarGrafo() {
  if (!ctx.caixa) return;
  try {
    const params = new URLSearchParams();
    for (const ns of sel.namespaces) params.append("namespace", ns);
    if (sel.q) params.set("q", sel.q);
    params.set("vizinhos", String(sel.vizinhos));
    if (sel.inativas) params.set("incluir_inativas", "true");
    if (sel.base) params.set("incluir_base", "true");
    grafoAtual = await api("GET", `/conhecimento/grafo?${params}`);
    ctx.resumo.textContent = `${grafoAtual.nos.length} nos · ${grafoAtual.arestas.length} ligacoes` + (grafoAtual.truncado ? " (truncado)" : "")
      + (grafoAtual.fantasmas ? ` · ${grafoAtual.fantasmas} link(s) sem nota` : "");
    ctx.vazio.hidden = grafoAtual.nos.length > 0;
    desenhar(ctx.caixa, grafoAtual, { aoSelecionar: abrirNo, selecionado: sel.nota?.id, aoLigar: (o, d) => dialogoLigar(o, d) });
    listaNotas();
  } catch (e) { ctx.resumo.textContent = `Erro: ${e.message}`; }
}

function listaNotas() {
  limpar(ctx.lista);
  const ordenados = [...grafoAtual.nos].sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR"));
  ctx.lista.append(...ordenados.map((n) => el("li", {}, el("button", { type: "button", textContent: `${n.grupo === "fantasma" ? "○ " : ""}${n.rotulo}`,
    "aria-current": String(n.id === sel.nota?.id), onclick: () => abrirNo(n) }))));
}

async function abrirNo(n) {
  if (n.grupo === "fantasma") return criarNota(n.rotulo);
  if (n.grupo !== "memoria") return toast(`No tipado "${n.rotulo}" (${n.tipo}): sem texto para editar.`);
  try {
    const [m, links] = await Promise.all([api("GET", `/memorias/${n.id}`), api("GET", `/memorias/${n.id}/links`)]);
    sel.nota = { ...m, links }; sel.editando = false;
    renderNota(); await carregarGrafo();
  } catch (e) { toast(e.message, "erro"); }
}

function renderNota() {
  const n = sel.nota;
  ctx.raiz.classList.toggle("sem-nota", !n);
  limpar(ctx.nota);
  ctx.nota.hidden = !n;
  if (!n) return;
  const existe = (t) => chaveTitulo().has(t.toLowerCase());
  const aoWikilink = (t, ok) => (ok ? abrirNo(chaveTitulo().get(t.toLowerCase())) : criarNota(t));
  const corpo = sel.editando ? editor(n) : renderizar(n.conteudo || n.resumo, { aoWikilink, existe });
  const back = (n.links?.entrada || []).map((l) => el("li", {}, el("button", { type: "button", className: "wikilink", textContent: l.titulo, onclick: () => aoWikilink(l.titulo, true) })));
  ctx.nota.append(
    el("div", { className: "linha" }, el("h1", { textContent: n.titulo }), el("span", { className: "espaco" }),
      String(n.namespace || "").startsWith("publico/forja-base") ? tag("base da Forja (somente leitura)")
        : el("button", { type: "button", textContent: sel.editando ? "Ler" : "Editar", onclick: () => { sel.editando = !sel.editando; renderNota(); } }),
      el("button", { type: "button", textContent: "Fechar", onclick: () => { sel.nota = null; renderNota(); carregarGrafo(); } })),
    el("div", { className: "linha" }, tag(n.tipo), tag(n.estado, n.estado === "validado" ? "ok" : ""), tag(`v${n.versao}`, "so-avancado"), tag(n.namespace),
      ...(n.sinalizadores?.suspeita_injecao?.length ? [tag("possivel prompt injection", "erro")] : []),
      n.necessita_revalidacao ? tag("origem mudou: revalidar", "aviso") : null),
    corpo,
    el("h2", { textContent: `Backlinks (${back.length})` }), back.length ? el("ul", {}, ...back) : el("p", { className: "mudo", textContent: "Nenhuma nota aponta para esta." }),
    secaoLigacoes(n),
    (n.links?.saida || []).length ? el("p", { className: "mudo so-avancado", textContent: `Saidas: ${n.links.saida.map((l) => l.titulo + (l.resolvido ? "" : " (sem nota)")).join(", ")}` }) : null,
    el("p", { className: "aviso", textContent: "Conteudo de memoria e dado nao confiavel: nunca e tratado como instrucao." }));
}

// ------------------------------------------------------------------ 4.22: ligacoes tipadas
let tiposLigacao = null;
const nomeNo = (id) => grafoAtual.nos.find((x) => x.id === id)?.rotulo || id;

async function ligar(origem, destino, tipo, nota) {
  try {
    await api("POST", "/conhecimento/ligacoes", { origem, destino, tipo, nota });
    toast(`Ligacao ${tipo} criada`, "ok"); await carregarGrafo(); renderNota();
  } catch (e) { toast(e.status === 409 ? "Essa ligacao ja existe." : e.message, "erro"); }
}

async function dialogoLigar(origem, destino) {
  tiposLigacao ??= await api("GET", "/conhecimento/tipos-de-ligacao");
  const tipo = el("select", { "aria-label": "Tipo da ligacao" }, ...tiposLigacao.map((t) => el("option", { value: t, textContent: t })));
  const nota = el("input", { maxLength: 300, placeholder: "Nota opcional (por que estao ligados)", "aria-label": "Nota da ligacao" });
  const form = el("form", {}, el("p", { textContent: `${nomeNo(origem)} → ${nomeNo(destino)}` }), el("label", { className: "campo" }, el("span", { textContent: "Tipo" }), tipo),
    el("label", { className: "campo" }, el("span", { textContent: "Nota" }), nota),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Ligar" }), el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo("Nova ligacao tipada", form);
  form.addEventListener("submit", async (ev) => { ev.preventDefault(); d.fechar(); await ligar(origem, destino, tipo.value, nota.value.trim()); });
}

function secaoLigacoes(n) {
  const minhas = grafoAtual.arestas.filter((a) => a.editavel && (a.origem === n.id || a.destino === n.id));
  const alvo = el("select", { "aria-label": "Ligar esta nota a" }, ...grafoAtual.nos.filter((x) => x.id !== n.id && x.grupo !== "fantasma")
    .sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR")).map((x) => el("option", { value: x.id, textContent: x.rotulo })));
  const lista = minhas.map((a) => el("li", { className: "linha" }, tag(a.tipo), el("span", { textContent: a.origem === n.id ? `→ ${nomeNo(a.destino)}` : `← ${nomeNo(a.origem)}` }),
    a.nota ? el("span", { className: "mudo", textContent: a.nota }) : null,
    el("button", { type: "button", textContent: "remover", "aria-label": `Remover ligacao ${a.tipo} com ${nomeNo(a.origem === n.id ? a.destino : a.origem)}`, onclick: async () => {
      try { await api("DELETE", `/conhecimento/ligacoes/${a.id}`); toast("Ligacao removida", "ok"); await carregarGrafo(); renderNota(); } catch (e) { toast(e.message, "erro"); }
    } })));
  return el("section", { className: "ligacoes" }, el("h2", { textContent: `Ligacoes tipadas (${minhas.length})` }),
    lista.length ? el("ul", {}, ...lista) : el("p", { className: "mudo", textContent: "Nenhuma. Ligue esta nota a outra (ou use Shift + arrastar no grafo)." }),
    alvo.options.length ? el("div", { className: "linha" }, alvo, el("button", { type: "button", textContent: "Ligar…", onclick: () => dialogoLigar(n.id, alvo.value) })) : null);
}

function editor(n) {
  const titulo = el("input", { value: n.titulo, maxLength: 200, "aria-label": "Titulo" });
  const texto = el("textarea", { rows: 14, value: n.conteudo || "", maxLength: 100000, "aria-label": "Conteudo em Markdown" });
  const motivo = el("input", { placeholder: "Motivo da edicao (opcional)", maxLength: 1000, className: "so-avancado" });
  return el("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    try {
      const novo = await api("PATCH", `/memorias/${n.id}`, { expected_version: n.versao, titulo: titulo.value, conteudo: texto.value, motivo: motivo.value });
      toast(novo.estado !== n.estado ? `Salva. Editar voltou a memoria para "${novo.estado}".` : "Nota salva", "ok");
      await abrirNo({ id: n.id, grupo: "memoria", rotulo: novo.titulo });
    } catch (e) { toast(e.status === 409 ? "Outra edicao ocorreu antes: reabra a nota." : e.message, "erro"); }
  } }, el("label", { className: "campo" }, el("span", { textContent: "Titulo" }), titulo), el("label", { className: "campo" }, el("span", { textContent: "Conteudo (Markdown, [[links]])" }), texto),
  motivo, el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Salvar" })),
  n.estado === "validado" ? el("p", { className: "aviso", textContent: "Memoria validada: salvar a devolve a candidata e exige nova validacao com evidencia." }) : null);
}

function criarNota(tituloInicial = "") {
  const titulo = el("input", { value: tituloInicial, required: true, maxLength: 200 });
  const texto = el("textarea", { rows: 8, maxLength: 100000 });
  const ns = el("select", {}, ...NAMESPACES.map((v) => el("option", { value: v, textContent: v, selected: sel.namespaces.has(v) })));
  const tipo = el("select", {}, ...["semantica", "procedimental", "episodica", "estrutural", "decisoria", "operacional"].map((v) => el("option", { value: v, textContent: v })));
  const f = el("form", {}, el("label", { className: "campo" }, el("span", { textContent: "Titulo" }), titulo), el("label", { className: "campo" }, el("span", { textContent: "Conteudo" }), texto),
    el("label", { className: "campo" }, el("span", { textContent: "Namespace" }), ns), el("label", { className: "campo so-avancado" }, el("span", { textContent: "Tipo" }), tipo),
    el("p", { className: "aviso", textContent: "A nota nasce como candidata (sem validacao). PII e segredos sao redigidos antes de gravar." }),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Criar nota" }), el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo("Nova nota", f);
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const m = await api("POST", "/memorias", { tipo: tipo.value, titulo: titulo.value, conteudo: texto.value, namespace: ns.value });
      d.fechar(); sel.namespaces.add(ns.value); await carregarGrafo(); await abrirNo({ id: m.id, grupo: "memoria", rotulo: m.titulo });
    } catch (e) { toast(e.message, "erro"); }
  });
}

/** Solicitacao de alimentacao e estudo: pasta (permitida) ou topico (pesquisa). As notas nascem candidatas e ligadas por topico. */
function abrirEstudo() {
  const tipo = el("select", { "aria-label": "Tipo de estudo" }, el("option", { value: "topico", textContent: "Pesquisar um tópico" }),
    el("option", { value: "pasta", textContent: "Analisar uma pasta de código" }));
  const alvo = el("input", { required: true, maxLength: 500, "aria-label": "Tópico ou caminho da pasta", placeholder: "Ex.: boas práticas de filas com prioridade" });
  const foco = el("input", { maxLength: 500, "aria-label": "Foco do estudo", placeholder: "Opcional: o que mais interessa" });
  const ns = el("input", { value: "pessoal/estudos", maxLength: 200, "aria-label": "Namespace das notas", pattern: "[a-z0-9._\\/\\-]+" });
  const web = el("input", { type: "checkbox", checked: true });
  const exec = el("input", { type: "checkbox" });
  const saida = el("div", { role: "status", "aria-live": "polite" });
  tipo.addEventListener("change", () => { alvo.placeholder = tipo.value === "pasta" ? "Caminho completo de uma pasta permitida" : "Ex.: boas práticas de filas com prioridade"; });
  const f = el("form", {},
    el("label", { className: "campo" }, el("span", { textContent: "O que estudar" }), tipo),
    el("label", { className: "campo" }, el("span", { textContent: "Tópico ou pasta" }), alvo),
    el("label", { className: "campo" }, el("span", { textContent: "Foco" }), foco),
    el("label", { className: "campo so-avancado" }, el("span", { textContent: "Onde guardar (namespace)" }), ns),
    el("label", {}, web, " pesquisar na web (citando fontes)"), el("br"),
    el("label", {}, exec, " executar agora (consome créditos; senão fica preparada no quadro)"),
    el("p", { className: "aviso", textContent: "O agente de estudo usa o modelo rápido e só lê. As notas entram como candidatas, divididas em subtópicos ligados; você revisa antes de valerem como fato." }),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Solicitar estudo" }),
      el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })), saida);
  const d = dialogo("Estudar e alimentar o segundo cérebro", f);
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("POST", "/estudos", { tipo: tipo.value, alvo: alvo.value.trim(), foco: foco.value.trim(), namespace: ns.value.trim(),
        pesquisar_web: web.checked, executar: exec.checked });
      limpar(saida);
      saida.append(el("p", { textContent: exec.checked ? "Estudo iniciado. As notas aparecem no grafo ao terminar." : "Estudo preparado (não executado)." }),
        el("button", { type: "button", textContent: "Abrir no quadro", onclick: () => { d.fechar(); selecionarTarefa(r.tarefa.id); emitir("ir", "tarefas"); } }));
    } catch (e) { toast(e.message, "erro"); }
  });
  alvo.focus();
}

export function montarLateral(lat) {
  limpar(lat);
  const busca = el("input", { type: "search", placeholder: "Buscar titulo, texto ou tag", value: sel.q, "aria-label": "Buscar no grafo", maxLength: 200 });
  busca.addEventListener("input", () => { clearTimeout(busca._t); busca._t = setTimeout(() => { sel.q = busca.value.trim(); carregarGrafo(); }, 250); });
  const nss = NAMESPACES.map((ns) => el("label", {}, el("input", { type: "checkbox", checked: sel.namespaces.has(ns), onchange: (ev) => {
    if (ev.target.checked) sel.namespaces.add(ns); else sel.namespaces.delete(ns);
    if (!sel.namespaces.size) { sel.namespaces.add("publico"); ev.target.checked = ns === "publico"; }
    carregarGrafo();
  } }), ` ${ns}`));
  const lista = el("ul", { className: "lista-notas", "aria-label": "Notas" });
  ctx.lista = lista;
  lat.append(el("h2", { textContent: "Segundo cerebro" }), el("button", { type: "button", className: "primario", textContent: "+ Nova nota", onclick: () => criarNota() }),
    el("label", { className: "campo" }, el("span", { textContent: "Busca" }), busca),
    el("fieldset", {}, el("legend", { className: "mudo", textContent: "Namespaces" }), ...nss.map((n) => el("div", {}, n))),
    el("label", { className: "campo so-avancado" }, el("span", { textContent: "Saltos de vizinhanca na busca" }), el("select", { onchange: (ev) => { sel.vizinhos = Number(ev.target.value); carregarGrafo(); } },
      ...[0, 1, 2].map((n) => el("option", { value: n, textContent: String(n), selected: n === sel.vizinhos })))),
    el("label", { className: "so-avancado" }, el("input", { type: "checkbox", checked: sel.inativas, onchange: (ev) => { sel.inativas = ev.target.checked; carregarGrafo(); } }), " incluir revogadas/substituidas"),
    el("label", { title: "Base inicial curada da Forja (somente leitura): engenharia, segurança, DevOps, banco, front, UX, QA, RPA, Python e agentes" },
      el("input", { type: "checkbox", checked: sel.base, onchange: (ev) => { sel.base = ev.target.checked; carregarGrafo(); } }), " mostrar a base da Forja"),
    el("button", { type: "button", textContent: "Estudar e alimentar…", title: "Peça a um agente para estudar uma pasta ou pesquisar um tópico e criar notas",
      onclick: () => abrirEstudo() }),
    el("button", { type: "button", textContent: "Avaliar a busca", title: "Rotule perguntas reais e meca a precisao da busca no seu corpus",
      onclick: () => abrirRotulagem(sel.namespaces).catch((e) => toast(e.message, "erro")) }),
    el("h2", { textContent: "Lista de notas" }), lista);
}

export function montar(raiz) {
  limpar(raiz);
  const resumo = el("span", { className: "mudo", role: "status" });
  const caixa = el("div", { className: "grafo-caixa" });
  const vazio = el("p", { className: "aviso", hidden: true, textContent: "Nenhuma nota neste filtro. Crie uma nota ou ingira uma pasta (scripts/memoria_ingerir.py)." });
  const nota = el("article", { className: "nota", hidden: true, "aria-label": "Nota" });
  const grade = el("div", { className: `memoria${sel.nota ? "" : " sem-nota"}` }, el("div", {}, caixa, vazio), nota);
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Grafo do conhecimento" }), resumo,
    el("button", { type: "button", textContent: "Atualizar", onclick: carregarGrafo })), grade);
  ctx = { ...ctx, raiz: grade, caixa, resumo, nota, vazio };
  renderNota();
  carregarGrafo();
}

const reagir = agrupar(() => { if (ctx.caixa?.isConnected) carregarGrafo(); });
ouvir("evento", (e) => { if (String(e.tipo).startsWith("memoria.")) reagir(); });
