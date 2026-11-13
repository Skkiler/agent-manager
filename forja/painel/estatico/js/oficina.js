// Oficina pixel art: so PROJETA o estado real das execucoes (GET /oficina). Nada aqui decide ou executa; pode ser desligada.
// Um personagem por papel (planejador, executor, testador, revisor, estudante), animacao pelo tipo de acao, balao
// "aguardando voce" clicavel, barra de orcamento, replay da execucao e descricao em texto (aria-live). Respeita reduced motion.
import { api, consulta } from "./api.js";
import { emitir, ouvir, selecionarTarefa } from "./estado.js";
import { el, limpar, tag, toast } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
// Sprite 10x10: o contorno, p pele, c roupa (cor do papel), a acessorio (cor do papel), h cabelo, . vazio
const BASE = ["...hhhh...", "..hpppph..", "..pooppo..", "..pppppp..", "...pppp...", "..cccccc..", ".pcccccccp", ".p.cccc.p.", "...c..c...", "..oo..oo.."];
const ACESSORIO = { // pixels extras [x, y] por papel (desenho simples e distinguivel tambem em escala de cinza)
  planejador: [[2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [7, 0], [1, 1], [8, 1]], // chapeu largo
  executor: [[9, 5], [9, 6], [8, 4], [9, 4]], // martelo erguido
  testador: [[0, 5], [0, 6], [1, 4], [0, 4]], // lupa
  revisor: [[2, 2], [7, 2], [4, 2], [5, 2]], // oculos
  estudante: [[3, 7], [4, 7], [5, 7], [6, 7]], // livro
  simulado: [],
};
const PALETA = { planejador: ["#8b5cf6", "#facc15"], executor: ["#3b82f6", "#a16207"], testador: ["#16a34a", "#e5e7eb"],
  revisor: ["#db2777", "#111827"], estudante: ["#0d9488", "#f97316"], simulado: ["#6b7280", "#9ca3af"] };
const CORES = { o: "#1f2937", p: "#f1c27d", h: "#4b2e1a" };
const ROTULO_ACAO = { lendo: "📖", digitando: "⌨", comando: "▶", web: "🌐", pensando: "…", aguardando: "!", concluido: "✓", parado: "■" };

const st = { raiz: null, cena: null, lista: null, vivo: null, projeto: "", ultimoResumo: "", foco: null, quadro: null, replay: null, carregando: false };

function sprite(papel) {
  const [roupa, acc] = PALETA[papel] || PALETA.simulado;
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 10 10"); s.setAttribute("aria-hidden", "true"); s.setAttribute("shape-rendering", "crispEdges"); s.classList.add("sprite");
  const px = (x, y, cor) => { const r = document.createElementNS(NS, "rect"); r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", 1); r.setAttribute("height", 1); r.setAttribute("fill", cor); s.append(r); return r; };
  BASE.forEach((linha, y) => [...linha].forEach((ch, x) => { if (ch !== ".") px(x, y, ch === "c" ? roupa : CORES[ch]).classList.add(`px-${ch}`); }));
  for (const [x, y] of ACESSORIO[papel] || []) px(x, y, acc).classList.add("px-a");
  return s;
}

function cartaoAgente(a, indice) {
  const balao = a.aguardando
    ? el("button", { type: "button", className: "balao clicavel", textContent: a.aprovacoes_pendentes ? `aguardando você (${a.aprovacoes_pendentes})` : "aguardando você",
      title: "Abrir decisões e aprovações", onclick: (ev) => { ev.stopPropagation(); selecionarTarefa(a.tarefa_id); emitir("abrir-direita", "decisoes"); } })
    : el("span", { className: "balao", "aria-hidden": "true", textContent: ROTULO_ACAO[a.acao] || "…" });
  const orc = el("meter", { min: 0, max: 1, low: 0.6, high: 0.85, optimum: 0, value: a.orcamento, className: "orcamento",
    "aria-label": `Orçamento usado: ${Math.round(a.orcamento * 100)}%` });
  const detalhe = el("div", { className: "of-detalhe", role: "tooltip", id: `of-det-${a.execucao_id}` },
    el("strong", { textContent: a.titulo }), el("div", { textContent: `${a.papel_rotulo} · ${a.acao_rotulo}${a.nivel ? ` · tarefa ${a.nivel}` : ""}` }),
    el("div", { textContent: `Ferramentas: ${a.ferramentas}${a.max_ferramentas ? ` de ${a.max_ferramentas}` : ""}` }),
    a.max_chamadas_modelo ? el("div", { textContent: `Chamadas de modelo: ${a.chamadas_modelo} de ${a.max_chamadas_modelo}` }) : null,
    a.max_segundos ? el("div", { textContent: `Tempo: ${Math.round(a.segundos / 60)} de ${Math.round(a.max_segundos / 60)} min` }) : null,
    a.ultimo ? el("div", { className: "mudo", textContent: `Último: ${a.ultimo}` }) : null,
    el("div", { className: "mudo", textContent: "Enter: conversa · R: replay" }));
  const ag = el("div", { className: `of-agente papel-${a.papel} acao-${a.acao}${a.nivel ? ` nivel-${a.nivel}` : ""}${a.aguardando ? " precisa" : ""}`,
    role: "listitem", dataset: { id: a.execucao_id } },
    el("button", { type: "button", className: "of-corpo", tabIndex: indice === 0 ? 0 : -1, "aria-describedby": detalhe.id, "aria-label": a.descricao,
      onclick: () => { selecionarTarefa(a.tarefa_id); emitir("abrir-direita", a.aguardando ? "decisoes" : "conversa"); },
      onkeydown: (ev) => { if (ev.key.toLowerCase() === "r") { ev.preventDefault(); iniciarReplay(a.execucao_id); } } },
    el("span", { className: "palco", "aria-hidden": "true" }, sprite(a.papel), el("span", { className: "efeito" })), el("small", { className: "nome", textContent: a.titulo.slice(0, 24) })),
    balao, orc, detalhe,
    el("button", { type: "button", className: "pequeno", textContent: "Replay", "aria-label": `Replay de ${a.titulo}`, onclick: () => iniciarReplay(a.execucao_id) }));
  return ag;
}

/** Setas movem o foco entre personagens (tabindex movel), como numa grade. */
function navegar(ev) {
  if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(ev.key)) return;
  const bs = [...st.lista.querySelectorAll(".of-corpo")];
  const i = bs.indexOf(document.activeElement);
  if (i < 0) return;
  ev.preventDefault();
  const j = ev.key === "Home" ? 0 : ev.key === "End" ? bs.length - 1 : (i + (ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length;
  bs.forEach((b, k) => { b.tabIndex = k === j ? 0 : -1; });
  bs[j].focus();
}

async function atualizarCena() {
  if (!st.lista?.isConnected || st.carregando) return;
  st.carregando = true;
  try {
    const cena = await api("GET", `/oficina?${consulta({ projeto_id: st.projeto })}`);
    st.cena = cena;
    const focado = document.activeElement?.closest?.(".of-agente")?.dataset.id;
    limpar(st.lista);
    if (!cena.agentes.length) st.lista.append(el("p", { className: "mudo", textContent: "Oficina vazia: nenhuma execução ativa agora. Use 'Rever execução' para assistir uma que já terminou." }));
    cena.agentes.forEach((a, i) => st.lista.append(cartaoAgente(a, i)));
    if (focado) st.lista.querySelector(`.of-agente[data-id="${CSS.escape(focado)}"] .of-corpo`)?.focus();
    if (cena.resumo !== st.ultimoResumo) { st.ultimoResumo = cena.resumo; st.vivo.textContent = cena.resumo; } // so fala o que mudou
    const esperando = new Set(cena.agentes.filter((a) => a.aguardando).map((a) => a.execucao_id));
    if (st.esperando && [...esperando].some((id) => !st.esperando.has(id))) bipe();
    st.esperando = esperando;
  } catch (e) { limpar(st.lista); st.lista.append(el("p", { className: "aviso", textContent: e.message })); }
  finally { st.carregando = false; }
}

/** Som opcional (WebAudio, sem arquivo): so com a caixa marcada pelo usuario. */
function bipe() {
  if (localStorage.getItem("forja_oficina_som") !== "on") return;
  try {
    const ctx = new AudioContext(); const o = ctx.createOscillator(); const g = ctx.createGain();
    o.frequency.value = 660; g.gain.value = 0.05; o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.15); o.onended = () => ctx.close();
  } catch { /* sem audio: nada a fazer */ }
}

// ---------------------------------------------------------------- replay (quadro a quadro, a partir dos eventos gravados)
function pararReplay() {
  if (st.replay?.timer) clearTimeout(st.replay.timer);
  st.replay?.no?.remove();
  st.replay = null;
}

async function iniciarReplay(execucaoId) {
  pararReplay();
  let dados;
  try { dados = await api("GET", `/execucoes/${execucaoId}/replay`); } catch (e) { return toast(e.message, "erro"); }
  if (!dados.quadros.length) return toast("Sem eventos para reproduzir nesta execução.");
  const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const r = { dados, i: 0, tocando: !reduzido, velocidade: 1, timer: null };
  const palco = el("div", { className: "of-agente replay-ator", "aria-hidden": "true" });
  const legenda = el("p", { className: "replay-legenda", role: "status", "aria-live": "polite" });
  const barra = el("input", { type: "range", min: 0, max: dados.quadros.length - 1, value: 0, "aria-label": "Posição do replay",
    oninput: () => { r.i = Number(barra.value); mostrar(); } });
  const tocar = el("button", { type: "button", className: "primario", onclick: () => { r.tocando = !r.tocando; if (r.tocando && r.i >= dados.quadros.length - 1) r.i = 0; mostrar(); agendar(); } });
  const vel = el("select", { "aria-label": "Velocidade", onchange: () => { r.velocidade = Number(vel.value); agendar(); } },
    ...[1, 2, 4, 8].map((v) => el("option", { value: v, textContent: `${v}x` })));
  const passo = (d) => el("button", { type: "button", textContent: d < 0 ? "◀" : "▶", "aria-label": d < 0 ? "Quadro anterior" : "Próximo quadro",
    onclick: () => { r.tocando = false; r.i = Math.max(0, Math.min(dados.quadros.length - 1, r.i + d)); mostrar(); } });
  function mostrar() {
    const q = dados.quadros[r.i];
    limpar(palco);
    palco.className = `of-agente replay-ator papel-${q.papel} acao-${q.acao}`;
    palco.append(el("span", { className: "palco" }, sprite(q.papel), el("span", { className: "efeito" })), el("span", { className: "balao", textContent: ROTULO_ACAO[q.acao] || "…" }));
    legenda.textContent = `${q.t.toFixed(1)} s · ${q.texto} — ${q.descricao}`;
    barra.value = String(r.i);
    tocar.textContent = r.tocando ? "Pausar" : "Reproduzir";
  }
  function agendar() {
    clearTimeout(r.timer);
    if (!r.tocando || r.i >= dados.quadros.length - 1) { if (r.i >= dados.quadros.length - 1) { r.tocando = false; mostrar(); } return; }
    const atual = dados.quadros[r.i], prox = dados.quadros[r.i + 1];
    const ms = Math.max(250, Math.min(2000, ((prox.t - atual.t) * 1000) / r.velocidade));
    r.timer = setTimeout(() => { r.i += 1; mostrar(); agendar(); }, ms);
    st.replay = r;
  }
  r.no = el("section", { className: "replay card", "aria-label": `Replay: ${dados.titulo}` },
    el("div", { className: "linha" }, el("strong", { textContent: `Replay: ${dados.titulo}` }), tag(dados.estado), tag(`${dados.quadros.length} quadros · ${Math.round(dados.duracao)} s`),
      el("button", { type: "button", className: "fechar", "aria-label": "Fechar replay", textContent: "✕", onclick: pararReplay })),
    el("div", { className: "linha" }, palco, legenda),
    el("div", { className: "linha" }, passo(-1), tocar, passo(1), vel, barra));
  st.replay = r;
  st.raiz.append(r.no);
  mostrar(); agendar();
  tocar.focus();
}

function seletorRever() {
  const cartoes = (st.quadro?.colunas || []).filter((c) => ["concluida", "encerradas", "atencao", "executando"].includes(c.id)).flatMap((c) => c.cartoes).slice(0, 30);
  const s = el("select", { "aria-label": "Rever execução de uma tarefa", onchange: async () => {
    if (!s.value) return;
    try {
      const t = await api("GET", `/tarefas/${s.value}`);
      const ex = t.execucoes[t.execucoes.length - 1];
      if (!ex) toast("Essa tarefa ainda não executou."); else iniciarReplay(ex.id);
    } catch (e) { toast(e.message, "erro"); }
    s.value = "";
  } }, el("option", { value: "", textContent: "Rever execução…" }), ...cartoes.map((c) => el("option", { value: c.id, textContent: `${c.titulo.slice(0, 40)} (${c.estado})` })));
  return s;
}

/** Monta a oficina em `destino`. `quadro` (kanban) alimenta o filtro de projeto e a lista de replays. */
export function montarOficina(destino, quadro) {
  pararReplay();
  st.quadro = quadro;
  const projetos = [...new Map((quadro?.colunas || []).flatMap((c) => c.cartoes).map((c) => [c.projeto_id, c.projeto_id])).keys()];
  const filtro = el("select", { "aria-label": "Filtrar oficina por projeto", onchange: () => { st.projeto = filtro.value; atualizarCena(); } },
    el("option", { value: "", textContent: "Todos os projetos" }), ...projetos.map((p) => el("option", { value: p, textContent: p, selected: p === st.projeto })));
  st.lista = el("div", { className: "oficina", role: "list", "aria-label": "Agentes trabalhando agora", onkeydown: navegar });
  st.vivo = el("p", { className: "sr-only", role: "status", "aria-live": "polite" });
  st.ultimoResumo = "";
  const legenda = el("details", { className: "of-legenda" }, el("summary", { textContent: "Legenda" }),
    el("ul", {}, ...Object.entries(PALETA).map(([papel]) => el("li", { className: `papel-${papel}` }, sprite(papel), ` ${papel}`)),
      el("li", { textContent: "Animação = ação atual (lendo, editando, comando, web, pensando). Barra = orçamento usado (ferramentas, chamadas ou tempo, o que estiver mais perto do limite). Contorno = nível da tarefa (verde simples, azul normal, roxo complexa)." })));
  const som = el("label", { title: "Bipe curto quando uma tarefa passa a precisar de você (desligado por padrão)" },
    el("input", { type: "checkbox", checked: localStorage.getItem("forja_oficina_som") === "on",
      onchange: (ev) => localStorage.setItem("forja_oficina_som", ev.target.checked ? "on" : "off") }), " som ao precisar de você");
  st.raiz = el("div", { className: "oficina-raiz" }, el("div", { className: "linha" }, filtro, seletorRever(), som, legenda), st.vivo, st.lista);
  destino.append(st.raiz);
  atualizarCena();
}

/** Atualiza so a cena (sem recriar a barra e sem interromper um replay). */
export const atualizarOficina = (quadro) => { if (quadro) st.quadro = quadro; atualizarCena(); };

let espera = null;
ouvir("evento", (e) => {
  if (!st.lista?.isConnected || !/^(kiro|execucao|aprovacao|agente|tarefa)\./.test(String(e.tipo))) return;
  clearTimeout(espera); espera = setTimeout(atualizarCena, 600);
});
