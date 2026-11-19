// Shell da Forja: tres visualizacoes (Editor estilo VS Code/Kiro, Chat de agentes e Agentes em pixel art), barra de atividades,
// barra lateral, abas do editor, barra do agente (direita), painel inferior, paleta de comandos e tempo real (SSE).
import { api, lerToken } from "./api.js";
import * as area from "./area.js";
import { abaAtiva, abas, abrirInicio, abrirVista, ativar, fechar, iniciarBancada, lateralAtual, marcarAtividade, mostrarLateral, reexibir } from "./bancada.js";
import "./receitas.js"; // ouvintes: abrir receitas a partir do Git, Docker, terminal e erros
import { abrirPaleta, iniciarPaleta, registrarComandos } from "./comandos.js";
import * as direita from "./direita.js";
import * as escritorio from "./escritorio.js";
import { agrupar, alternarPainel, definirModo, definirNivel, definirPainel, emitir, estado, ouvir, painelAberto, painelLembrado } from "./estado.js";
import { icone } from "./icones.js";
import * as inferior from "./inferior.js";
import { iniciarDicas, iniciarTransicoes } from "./movimento.js";
import { dialogoConta, garantirAcesso } from "./login.js";
import { $, dialogo, el, iniciarTexto } from "./ui.js";
import * as comandosVista from "./views/comandos.js";
import * as config from "./views/config.js";
import * as custos from "./views/custos.js";
import * as ferramentas from "./views/ferramentas.js";
import * as http from "./views/http.js";
import * as integracoes from "./views/integracoes.js";
import * as master from "./views/master.js";
import { aprender, organizar } from "./views/conhecimento.js";
import * as memoria from "./views/memoria.js";
import * as revisaoVista from "./views/revisao.js";
import * as quadro from "./views/quadro.js";
import * as tarefas from "./views/tarefas.js";

// tipo "painel": so a barra lateral (como o Explorador do VS Code); "vista": aba no editor (+ menu na barra lateral, se houver)
const ATIVIDADES = [
  { id: "explorador", rotulo: "Explorador", curto: "Explorar", icone: "explorador", tipo: "painel", montarLateral: area.montarExplorador, atalho: "Ctrl+Shift+E" },
  { id: "busca", rotulo: "Buscar nos arquivos", curto: "Buscar", icone: "busca", tipo: "painel", montarLateral: area.montarBusca, atalho: "Ctrl+Shift+F" },
  { id: "git", rotulo: "Controle de código (Git)", curto: "Git", icone: "git", tipo: "painel", montarLateral: area.montarGit, atalho: "Ctrl+Shift+G" },
  { id: "docker", rotulo: "Docker", curto: "Docker", icone: "docker", tipo: "painel", montarLateral: area.montarDocker },
  { id: "http", rotulo: "Requisições HTTP", curto: "HTTP", icone: "http", tipo: "vista", modulo: http },
  { id: "comandos", rotulo: "Comandos e receitas", curto: "Comandos", icone: "comandos", tipo: "vista", modulo: comandosVista },
  { separador: true },
  { id: "master", rotulo: "Master", curto: "Master", icone: "master", tipo: "vista", modulo: master },
  { id: "tarefas", rotulo: "Tarefas", curto: "Tarefas", icone: "tarefas", tipo: "vista", modulo: tarefas },
  { id: "quadro", rotulo: "Quadro de mensagens", curto: "Quadro", icone: "quadro", tipo: "vista", modulo: quadro },
  { id: "memoria", rotulo: "Memória", aba: "Grafo e notas", curto: "Memória", icone: "memoria", tipo: "vista", modulo: memoria },
  { id: "aprender", rotulo: "Buscar e aprender", curto: "Aprender", icone: "lampada", tipo: "vista", modulo: aprender },
  { id: "organizar", rotulo: "Organizar e deduplicar", aba: "Organizar", curto: "Organizar", icone: "memoria", tipo: "vista", modulo: organizar },
  { id: "revisao", rotulo: "Revisão do segundo cérebro", aba: "Revisão", curto: "Revisão", icone: "tarefas", tipo: "vista", modulo: revisaoVista },
  { id: "ferramentas", rotulo: "Ferramentas", curto: "Ferram.", icone: "ferramentas", tipo: "vista", modulo: ferramentas },
  { id: "integracoes", rotulo: "Integrações", curto: "Integr.", icone: "integracoes", tipo: "vista", modulo: integracoes },
  { id: "custos", rotulo: "Custo", curto: "Custo", icone: "custos", tipo: "vista", modulo: custos },
  { espaco: true },
  { id: "conta", rotulo: "Sua conta", curto: "Conta", icone: "conta", tipo: "acao", fazer: () => dialogoConta($("#usuario-atual").textContent) },
  { id: "config", rotulo: "Configurações", curto: "Config", icone: "config", tipo: "acao", fazer: () => config.abrirJanela(), atalho: "Ctrl+," },
];
// Barra de atividades em GRUPOS (6 itens + conta e configuracoes): cada grupo abre o ultimo membro usado e mostra os membros
// como abas no topo (barra lateral para Arquivos e Codigo; aba do editor para os demais). As rotas #/<membro> continuam valendo.
const GRUPOS = [
  { id: "arquivos", rotulo: "Arquivos: explorador e busca", curto: "Arquivos", icone: "explorador", tipo: "painel", membros: ["explorador", "busca"] },
  { id: "codigo", rotulo: "Código: Git e Docker", curto: "Código", icone: "git", tipo: "painel", membros: ["git", "docker"] },
  { id: "dev", rotulo: "Desenvolvimento: requisições HTTP, comandos e receitas", curto: "Dev", icone: "http", tipo: "vista", membros: ["http", "comandos"] },
  { id: "orquestracao", rotulo: "Orquestração: master, tarefas e quadro", curto: "Agentes", icone: "master", tipo: "vista", membros: ["master", "tarefas", "quadro"] },
  { id: "conhecimento", rotulo: "Conhecimento: segundo cérebro, grafo, aprender, organizar e ferramentas", curto: "Saber", icone: "memoria", tipo: "vista",
    membros: ["memoria", "aprender", "organizar", "revisao", "ferramentas"] },
  { id: "conexoes", rotulo: "Conexões: integrações e custo", curto: "Conexões", icone: "integracoes", tipo: "vista", membros: ["integracoes", "custos"] },
];
const REAIS = ATIVIDADES.filter((a) => a.id);
const atividade = (id) => REAIS.find((a) => a.id === id);
const grupoDe = (id) => GRUPOS.find((g) => g.membros.includes(id));
const ultimos = (() => { try { return JSON.parse(localStorage.getItem("forja_grupos") || "{}"); } catch { return {}; } })();
const lembrarMembro = (id) => { const g = grupoDe(id); if (g) { ultimos[g.id] = id; localStorage.setItem("forja_grupos", JSON.stringify(ultimos)); } };
let fonte = null;
const vistos = new Set();

/** Navega para uma area. Vistas abrem (ou reativam) a aba e mostram o menu delas na barra lateral. */
function ir(id, { abrirMenu = true } = {}) {
  if (id === "config") {
    if (!abaAtiva()) abrirInicio();
    history.replaceState(null, "", "#/config");
    config.abrirJanela();
    return;
  }
  if (id === "agentes" || id === "chat") return definirModo(id);
  if (id === "inicio") { if (estado.modo !== "editor") definirModo("editor"); abrirInicio(); return; }
  const grupo = GRUPOS.find((g) => g.id === id);
  if (grupo) return ir(ultimos[grupo.id] || grupo.membros[0], { abrirMenu });
  const at = atividade(id);
  if (!at) return ir("inicio");
  if (estado.modo !== "editor") definirModo("editor");
  lembrarMembro(id);
  if (at.tipo === "painel") return mostrarLateral(id);
  if (at.tipo === "acao") return at.fazer();
  abrirVista(id);
  if (typeof at.modulo.montarLateral === "function") mostrarLateral(id, { abrir: abrirMenu });
}

function clicarGrupo(g) {
  const aba = abaAtiva();
  const ativo = (painelAberto("lateral") && g.membros.includes(lateralAtual())) || (aba?.tipo === "vista" && g.membros.includes(aba.id));
  if (ativo && estado.modo === "editor") return clicarAtividade(g.tipo === "painel" ? lateralAtual() : aba.id);
  ir(ultimos[g.id] || g.membros[0]);
}

function clicarAtividade(id) {
  const at = atividade(id);
  if (at.tipo === "acao") return at.fazer();
  if (estado.modo !== "editor") definirModo("editor");
  const aba = abaAtiva();
  const mostrando = painelAberto("lateral") && lateralAtual() === id;
  if (at.tipo === "painel") return mostrando ? definirPainel("lateral", false) : mostrarLateral(id);
  if (aba?.tipo === "vista" && aba.id === id) { // como nas IDEs: clicar na area ativa recolhe/abre a barra lateral
    if (mostrando) return definirPainel("lateral", false);
    if (typeof at.modulo.montarLateral === "function") return mostrarLateral(id);
    return;
  }
  ir(id);
}

function montarAtividades() {
  const nav = $("#atividades");
  for (const g of GRUPOS) {
    const atalhos = g.membros.map(atividade).filter((a) => a?.atalho).map((a) => `${a.rotulo.split(" (")[0]}: ${a.atalho}`);
    nav.append(el("button", { type: "button", dataset: { id: g.id, membros: g.membros.join(" ") }, title: atalhos.length ? `${g.rotulo} (${atalhos.join("; ")})` : g.rotulo,
      "aria-label": g.rotulo, onclick: () => clicarGrupo(g) }, icone(g.icone, 22), el("span", { textContent: g.curto })));
  }
  nav.append(el("span", { className: "espaco" }));
  for (const a of ATIVIDADES.filter((x) => x.tipo === "acao")) {
    nav.append(el("button", { type: "button", dataset: { id: a.id }, title: a.atalho ? `${a.rotulo} (${a.atalho})` : a.rotulo, "aria-label": a.rotulo,
      onclick: () => clicarAtividade(a.id) }, icone(a.icone, 22), el("span", { textContent: a.curto })));
  }
  // setas ↑/↓ entre as areas (padrao das barras de atividade das IDEs)
  nav.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    const bs = [...nav.querySelectorAll("button")]; const i = bs.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault(); bs[(i + (ev.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length].focus();
  });
}

function proximaAba(passo) {
  const lista = abas(); const i = lista.findIndex((a) => a.chave === abaAtiva()?.chave);
  if (lista.length > 1) ativar(lista[(i + passo + lista.length) % lista.length].chave);
}

function comandos() {
  const c = (rotulo, executar, atalho = "") => ({ rotulo, executar, atalho });
  return [
    ...REAIS.map((a) => c(`Ir para: ${a.rotulo}`, () => (a.tipo === "acao" ? a.fazer() : ir(a.id)), a.atalho || "")),
    c("Visualização: Editor", () => definirModo("editor"), "Ctrl+Alt+1"),
    c("Visualização: Chat de agentes", () => definirModo("chat"), "Ctrl+Alt+2"),
    c("Visualização: Agentes (oficina)", () => definirModo("agentes"), "Ctrl+Alt+3"),
    c("Novo pedido ao master", novoPedido),
    c("Alternar barra lateral", () => alternarPainel("lateral"), "Ctrl+B"),
    c("Alternar painel inferior", () => alternarPainel("inferior"), "Ctrl+J"),
    c("Alternar conversa (barra do agente)", () => alternarPainel("direita"), "Ctrl+Alt+B"),
    c("Abrir terminal", () => emitir("inferior", "terminal"), "Ctrl+`"),
    c("Mostrar problemas", () => emitir("inferior", "problemas")),
    c("Mostrar eventos", () => emitir("inferior", "eventos")),
    c("Mostrar decisões pendentes", () => emitir("abrir-direita", "decisoes")),
    c("Arquivo: salvar", () => abaAtiva()?.editor?.salvar(), "Ctrl+S"),
    c("Arquivo: buscar no arquivo", () => abaAtiva()?.editor?.abrirBusca(false), "Ctrl+F"),
    c("Arquivo: substituir no arquivo", () => abaAtiva()?.editor?.abrirBusca(true), "Ctrl+H"),
    c("Arquivo: alternar prévia (Markdown/HTML)", () => abaAtiva()?.editor?.alternarPrevia(), "Ctrl+Shift+V"),
    c("Arquivo: ir para a linha…", () => abrirPaleta(":"), "Ctrl+G"),
    c("Abas: fechar a aba atual", () => abaAtiva() && fechar(abaAtiva().chave), "Ctrl+Alt+W"),
    c("Abas: próxima aba", () => proximaAba(1), "Ctrl+Alt+→"),
    c("Abas: aba anterior", () => proximaAba(-1), "Ctrl+Alt+←"),
    c("Abrir boas-vindas", () => ir("inicio")),
    c("Mostrar atalhos de teclado", mostrarAtalhos, "Ctrl+/"),
    c("Receitas: processos passo a passo", () => emitir("receitas", "")),
    c("Arquivo: ir para símbolo…", () => abrirPaleta("@"), "Ctrl+Shift+O"),
    c("Arquivo: autocompletar", () => abaAtiva()?.editor && document.querySelector("#vista .fonte")?.dispatchEvent(new KeyboardEvent("keydown", { key: " ", ctrlKey: true, bubbles: true })), "Ctrl+Espaço"),
    c("Arquivo: ir para a definição", () => document.querySelector("#vista .fonte")?.dispatchEvent(new KeyboardEvent("keydown", { key: "F12", bubbles: true })), "F12"),
    c("Detalhe: alternar Simples/Avançado", () => { const n = $("#nivel"); n.value = n.value === "simples" ? "avancado" : "simples"; n.dispatchEvent(new Event("change")); }),
  ];
}

const ATALHOS = [["Geral", [["Ctrl+P", "Abrir arquivo"], ["Ctrl+Shift+P / F1", "Todos os comandos"], ["Ctrl+Shift+O", "Ir para símbolo do arquivo"], ["Ctrl+G", "Ir para a linha"],
  ["Ctrl+,", "Configurações"], ["Ctrl+/", "Esta lista"]]],
["Visualização", [["Ctrl+Alt+1 / 2 / 3", "Editor / Chat / Agentes"], ["Ctrl+B", "Barra lateral"], ["Ctrl+J", "Painel inferior"], ["Ctrl+Alt+B", "Conversa (barra do agente)"],
  ["Ctrl+Alt+I", "Abrir o chat"], ["Ctrl+`", "Terminal"], ["Ctrl+Shift+E / F / G", "Explorador / Busca / Git"]]],
["Editor", [["Ctrl+S", "Salvar"], ["Ctrl+F / Ctrl+H", "Buscar / substituir"], ["Ctrl+Espaço", "Sugestões"], ["F12 ou Ctrl+clique", "Ir para a definição"],
  ["Ctrl+Shift+V", "Prévia (Markdown/HTML)"], ["Tab / Shift+Tab", "Indentar"], ["Esc e Tab", "Sair do editor pelo teclado"], ["Ctrl+Alt+W", "Fechar aba"]]],
["Terminal", [["Tab", "Completar a sugestão"], ["↑ / ↓", "Sugestões (quando abertas) ou histórico"], ["Enter", "Executar"], ["Esc", "Fechar sugestões"]]],
["Diferenças", [["Alt+↑ / Alt+↓", "Alteração anterior / próxima"]]]];

function mostrarAtalhos() {
  dialogo("Atalhos de teclado", el("div", { className: "atalhos-grade" }, ...ATALHOS.map(([grupo, itens]) => el("section", {}, el("h3", { textContent: grupo }),
    el("dl", {}, ...itens.flatMap(([k, d]) => [el("dt", {}, el("kbd", { textContent: k })), el("dd", { textContent: d })]))))));
}

function novoPedido() {
  localStorage.setItem("forja_fio", JSON.stringify({ tipo: "master" }));
  definirModo("chat");
  requestAnimationFrame(() => setTimeout(() => $("#direita-corpo textarea")?.focus(), 200));
}

function atalhos() {
  $("#alternar-lateral").addEventListener("click", () => alternarPainel("lateral"));
  $("#alternar-direita").addEventListener("click", () => alternarPainel("direita"));
  $("#alternar-inferior").addEventListener("click", () => alternarPainel("inferior"));
  $("#centro-comandos").addEventListener("click", () => abrirPaleta(""));
  for (const b of document.querySelectorAll("#modos button")) b.addEventListener("click", () => definirModo(b.dataset.modo));
  for (const b of document.querySelectorAll("[data-fechar]")) b.addEventListener("click", () => { if (b.dataset.fechar === "direita" && estado.modo === "chat") definirModo("editor"); definirPainel(b.dataset.fechar, false); });
  $('[data-expandir="direita"]').addEventListener("click", () => definirModo(estado.modo === "chat" ? "editor" : "chat"));
  $('[data-maximizar="inferior"]').addEventListener("click", (ev) => {
    const a = $("#area"); const max = a.dataset.inferiorMax !== "on";
    a.dataset.inferiorMax = max ? "on" : "off"; ev.currentTarget.setAttribute("aria-pressed", String(max));
  });
  // Arrastar um cartao com o painel sobreposto (tela estreita): os paineis deixam o ponteiro passar.
  document.addEventListener("dragstart", () => document.body.classList.add("arrastando"));
  for (const t of ["dragend", "drop"]) document.addEventListener(t, () => document.body.classList.remove("arrastando"));
  const estreita = matchMedia("(max-width: 760px)");
  // Em tela estreita os paineis viram gavetas: clicar no conteudo recolhe o menu lateral.
  $("#principal").addEventListener("pointerdown", () => { if (estreita.matches && painelAberto("lateral")) definirPainel("lateral", false, { lembrar: false }); });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !document.querySelector("dialog[open]")) {
      const emFoco = ["lateral", "direita", "inferior"].find((n) => $(`#${n}`).contains(document.activeElement));
      const alvo = emFoco && painelAberto(emFoco) ? emFoco : estreita.matches && painelAberto("lateral") ? "lateral" : null;
      if (alvo && !(alvo === "direita" && estado.modo === "chat")) { ev.preventDefault(); definirPainel(alvo, false); }
      return;
    }
    if (ev.key === "F1") { ev.preventDefault(); abrirPaleta(">"); return; }
    if (!(ev.ctrlKey || ev.metaKey)) return;
    const k = ev.key.toLowerCase();
    const comAlt = ev.altKey;
    if (comAlt && ev.target instanceof Element && ev.target.matches("textarea, input, [contenteditable]")) return; // AltGr (= Ctrl+Alt) digita caracteres
    if (comAlt && ["1", "2", "3"].includes(ev.key)) { ev.preventDefault(); definirModo(["editor", "chat", "agentes"][Number(ev.key) - 1]); }
    else if (comAlt && k === "b") { ev.preventDefault(); alternarPainel("direita"); }
    else if (comAlt && k === "i") { ev.preventDefault(); definirPainel("direita", true); requestAnimationFrame(() => $("#direita-corpo textarea")?.focus()); }
    else if (comAlt && k === "w") { ev.preventDefault(); if (abaAtiva()) fechar(abaAtiva().chave); }
    else if (comAlt && ev.key === "ArrowRight") { ev.preventDefault(); proximaAba(1); }
    else if (comAlt && ev.key === "ArrowLeft") { ev.preventDefault(); proximaAba(-1); }
    else if (k === "s" && !ev.shiftKey) { ev.preventDefault(); abaAtiva()?.editor?.salvar(); } // fora do editor tambem salva a aba ativa
    else if (k === "b" && ev.shiftKey) { ev.preventDefault(); alternarPainel("direita"); }
    else if (k === "p" && ev.shiftKey) { ev.preventDefault(); abrirPaleta(">"); }
    else if (k === "o" && ev.shiftKey) { ev.preventDefault(); abrirPaleta("@"); }
    else if (ev.key === "/" && !ev.shiftKey) { ev.preventDefault(); mostrarAtalhos(); }
    else if (k === "p") { ev.preventDefault(); abrirPaleta(""); }
    else if (k === "g" && !ev.shiftKey) { ev.preventDefault(); abrirPaleta(":"); }
    else if (k === "e" && ev.shiftKey) { ev.preventDefault(); ir("explorador"); }
    else if (k === "f" && ev.shiftKey) { ev.preventDefault(); ir("busca"); }
    else if (k === "g" && ev.shiftKey) { ev.preventDefault(); ir("git"); }
    else if (k === "b") { ev.preventDefault(); alternarPainel("lateral"); }
    else if (k === "j") { ev.preventDefault(); alternarPainel("inferior"); }
    else if (ev.key === "`") { ev.preventDefault(); emitir("inferior", "terminal"); }
    else if (k === ",") { ev.preventDefault(); config.abrirJanela(); }
  });
}

// ---- tempo real (SSE com replay por Last-Event-ID; o servidor nao nomeia eventos: o tipo vem em d.tipo)
function conectarSse() {
  if (fonte) fonte.close();
  const t = lerToken();
  fonte = new EventSource(`/api/v1/eventos/stream${t ? `?token=${encodeURIComponent(t)}` : ""}`);
  const pill = $("#conexao");
  fonte.onopen = () => { pill.textContent = "conectado"; pill.classList.add("ok"); };
  fonte.onerror = () => { pill.textContent = "reconectando…"; pill.classList.remove("ok"); };
  fonte.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (vistos.has(d.seq)) return;
    vistos.add(d.seq);
    emitir("evento", d);
  };
}

async function atualizarChip() {
  try {
    const q = await api("GET", "/kanban");
    const chip = $("#atalho-precisa");
    chip.hidden = !q.precisa_de_voce;
    chip.textContent = q.precisa_de_voce === 1 ? "1 precisa de você" : `${q.precisa_de_voce} precisam de você`;
    emitir("kanban", q);
  } catch { /* o chip e informativo */ }
}
const agendarChip = agrupar(() => { atualizarChip(); const a = abaAtiva(); if (a?.tipo === "vista" && a.id === "tarefas" && estado.modo === "editor") tarefas.atualizar(); });

function mostrarUsuario(usuario) {
  const b = $("#usuario-atual");
  b.hidden = !usuario;
  if (usuario) { b.replaceChildren(icone("conta", 14), el("span", { className: "trunc", textContent: usuario })); b.title = `Conectado como ${usuario}: trocar senha ou sair`; b.setAttribute("aria-label", `Sua conta: ${usuario}`); }
}

let reautenticando = false;
async function sessaoExpirou() {
  if (reautenticando) return;
  reautenticando = true;
  if (fonte) fonte.close();
  await garantirAcesso("Sua sessão expirou. Entre de novo para continuar.");
  location.reload(); // recarrega as telas com a sessao nova
}

let pronto = false;
function aoMudarModo(m) {
  if (!pronto) return;
  if (m === "agentes") { $("#principal").setAttribute("aria-label", "Agentes"); escritorio.montar($("#vista")); history.replaceState(null, "", "#/agentes"); }
  else if (m === "chat") { definirPainel("direita", true, { lembrar: false }); history.replaceState(null, "", "#/chat"); }
  else { reexibir(); const a = abaAtiva(); history.replaceState(null, "", a?.tipo === "vista" ? `#/${a.id}` : "#/editor"); }
  marcarAtividade();
}

async function iniciar() {
  montarAtividades(); atalhos(); iniciarTexto(); iniciarPaleta(); iniciarDicas(); iniciarTransicoes();
  registrarComandos(comandos());
  ouvir("janela-fechada", () => { marcarAtividade(); const a = abaAtiva(); history.replaceState(null, "", a?.tipo === "vista" ? `#/${a.id}` : estado.modo === "editor" ? "#/editor" : `#/${estado.modo}`); });
  const nivel = $("#nivel");
  nivel.value = estado.nivel; definirNivel(estado.nivel);
  nivel.addEventListener("change", () => { definirNivel(nivel.value); config.definirPreferencia("nivel_detalhe", nivel.value).catch(() => {}); });
  document.addEventListener("forja:auth", sessaoExpirou);
  $("#usuario-atual").addEventListener("click", () => dialogoConta($("#usuario-atual").textContent));
  ouvir("ir", ir);
  ouvir("paleta", (prefixo) => abrirPaleta(prefixo || ""));
  ouvir("atividade", (id) => ir(id));
  ouvir("modo-pedido", novoPedido);
  ouvir("modo", aoMudarModo);
  ouvir("aba", (a) => {
    if (a.tipo === "vista") {
      history.replaceState(null, "", `#/${a.id}`);
      const at = atividade(a.id);
      const lat = atividade(lateralAtual());
      if (typeof at?.modulo.montarLateral === "function" && lat?.tipo === "vista" && lat.id !== a.id) mostrarLateral(a.id, { abrir: painelAberto("lateral") });
    } else if (estado.modo === "editor") history.replaceState(null, "", "#/editor");
  });
  ouvir("evento", (e) => {
    const t = String(e.tipo);
    if (/^(tarefa|execucao|aprovacao|conversa)\./.test(t)) agendarChip();
    if (t.startsWith("configuracao.")) config.recarregar().catch(() => {});
  });
  $("#atalho-precisa").addEventListener("click", () => { if (estado.modo === "agentes") definirModo("editor"); ir("tarefas"); });
  setInterval(() => { $("#st-hora").textContent = new Date().toLocaleTimeString("pt-BR"); }, 1000);

  mostrarUsuario(await garantirAcesso()); // so segue depois de um login valido (ou se o servidor nao exige login)
  const ativaSalva = iniciarBancada(REAIS, GRUPOS);
  definirPainel("lateral", painelLembrado("lateral", true), { lembrar: false });
  definirPainel("inferior", painelLembrado("inferior", false), { lembrar: false });
  direita.iniciar(); inferior.iniciar();
  const rota = (location.hash.match(/^#\/(\w+)/) || [])[1];
  const modo = rota === "chat" || rota === "agentes" ? rota : rota && rota !== "editor" ? "editor" : estado.modo;
  estado.modo = modo; // as abas montam (ou nao) conforme o modo inicial
  const alvoRota = rota ? atividade(rota) : null; // vista (abre a aba dela) ou painel (Explorador, Git...: so a barra lateral)
  const rotaVista = alvoRota?.tipo === "vista";
  if (!rotaVista) { if (ativaSalva && abas().some((a) => a.chave === ativaSalva)) ativar(ativaSalva); else abrirInicio(); }
  const ativa = abaAtiva(); // a barra lateral volta com o menu da tela aberta (ou o Explorador)
  const menuDaTela = ativa?.tipo === "vista" && typeof atividade(ativa.id)?.modulo.montarLateral === "function";
  mostrarLateral(menuDaTela ? ativa.id : "explorador", { abrir: painelAberto("lateral") });
  if (alvoRota || rota === "config") ir(rota);
  definirModo(modo);
  pronto = true;
  if (modo !== "editor") aoMudarModo(modo);
  conectarSse(); atualizarChip();
  config.recarregar().catch(() => {});
  config.carregarPreferencias().catch(() => {});
  addEventListener("hashchange", () => { const id = (location.hash.match(/^#\/(\w+)/) || [])[1]; if (id && id !== abaAtiva()?.id && id !== "editor") ir(id); });
}

iniciar();
