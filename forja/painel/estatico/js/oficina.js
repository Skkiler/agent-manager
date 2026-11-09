// Oficina pixel art: apenas PROJETA o estado real das tarefas (nada aqui decide ou executa). Pode ser desligada.
import { el } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
// Sprite 8x8: o = contorno, p = pele, c = roupa (cor muda por estado), . = vazio
const SPRITE = ["..oooo..", ".oppppo.", ".opoopo.", ".oppppo.", "..occo..", ".occcco.", ".oc..co.", ".oo..oo."];
const CORES = { o: "#222", p: "#f1c27d" };

function boneco(corRoupa) {
  const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 8 8"); s.setAttribute("aria-hidden", "true"); s.setAttribute("shape-rendering", "crispEdges");
  SPRITE.forEach((linha, y) => [...linha].forEach((ch, x) => {
    if (ch === ".") return;
    const r = document.createElementNS(NS, "rect"); r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", 1); r.setAttribute("height", 1);
    r.setAttribute("fill", ch === "c" ? corRoupa : CORES[ch]); s.append(r);
  }));
  return s;
}

const ESTADOS = {
  executando: ["trabalhando", "#3fb950", "trabalhando"], validando: ["trabalhando", "#3fb950", "validando"], pronta: ["", "#3794ff", "pronta"], atribuida: ["", "#3794ff", "atribuida"],
  bloqueada: ["precisa", "#d29922", "espera voce"], aguardando_aprovacao: ["precisa", "#d29922", "aprovacao"],
};

export function desenharOficina(destino, quadro) {
  destino.replaceChildren();
  const cartoes = quadro.colunas.flatMap((c) => c.cartoes).filter((c) => ESTADOS[c.estado]).slice(0, 12);
  if (!cartoes.length) return destino.append(el("p", { className: "mudo", textContent: "Oficina vazia: nenhuma tarefa ativa agora." }));
  destino.append(el("div", { className: "oficina", role: "list", "aria-label": "Agentes e tarefas ativas" }, ...cartoes.map((c) => {
    const [cls, cor, rotulo] = ESTADOS[c.estado];
    const a = el("div", { className: `of-agente ${cls}`.trim(), role: "listitem", title: `${c.titulo} — ${c.estado}` }, boneco(cor), el("div", { className: "balao", textContent: rotulo }), el("small", { textContent: c.titulo.slice(0, 22) }));
    return a;
  })));
}
