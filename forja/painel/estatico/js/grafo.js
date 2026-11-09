// Grafo de conhecimento em SVG (estilo Obsidian): layout de forcas, zoom/pan, arrastar nos, destaque de vizinhos.
// Sem animacao quando o usuario prefere movimento reduzido: o layout converge de uma vez.
const NS = "http://www.w3.org/2000/svg";
const CORES = { candidato: "#9d9d9d", observado: "#58a6ff", verificado: "#3fb950", validado: "#2ea043", contestado: "#f85149", obsoleto: "#8b949e", memoria: "#58a6ff", no: "#bc8cff", fantasma: "#9d9d9d" };
const svg = (nome, attrs = {}) => { const n = document.createElementNS(NS, nome); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };

export function corDoNo(n) { return n.grupo === "memoria" ? (CORES[n.estado] || CORES.memoria) : (CORES[n.grupo] || "#999"); }

export function simular(nos, arestas, largura, altura, passos = 220) {
  // Posicoes iniciais em espiral (deterministicas: o mesmo grafo gera o mesmo desenho).
  nos.forEach((n, i) => { const a = i * 2.4, r = 14 * Math.sqrt(i + 1); n.x ??= largura / 2 + r * Math.cos(a); n.y ??= altura / 2 + r * Math.sin(a); n.vx = 0; n.vy = 0; });
  const idx = new Map(nos.map((n) => [n.id, n]));
  const ligacoes = arestas.map((a) => [idx.get(a.origem), idx.get(a.destino)]).filter(([a, b]) => a && b);
  for (let p = 0; p < passos; p++) {
    const resfria = 1 - p / passos;
    for (let i = 0; i < nos.length; i++) for (let j = i + 1; j < nos.length; j++) {
      const a = nos[i], b = nos[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = Math.max(dx * dx + dy * dy, 25), d = Math.sqrt(d2);
      const f = 1800 / d2; dx /= d; dy /= d; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const [a, b] of ligacoes) {
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(Math.hypot(dx, dy), 1), f = (d - 70) * 0.02;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    }
    for (const n of nos) {
      n.vx += (largura / 2 - n.x) * 0.004; n.vy += (altura / 2 - n.y) * 0.004;
      n.x += Math.max(-12, Math.min(12, n.vx)) * resfria; n.y += Math.max(-12, Math.min(12, n.vy)) * resfria; n.vx *= 0.6; n.vy *= 0.6;
    }
  }
}

export function desenhar(caixa, grafo, { aoSelecionar, selecionado }) {
  caixa.replaceChildren();
  const L = caixa.clientWidth || 640, A = caixa.clientHeight || 420;
  const nos = grafo.nos.map((n) => ({ ...n })); // copia: o layout escreve x/y
  const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  simular(nos, grafo.arestas, L, A, reduzido || nos.length > 150 ? 260 : 220);
  const raiz = svg("svg", { viewBox: `0 0 ${L} ${A}`, role: "img", "aria-label": `Grafo com ${nos.length} notas e ${grafo.arestas.length} ligacoes. Use a lista de notas para navegar pelo teclado.` });
  const g = svg("g"); raiz.append(g);
  const idx = new Map(nos.map((n) => [n.id, n]));
  const linhas = grafo.arestas.map((a) => {
    const l = svg("line", { class: "aresta" }); l.dataset.o = a.origem; l.dataset.d = a.destino; g.append(l); return [l, a];
  });
  const raio = (n) => 5 + Math.min(n.grau, 12) * 1.1;
  const grupos = nos.map((n) => {
    const gn = svg("g", { class: `no${n.grupo === "fantasma" ? " fantasma" : ""}${n.id === selecionado ? " sel" : ""}`, tabindex: "-1" });
    const c = svg("circle", { r: raio(n), fill: corDoNo(n) }); const t = svg("text", { dx: raio(n) + 3, dy: 3 }); t.textContent = n.rotulo.length > 26 ? n.rotulo.slice(0, 25) + "…" : n.rotulo;
    const tit = svg("title"); tit.textContent = `${n.rotulo} — ${n.grupo === "memoria" ? `${n.tipo}, ${n.estado}` : n.grupo} (${n.grau} ligacoes)`;
    gn.append(c, t, tit); g.append(gn);
    gn.addEventListener("click", () => aoSelecionar(n));
    gn.addEventListener("mouseenter", () => linhas.forEach(([l, a]) => l.classList.toggle("destaque", a.origem === n.id || a.destino === n.id)));
    gn.addEventListener("mouseleave", () => linhas.forEach(([l]) => l.classList.remove("destaque")));
    gn.addEventListener("pointerdown", (ev) => arrastarNo(ev, n, atualizar, raiz));
    return [gn, n];
  });
  function atualizar() {
    for (const [l, a] of linhas) { const o = idx.get(a.origem), d = idx.get(a.destino); l.setAttribute("x1", o.x); l.setAttribute("y1", o.y); l.setAttribute("x2", d.x); l.setAttribute("y2", d.y); }
    for (const [gn, n] of grupos) gn.setAttribute("transform", `translate(${n.x},${n.y})`);
  }
  atualizar();
  zoomPan(raiz, g, L, A);
  caixa.append(raiz);
  const leg = document.createElement("div"); leg.className = "grafo-legenda";
  for (const [rot, cor] of [["candidato", CORES.candidato], ["verificado", CORES.verificado], ["validado", CORES.validado], ["no tipado", CORES.no], ["link nao resolvido", CORES.fantasma]]) {
    const s = document.createElement("span"); s.textContent = `● ${rot}`; s.style.color = cor; leg.append(s);
  }
  caixa.append(leg);
}

function pontoSvg(raiz, ev) { const p = raiz.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(raiz.getScreenCTM().inverse()); }

function arrastarNo(ev, n, atualizar, raiz) {
  ev.stopPropagation();
  const g = raiz.firstChild; const m = g.getScreenCTM().inverse();
  const mover = (e) => { const p = raiz.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(m); n.x = q.x; n.y = q.y; atualizar(); };
  const soltar = () => { removeEventListener("pointermove", mover); removeEventListener("pointerup", soltar); };
  addEventListener("pointermove", mover); addEventListener("pointerup", soltar);
}

function zoomPan(raiz, g, L, A) {
  let k = 1, tx = 0, ty = 0;
  const aplicar = () => g.setAttribute("transform", `translate(${tx},${ty}) scale(${k})`);
  raiz.addEventListener("wheel", (ev) => { ev.preventDefault(); const p = pontoSvg(raiz, ev); const f = ev.deltaY < 0 ? 1.12 : 1 / 1.12; const nk = Math.max(0.3, Math.min(4, k * f)); tx = p.x - ((p.x - tx) * nk) / k; ty = p.y - ((p.y - ty) * nk) / k; k = nk; aplicar(); }, { passive: false });
  raiz.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".no")) return;
    const x0 = ev.clientX, y0 = ev.clientY, tx0 = tx, ty0 = ty; const esc = L / raiz.clientWidth;
    const mover = (e) => { tx = tx0 + (e.clientX - x0) * esc; ty = ty0 + (e.clientY - y0) * esc; aplicar(); };
    const soltar = () => { removeEventListener("pointermove", mover); removeEventListener("pointerup", soltar); };
    addEventListener("pointermove", mover); addEventListener("pointerup", soltar);
  });
  void A;
}
