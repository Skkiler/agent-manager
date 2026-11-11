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

// ---- paineis sobrepostos (lateral, direita, inferior): abrem POR CIMA do conteudo; fechados ficam inertes (fora do Tab)
export const PAINEIS = { lateral: "alternar-lateral", direita: "alternar-direita", inferior: "alternar-inferior" };
export const painelAberto = (nome) => document.getElementById("area")?.dataset[nome] === "on";

export function definirPainel(nome, ligado) {
  const area = document.getElementById("area");
  const painel = document.getElementById(nome);
  if (!area || !painel) return;
  if (!ligado && painel.contains(document.activeElement)) document.getElementById("principal")?.focus({ preventScroll: true });
  area.dataset[nome] = ligado ? "on" : "off";
  painel.inert = !ligado;
  document.getElementById(PAINEIS[nome])?.setAttribute("aria-pressed", String(ligado));
  emitir("painel", { nome, ligado });
}

export const alternarPainel = (nome) => definirPainel(nome, !painelAberto(nome));
