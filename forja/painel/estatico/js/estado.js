// Estado compartilhado e barramento de eventos entre vistas (sem framework).
export const bus = new EventTarget();
export const emitir = (nome, detalhe) => bus.dispatchEvent(new CustomEvent(nome, { detail: detalhe }));
export const ouvir = (nome, fn) => bus.addEventListener(nome, (e) => fn(e.detail));

// Agrupa rajadas (ex.: replay do SSE ao conectar) numa unica chamada: evita tempestade de requisicoes e rate limit.
export function agrupar(fn, ms = 500) {
  let t = null;
  return () => { clearTimeout(t); t = setTimeout(fn, ms); };
}

export const estado = {
  nivel: localStorage.getItem("forja_nivel") || "simples",
  tarefaId: null,
  config: null, // ultima configuracao lida do servidor
};

export function definirNivel(n) {
  estado.nivel = n === "avancado" ? "avancado" : "simples";
  localStorage.setItem("forja_nivel", estado.nivel);
  document.body.dataset.nivel = estado.nivel;
  emitir("nivel", estado.nivel);
}

export function selecionarTarefa(id) {
  estado.tarefaId = id;
  emitir("tarefa", id);
}

// ---- paineis (lateral, direita, inferior): EMPURRAM o conteudo e tem divisorias (como no VS Code); em tela estreita viram
// gavetas por cima do conteudo (CSS). Fechados ficam inertes (fora do Tab). Aberto/fechado e tamanho ficam no localStorage.
export const PAINEIS = { lateral: "alternar-lateral", direita: "alternar-direita", inferior: "alternar-inferior" };
export const painelAberto = (nome) => document.getElementById("area")?.dataset[nome] === "on";

const lembrados = (() => { try { return JSON.parse(localStorage.getItem("forja_paineis") || "{}"); } catch { return {}; } })();
export const painelLembrado = (nome, padrao) => (nome in lembrados ? Boolean(lembrados[nome]) : padrao);

export function definirPainel(nome, ligado, { lembrar = true } = {}) {
  const area = document.getElementById("area");
  const painel = document.getElementById(nome);
  if (!area || !painel) return;
  if (!ligado && painel.contains(document.activeElement)) document.getElementById("principal")?.focus({ preventScroll: true });
  area.dataset[nome] = ligado ? "on" : "off";
  painel.inert = !ligado;
  document.getElementById(PAINEIS[nome])?.setAttribute("aria-pressed", String(ligado));
  if (lembrar) { lembrados[nome] = ligado; localStorage.setItem("forja_paineis", JSON.stringify(lembrados)); }
  emitir("painel", { nome, ligado });
}

export const alternarPainel = (nome) => definirPainel(nome, !painelAberto(nome));

// ---- modo da bancada: editor (VS Code/Kiro), chat (conversa em tela cheia) ou agentes (oficina pixel art)
export const MODOS = ["editor", "chat", "agentes"];
export function definirModo(modo) {
  const m = MODOS.includes(modo) ? modo : "editor";
  estado.modo = m;
  localStorage.setItem("forja_modo", m);
  document.getElementById("area").dataset.modo = m;
  for (const b of document.querySelectorAll("#modos button")) b.setAttribute("aria-pressed", String(b.dataset.modo === m));
  emitir("modo", m);
}
estado.modo = localStorage.getItem("forja_modo") || "editor";

// ---- tamanhos dos paineis (px), arrastados pelas divisorias
const TAMANHOS = { lateral: [170, 640, 280], direita: [300, 900, 420], inferior: [120, 900, 260] }; // [min, max, padrao]
const tamanhos = (() => { try { return JSON.parse(localStorage.getItem("forja_tamanhos") || "{}"); } catch { return {}; } })();
export function tamanhoPainel(nome, px, { salvar = true } = {}) {
  const [min, max, padrao] = TAMANHOS[nome];
  const v = Math.round(Math.max(min, Math.min(max, px ?? tamanhos[nome] ?? padrao)));
  document.getElementById("area")?.style.setProperty(`--w-${nome}`, `${v}px`);
  if (salvar) { tamanhos[nome] = v; localStorage.setItem("forja_tamanhos", JSON.stringify(tamanhos)); }
  return v;
}
export const tamanhoPadrao = (nome) => TAMANHOS[nome][2];
export const tamanhoAtual = (nome) => tamanhos[nome] ?? TAMANHOS[nome][2];
