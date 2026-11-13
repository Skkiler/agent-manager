// Shell do orquestrador: barra de atividades, barra lateral, area principal, conversa/decisoes, painel inferior e SSE.
import { api, lerToken } from "./api.js";
import { dialogoConta, garantirAcesso } from "./login.js";
import * as direita from "./direita.js";
import { agrupar, alternarPainel, definirNivel, definirPainel, emitir, estado, ouvir, painelAberto } from "./estado.js";
import * as inferior from "./inferior.js";
import { $, el, iniciarTexto, limpar } from "./ui.js";
import * as config from "./views/config.js";
import * as custos from "./views/custos.js";
import * as ferramentas from "./views/ferramentas.js";
import * as integracoes from "./views/integracoes.js";
import * as memoria from "./views/memoria.js";
import * as quadro from "./views/quadro.js";
import * as tarefas from "./views/tarefas.js";

const VISTAS = [
  { id: "tarefas", rotulo: "Tarefas", glifo: "▦", modulo: tarefas },
  { id: "quadro", rotulo: "Quadro", glifo: "✉", modulo: quadro },
  { id: "memoria", rotulo: "Memória", glifo: "◉", modulo: memoria },
  { id: "ferramentas", rotulo: "Ferram.", glifo: "⚒", modulo: ferramentas },
  { id: "integracoes", rotulo: "Integr.", glifo: "⇄", modulo: integracoes },
  { id: "custos", rotulo: "Custo", glifo: "¤", modulo: custos },
  { id: "config", rotulo: "Config", glifo: "⚙", modulo: config, janela: true }, // tela secundaria: janela flutuante, nao pagina
];
let atual = null;
let fonte = null;
const vistos = new Set();

function marcarAtual() {
  for (const b of document.querySelectorAll("#atividades button")) b.setAttribute("aria-current", b.dataset.id === atual ? "page" : "false");
}

/** Troca a area principal. O menu lateral da area abre por cima do conteudo (gaveta) e fecha ao clicar fora, Esc ou Ctrl+B. */
function ir(id, { abrirMenu = true } = {}) {
  const v = VISTAS.find((x) => x.id === id) || VISTAS[0];
  if (v.janela) { // a area de fundo continua; o endereco #/config reabre a janela (link direto e recarregar)
    if (!atual) ir("tarefas", { abrirMenu: false });
    history.replaceState(null, "", `#/${v.id}`);
    config.abrirJanela();
    return;
  }
  atual = v.id;
  if (location.hash !== `#/${v.id}`) history.replaceState(null, "", `#/${v.id}`);
  marcarAtual();
  const lat = $("#lateral");
  limpar(lat);
  const temMenu = typeof v.modulo.montarLateral === "function";
  if (temMenu) v.modulo.montarLateral(lat);
  definirPainel("lateral", temMenu && abrirMenu);
  v.modulo.montar($("#principal"));
  $("#principal").setAttribute("aria-label", v.rotulo);
}

function clicarAtividade(id) {
  if (id === atual && painelAberto("lateral")) return definirPainel("lateral", false); // como nas IDEs: clicar na area ativa recolhe
  if (id === atual) return definirPainel("lateral", true);
  ir(id);
}

function montarAtividades() {
  const nav = $("#atividades");
  nav.append(...VISTAS.map((v) => el("button", { type: "button", dataset: { id: v.id }, title: v.rotulo, "aria-label": v.rotulo, onclick: () => clicarAtividade(v.id) },
    el("span", { className: "glifo", "aria-hidden": "true", textContent: v.glifo }), el("span", { textContent: v.rotulo }))));
  // Navegacao por setas ↑/↓ entre as areas (padrao de barras de atividade de IDEs)
  nav.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    const bs = [...nav.querySelectorAll("button")]; const i = bs.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault(); bs[(i + (ev.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length].focus();
  });
}

function atalhos() {
  $("#alternar-lateral").addEventListener("click", () => alternarPainel("lateral"));
  $("#alternar-direita").addEventListener("click", () => alternarPainel("direita"));
  $("#alternar-inferior").addEventListener("click", () => alternarPainel("inferior"));
  for (const b of document.querySelectorAll("[data-fechar]")) b.addEventListener("click", () => definirPainel(b.dataset.fechar, false));
  // Clique fora do menu lateral (no conteudo ou no painel inferior) o recolhe; o clique continua valendo para o que foi clicado.
  for (const alvo of ["#principal", "#inferior", "#direita"]) $(alvo).addEventListener("pointerdown", () => { if (painelAberto("lateral")) definirPainel("lateral", false); });
  // Arrastar um cartao: os paineis sobrepostos ficam translucidos e deixam o ponteiro passar (a coluna de destino pode estar embaixo).
  document.addEventListener("dragstart", () => document.body.classList.add("arrastando"));
  for (const t of ["dragend", "drop"]) document.addEventListener(t, () => document.body.classList.remove("arrastando"));
  // Escolher um item de lista do menu (nota, ferramenta) e "navegar": o menu sai da frente do conteudo escolhido.
  $("#lateral").addEventListener("click", (ev) => { if (ev.target.closest(".lista-notas button")) definirPainel("lateral", false); });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !document.querySelector("dialog[open]")) {
      // Fecha o painel sobreposto de cima: menu lateral, depois o painel em foco (conversa ou inferior).
      const emFoco = ["direita", "inferior"].find((n) => $(`#${n}`).contains(document.activeElement));
      const alvo = painelAberto("lateral") ? "lateral" : emFoco && painelAberto(emFoco) ? emFoco : null;
      if (alvo) { ev.preventDefault(); definirPainel(alvo, false); }
      return;
    }
    if (!(ev.ctrlKey || ev.metaKey)) return;
    const k = ev.key.toLowerCase();
    if (k === "b" && ev.shiftKey) { ev.preventDefault(); alternarPainel("direita"); }
    else if (k === "b") { ev.preventDefault(); alternarPainel("lateral"); }
    else if (k === "j") { ev.preventDefault(); alternarPainel("inferior"); }
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
  fonte.onerror = () => { pill.textContent = "reconectando..."; pill.classList.remove("ok"); };
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
    chip.textContent = `${q.precisa_de_voce} precisam de você`;
    emitir("kanban", q);
  } catch { /* o chip e informativo */ }
}
const agendarChip = agrupar(() => { atualizarChip(); if (atual === "tarefas") tarefas.atualizar(); });

function mostrarUsuario(usuario) {
  const b = $("#usuario-atual");
  b.hidden = !usuario;
  if (usuario) { b.textContent = usuario; b.title = `Conectado como ${usuario}: trocar senha ou sair`; }
}

let reautenticando = false;
async function sessaoExpirou() {
  if (reautenticando) return;
  reautenticando = true;
  if (fonte) fonte.close();
  await garantirAcesso("Sua sessão expirou. Entre de novo para continuar.");
  location.reload(); // recarrega as telas com a sessao nova
}

async function iniciar() {
  montarAtividades(); atalhos(); iniciarTexto();
  ouvir("janela-fechada", () => { marcarAtual(); if (atual) history.replaceState(null, "", `#/${atual}`); });
  const nivel = $("#nivel");
  nivel.value = estado.nivel; definirNivel(estado.nivel);
  nivel.addEventListener("change", () => { definirNivel(nivel.value); config.definirPreferencia("nivel_detalhe", nivel.value).catch(() => {}); });
  document.addEventListener("forja:auth", sessaoExpirou);
  $("#usuario-atual").addEventListener("click", () => dialogoConta($("#usuario-atual").textContent));
  ouvir("ir", ir);
  ouvir("evento", (e) => {
    const t = String(e.tipo);
    if (/^(tarefa|execucao|aprovacao|conversa)\./.test(t)) agendarChip();
    if (t.startsWith("configuracao.")) config.recarregar().catch(() => {});
  });
  $("#atalho-precisa").addEventListener("click", () => ir("tarefas"));
  setInterval(() => { $("#st-hora").textContent = new Date().toLocaleTimeString("pt-BR"); }, 1000);

  mostrarUsuario(await garantirAcesso()); // so segue depois de um login valido (ou se o servidor nao exige login)
  direita.iniciar(); inferior.iniciar();
  ir((location.hash.match(/^#\/(\w+)/) || [])[1] || "tarefas");
  conectarSse(); atualizarChip();
  config.recarregar().catch(() => {});
  config.carregarPreferencias().catch(() => {});
  addEventListener("hashchange", () => { const id = (location.hash.match(/^#\/(\w+)/) || [])[1]; if (id && id !== atual) ir(id); });
}

iniciar();
