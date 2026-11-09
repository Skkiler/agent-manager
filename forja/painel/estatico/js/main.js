// Shell do orquestrador: barra de atividades, barra lateral, area principal, conversa/decisoes, painel inferior e SSE.
import { api, definirToken, lerToken } from "./api.js";
import * as direita from "./direita.js";
import { agrupar, definirNivel, emitir, estado, ouvir } from "./estado.js";
import * as inferior from "./inferior.js";
import { $, el, limpar } from "./ui.js";
import * as config from "./views/config.js";
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
  { id: "config", rotulo: "Config", glifo: "⚙", modulo: config },
];
let atual = null;
let fonte = null;
const vistos = new Set();

function ir(id) {
  const v = VISTAS.find((x) => x.id === id) || VISTAS[0];
  atual = v.id;
  if (location.hash !== `#/${v.id}`) history.replaceState(null, "", `#/${v.id}`);
  for (const b of document.querySelectorAll("#atividades button")) b.setAttribute("aria-current", b.dataset.id === v.id ? "page" : "false");
  const lat = $("#lateral");
  limpar(lat); v.modulo.montarLateral?.(lat);
  v.modulo.montar($("#principal"));
  $("#principal").setAttribute("aria-label", v.rotulo);
}

function montarAtividades() {
  const nav = $("#atividades");
  nav.append(...VISTAS.map((v) => el("button", { type: "button", dataset: { id: v.id }, title: v.rotulo, "aria-label": v.rotulo, onclick: () => ir(v.id) },
    el("span", { className: "glifo", "aria-hidden": "true", textContent: v.glifo }), el("span", { textContent: v.rotulo }))));
  // Navegacao por setas ↑/↓ entre as areas (padrao de barras de atividade de IDEs)
  nav.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    const bs = [...nav.querySelectorAll("button")]; const i = bs.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault(); bs[(i + (ev.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length].focus();
  });
}

function alternar(id, atributo, botao) {
  const area = $("#area");
  const ligado = area.dataset[atributo] !== "off";
  area.dataset[atributo] = ligado ? "off" : "on";
  $(botao).setAttribute("aria-pressed", String(!ligado));
  if (id === "memoria") window.dispatchEvent(new Event("resize"));
}

function atalhos() {
  $("#alternar-lateral").addEventListener("click", () => alternar("lateral", "lateral", "#alternar-lateral"));
  $("#alternar-direita").addEventListener("click", () => alternar("direita", "direita", "#alternar-direita"));
  $("#alternar-inferior").addEventListener("click", () => alternar("inferior", "inferior", "#alternar-inferior"));
  document.addEventListener("keydown", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey)) return;
    const k = ev.key.toLowerCase();
    if (k === "b" && ev.shiftKey) { ev.preventDefault(); alternar("direita", "direita", "#alternar-direita"); }
    else if (k === "b") { ev.preventDefault(); alternar("lateral", "lateral", "#alternar-lateral"); }
    else if (k === "j") { ev.preventDefault(); alternar("inferior", "inferior", "#alternar-inferior"); }
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

async function autenticarSeNecessario() {
  try { await api("GET", "/configuracao"); return true; } catch (e) { if (e.status !== 401) return true; }
  const d = $("#dlg-token");
  d.showModal();
  return new Promise((resolver) => {
    $("#form-token").addEventListener("submit", () => { definirToken($("#token").value); $("#token").value = ""; resolver(true); }, { once: true });
  });
}

async function iniciar() {
  montarAtividades(); atalhos();
  const nivel = $("#nivel");
  nivel.value = estado.nivel; definirNivel(estado.nivel);
  nivel.addEventListener("change", () => definirNivel(nivel.value));
  document.addEventListener("forja:auth", () => { if (!$("#dlg-token").open) autenticarSeNecessario().then(() => location.reload()); });
  ouvir("ir", ir);
  ouvir("evento", (e) => {
    const t = String(e.tipo);
    if (/^(tarefa|execucao|aprovacao|conversa)\./.test(t)) agendarChip();
    if (t.startsWith("configuracao.")) config.recarregar().catch(() => {});
  });
  $("#atalho-precisa").addEventListener("click", () => ir("tarefas"));
  setInterval(() => { $("#st-hora").textContent = new Date().toLocaleTimeString("pt-BR"); }, 1000);

  await autenticarSeNecessario();
  direita.iniciar(); inferior.iniciar();
  ir((location.hash.match(/^#\/(\w+)/) || [])[1] || "tarefas");
  conectarSse(); atualizarChip();
  config.recarregar().catch(() => {});
  addEventListener("hashchange", () => { const id = (location.hash.match(/^#\/(\w+)/) || [])[1]; if (id && id !== atual) ir(id); });
}

iniciar();
