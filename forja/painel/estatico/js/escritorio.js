// Visualizacao agentica (inspirada no Pixel Agents): um escritorio em pixel art com uma sala por projeto e a sala do master.
// Cada execucao real vira um personagem na mesa (Kiro, Codex ou simulado) animado pela acao que o backend informa
// (GET /oficina). So PROJETA o estado; nada aqui decide ou executa. Arte propria, desenhada em codigo. A lista ao lado e o
// equivalente acessivel (teclado e leitor de tela); com "reduzir movimento" a cena fica parada.
import { api } from "./api.js";
import { agrupar, emitir, ouvir, selecionarTarefa } from "./estado.js";
import { el, limpar, tag } from "./ui.js";

const SALA = { l: 104, a: 70 }; // em "pixels de arte"
const CORPO = { kiro: ["#7c3aed", "#c4b5fd"], codex: ["#0f766e", "#99f6e4"], mock: ["#6b7280", "#d1d5db"], master: ["#b45309", "#fde68a"] };
const PELE = ["#f1c27d", "#e0ac69", "#c68642", "#8d5524"];
const CABELO = ["#2b1b10", "#4b2e1a", "#a16207", "#111827", "#7c2d12"];
const BALAO = { lendo: "lendo", digitando: "editando", comando: ">_", web: "web", pensando: "…", aguardando: "!", concluido: "✓", parado: "■" };
const reduzir = matchMedia("(prefers-reduced-motion: reduce)");
const st = { canvas: null, ctx: null, lista: null, dica: null, resumo: null, cena: null, projetos: [], master: null, alvos: [], escala: 3,
  t: 0, quadro: null, pausado: localStorage.getItem("forja_escritorio_pausa") === "1", carregando: false };

const hash = (s) => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

// ------------------------------------------------------------------ desenho
function px(x, y, w, h, cor) { st.ctx.fillStyle = cor; st.ctx.fillRect(x * st.escala, y * st.escala, w * st.escala, h * st.escala); }

function chao(x, y) {
  for (let i = 0; i < SALA.l; i += 8) for (let j = 16; j < SALA.a; j += 8) px(x + i, y + j, 8, 8, ((i + j) / 8) % 2 ? "#c9a46c" : "#bf9a62");
  px(x, y, SALA.l, 16, "#5b6b7a"); px(x, y + 14, SALA.l, 2, "#46525e"); // parede e rodape
  px(x + SALA.l - 22, y + 3, 16, 9, "#9fd3f0"); px(x + SALA.l - 22, y + 7, 16, 1, "#dff3fb"); px(x + SALA.l - 15, y + 3, 1, 9, "#7aa8c2"); // janela
  px(x + 3, y + 52, 6, 8, "#7c4a1e"); px(x + 2, y + 44, 8, 9, "#2f855a"); px(x + 4, y + 42, 4, 3, "#38a169"); // planta
  px(x, y, SALA.l, 1, "#2d3640"); px(x, y + SALA.a - 1, SALA.l, 1, "#8a6a3e"); px(x, y, 1, SALA.a, "#2d3640"); px(x + SALA.l - 1, y, 1, SALA.a, "#2d3640");
}

function placa(x, y, texto, destaque) {
  const c = st.ctx, e = st.escala;
  c.font = `${Math.max(9, 4 * e)}px ui-monospace, Consolas, monospace`;
  const w = Math.min(SALA.l - 30, Math.ceil(c.measureText(texto).width / e) + 6);
  px(x + 4, y + 3, w, 8, destaque ? "#fbbf24" : "#e5e7eb"); px(x + 4, y + 10, w, 1, "#9ca3af");
  c.fillStyle = "#111827"; c.textBaseline = "middle";
  c.save(); c.beginPath(); c.rect((x + 4) * e, (y + 3) * e, w * e, 8 * e); c.clip();
  c.fillText(texto, (x + 7) * e, (y + 7.2) * e); c.restore();
}

function mesa(x, y, tela, quadro) {
  px(x - 1, y + 9, 22, 2, "#00000022"); // sombra
  px(x, y, 20, 6, "#8b5a2b"); px(x, y, 20, 1, "#a8743f"); px(x + 1, y + 6, 2, 5, "#6b4423"); px(x + 17, y + 6, 2, 5, "#6b4423"); // tampo e pernas
  px(x + 1, y - 7, 9, 7, "#1f2937"); px(x + 5, y - 1, 2, 1, "#374151"); // monitor (lado esquerdo: o rosto fica visivel)
  const cor = { digitando: "#60a5fa", lendo: "#e5e7eb", comando: "#064e3b", web: "#38bdf8", pensando: "#a78bfa", aguardando: "#fbbf24", concluido: "#34d399", parado: "#374151" }[tela] || "#111827";
  px(x + 2, y - 6, 7, 5, cor);
  if (tela === "comando" && quadro % 2) px(x + 3, y - 3, 3, 1, "#34d399");
  if (tela === "digitando" || tela === "lendo") for (let k = 0; k < 3; k += 1) px(x + 3, y - 5 + k * 1.5, (quadro + k) % 3 + 3, 0.6, "#1e3a8a");
}

function personagem(x, y, tipo, semente, acao, quadro, coroa) {
  const [roupa, detalhe] = CORPO[tipo] || CORPO.mock;
  const pele = PELE[semente % PELE.length], cabelo = CABELO[(semente >> 3) % CABELO.length];
  const sobe = acao === "aguardando" && quadro % 2 ? -1 : 0;
  y += sobe;
  px(x + 2, y + 1, 6, 2, cabelo); px(x + 1, y + 2, 8, 2, cabelo); // cabelo
  px(x + 2, y + 3, 6, 5, pele); px(x + 1, y + 4, 1, 2, pele); px(x + 8, y + 4, 1, 2, pele); // rosto e orelhas
  const piscar = quadro % 12 === 0;
  px(x + 3, y + 5, 1, piscar ? 0.4 : 1, "#111827"); px(x + 6, y + 5, 1, piscar ? 0.4 : 1, "#111827"); // olhos
  px(x + 4, y + 7, 2, 0.6, "#9a3412");
  px(x + 1, y + 8, 8, 6, roupa); px(x + 4, y + 8, 2, 2, detalhe); // tronco
  const braco = acao === "digitando" ? quadro % 2 : 0;
  px(x, y + 9, 1, 4 - braco, roupa); px(x + 9, y + 9, 1, 4 - (1 - braco) * (acao === "digitando" ? 1 : 0), roupa);
  px(x, y + 13 - braco, 1, 1, pele); px(x + 9, y + 13, 1, 1, pele); // maos
  if (acao === "lendo") { px(x + 2, y + 11, 6, 3, "#1d4ed8"); px(x + 4.8, y + 11, 0.4, 3, "#bfdbfe"); }
  if (coroa) { px(x + 2, y - 1, 6, 1, "#fbbf24"); px(x + 2, y - 2, 1, 1, "#fbbf24"); px(x + 4.5, y - 2, 1, 1, "#fbbf24"); px(x + 7, y - 2, 1, 1, "#fbbf24"); }
  if (tipo === "codex") { px(x + 2, y + 1, 6, 1, "#e5e7eb"); } // faixa clara: distingue Codex de Kiro tambem em escala de cinza
}

function balao(x, y, texto, tipo) {
  const c = st.ctx, e = st.escala;
  c.font = `bold ${Math.max(9, 3.6 * e)}px ui-sans-serif, Segoe UI, sans-serif`;
  const w = Math.max(8, Math.ceil(c.measureText(texto).width / e) + 4);
  const cor = tipo === "aguardando" ? "#fbbf24" : tipo === "concluido" ? "#bbf7d0" : "#ffffff";
  px(x - w / 2, y - 7, w, 6, cor); px(x - w / 2 + 1, y - 8, w - 2, 1, cor); px(x - w / 2 + 1, y - 1, w - 2, 1, cor); px(x - 1, y, 2, 1.5, cor);
  c.fillStyle = "#111827"; c.textBaseline = "middle"; c.textAlign = "center";
  c.fillText(texto, x * e, (y - 4) * e); c.textAlign = "left";
}

function rotulo(x, y, texto) {
  const c = st.ctx, e = st.escala;
  c.font = `${Math.max(8, 3.2 * e)}px ui-sans-serif, Segoe UI, sans-serif`;
  c.fillStyle = "#1f2937"; c.textBaseline = "top"; c.textAlign = "center";
  c.fillText(texto.length > 16 ? `${texto.slice(0, 15)}…` : texto, x * e, y * e); c.textAlign = "left";
}

function salas() {
  const ag = st.cena?.agentes || [];
  const comAgente = new Set(ag.map((a) => a.projeto_id));
  const lista = [{ id: "__master", nome: "Sala do master", agentes: [], master: true },
    ...st.projetos.filter((p) => comAgente.has(p.id) || (p.pastas || []).length).slice(0, 11).map((p) => ({ id: p.id, nome: p.nome, agentes: [] }))];
  for (const a of ag) {
    let s = lista.find((x) => x.id === a.projeto_id);
    if (!s) { s = { id: a.projeto_id, nome: a.projeto_id, agentes: [] }; lista.push(s); }
    s.agentes.push(a);
  }
  return lista;
}

function desenhar() {
  const c = st.canvas;
  if (!c?.isConnected) return;
  const ctx = st.ctx;
  const lista = salas();
  const largura = c.parentElement.clientWidth;
  st.escala = Math.floor((largura / 3 - 4) / (SALA.l + 4)) >= Math.min(lista.length, 3) ? 3 : 2; // pelo menos 3 salas por linha quando cabe
  const colunas = Math.max(1, Math.floor((largura / st.escala - 4) / (SALA.l + 4)));
  const linhas = Math.ceil(lista.length / colunas);
  const W = colunas * (SALA.l + 4) + 4, H = linhas * (SALA.a + 4) + 4;
  const dpr = devicePixelRatio || 1;
  if (c.width !== Math.round(W * st.escala * dpr) || c.height !== Math.round(H * st.escala * dpr)) {
    c.width = Math.round(W * st.escala * dpr); c.height = Math.round(H * st.escala * dpr);
    c.style.width = `${W * st.escala}px`; c.style.height = `${H * st.escala}px`;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.imageSmoothingEnabled = false;
  px(0, 0, W, H, "#2b2f36");
  st.alvos = [];
  const q = st.quadro;
  lista.forEach((s, i) => {
    const x = 4 + (i % colunas) * (SALA.l + 4), y = 4 + Math.floor(i / colunas) * (SALA.a + 4);
    chao(x, y);
    const esperando = s.agentes.some((a) => a.aguardando);
    placa(x, y, s.master ? "★ Master" : s.nome, esperando);
    if (s.master) {
      const m = st.master;
      const ativo = Boolean(m?.submasters?.length || m?.master?.chamadas_usadas);
      const mx = x + 40, my = y + 26;
      personagem(mx + 10, my - 12, "master", 3, ativo ? "pensando" : "", q, true);
      mesa(mx, my, ativo ? "pensando" : "", q);
      balao(mx + 15, my - 13, m?.submasters?.length ? `${m.submasters.length} sub` : ativo ? "…" : "zz", ativo ? "pensando" : "");
      rotulo(mx + 10, my + 12, "Master");
      st.alvos.push({ x: mx * st.escala, y: (my - 20) * st.escala, w: 22 * st.escala, h: 30 * st.escala, master: true, texto: "Master: clique para conversar" });
      return;
    }
    const n = Math.max(2, Math.min(4, s.agentes.length || 2));
    for (let k = 0; k < n; k += 1) {
      const dx = x + 14 + k * ((SALA.l - 24) / n), dy = y + 30 + (k % 2) * 16;
      const a = s.agentes[k];
      if (a) {
        const sem = hash(a.execucao_id);
        const fq = q + (sem % 5);
        personagem(dx + 10, dy - 12, a.agente === "kiro" || a.agente === "codex" ? a.agente : "mock", sem, a.acao, fq, false);
        mesa(dx, dy, a.acao, fq);
        if (a.acao !== "digitando" || fq % 6 < 3) balao(dx + 15, dy - 13, a.aguardando ? "!" : BALAO[a.acao] || "…", a.aguardando ? "aguardando" : a.acao);
        rotulo(dx + 10, dy + 12, a.titulo);
        st.alvos.push({ x: dx * st.escala, y: (dy - 20) * st.escala, w: 22 * st.escala, h: 30 * st.escala, agente: a,
          texto: `${a.titulo}\n${nomeAgente(a)} · ${a.papel_rotulo} · ${a.acao_rotulo}${a.aguardando ? " · aguardando você" : ""}` });
      } else {
        px(dx + 11, dy - 5, 8, 5, "#4b5563"); px(dx + 11, dy - 6, 8, 1, "#6b7280"); // cadeira vazia (encosto atras da mesa)
        mesa(dx, dy, "", 0);
      }
    }
    if (s.agentes.length > 4) rotulo(x + SALA.l - 14, y + SALA.a - 7, `+${s.agentes.length - 4}`);
  });
}

const nomeAgente = (a) => ({ kiro: "Kiro", codex: "Codex", mock: "Simulado" }[a.agente] || a.agente || "agente");

// ------------------------------------------------------------------ dados, laco e interacao
async function carregar() {
  if (st.carregando) return;
  st.carregando = true;
  try {
    const [cena, projetos, master] = await Promise.all([api("GET", "/oficina"), api("GET", "/projetos").catch(() => []), api("GET", "/master").catch(() => null)]);
    st.cena = cena; st.projetos = projetos; st.master = master;
    st.resumo.textContent = cena.resumo;
    st.canvas.setAttribute("aria-label", `Escritório dos agentes. ${cena.resumo}`);
    desenharLista();
    desenhar();
  } catch (e) { st.resumo.textContent = `Não foi possível carregar a oficina: ${e.message}`; }
  finally { st.carregando = false; }
}
const recarregar = agrupar(() => { if (st.canvas?.isConnected) carregar(); }, 700);

function desenharLista() {
  limpar(st.lista);
  const ag = st.cena?.agentes || [];
  st.lista.append(el("li", {}, el("button", { type: "button", className: "bloco", onclick: () => emitir("abrir-direita", "master") }, "★ Master — conversar")));
  for (const a of ag) {
    st.lista.append(el("li", {}, el("button", { type: "button", className: `bloco${a.aguardando ? " precisa" : ""}`, title: a.descricao, onclick: () => abrir(a) },
      el("span", { className: `ponto agente-${a.agente}`, "aria-hidden": "true" }),
      el("span", { className: "trunc", textContent: `${a.titulo}` }), tag(a.aguardando ? "aguardando você" : a.acao_rotulo, a.aguardando ? "aviso" : ""),
      el("span", { className: "sr-only", textContent: `${nomeAgente(a)}, ${a.papel_rotulo}` }))));
  }
  if (!ag.length) st.lista.append(el("li", { className: "mudo", textContent: "Nenhum agente trabalhando agora. Execute uma tarefa ou faça um pedido ao master." }));
}

function abrir(a) { selecionarTarefa(a.tarefa_id); emitir("abrir-direita", a.aguardando ? "decisoes" : "conversa"); }

function alvoEm(ev) {
  const r = st.canvas.getBoundingClientRect();
  const x = ev.clientX - r.left, y = ev.clientY - r.top;
  return st.alvos.find((t) => x >= t.x && x <= t.x + t.w && y >= t.y && y <= t.y + t.h);
}

function laco(agora) {
  if (!st.canvas?.isConnected) return;
  if (!st.pausado && !reduzir.matches && !document.hidden && agora - st.t > 160) { st.t = agora; st.quadro = (st.quadro || 0) + 1; desenhar(); }
  requestAnimationFrame(laco);
}

export function montar(raiz) {
  limpar(raiz);
  st.canvas = el("canvas", { className: "escritorio-cena", role: "img", "aria-label": "Escritório dos agentes" });
  st.ctx = st.canvas.getContext("2d");
  st.quadro = 0;
  st.lista = el("ul", { className: "escritorio-lista", "aria-label": "Agentes trabalhando agora" });
  st.dica = el("div", { className: "escritorio-dica", role: "tooltip", hidden: true });
  st.resumo = el("p", { className: "mudo", role: "status", "aria-live": "polite" });
  const pausa = el("button", { type: "button", className: "pequeno", "aria-pressed": String(st.pausado), textContent: st.pausado ? "Retomar animação" : "Pausar animação",
    onclick: () => { st.pausado = !st.pausado; localStorage.setItem("forja_escritorio_pausa", st.pausado ? "1" : "0"); pausa.textContent = st.pausado ? "Retomar animação" : "Pausar animação"; pausa.setAttribute("aria-pressed", String(st.pausado)); } });
  const palco = el("div", { className: "escritorio-palco" }, st.canvas, st.dica);
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Agentes" }), el("div", { className: "linha" }, pausa,
    el("button", { type: "button", className: "pequeno", textContent: "Atualizar", onclick: carregar }))),
  el("div", { className: "escritorio" }, palco, el("aside", { className: "escritorio-lado", "aria-label": "Lista de agentes" }, st.resumo, st.lista,
    el("p", { className: "mudo legenda" }, el("span", { className: "ponto agente-kiro" }), " Kiro  ", el("span", { className: "ponto agente-codex" }), " Codex  ",
      el("span", { className: "ponto agente-mock" }), " simulado · clique num personagem para abrir a conversa"))));
  st.canvas.addEventListener("pointermove", (ev) => {
    const t = alvoEm(ev);
    st.canvas.style.cursor = t ? "pointer" : "default";
    st.dica.hidden = !t;
    if (t) { st.dica.textContent = t.texto; st.dica.style.left = `${t.x + t.w}px`; st.dica.style.top = `${t.y}px`; }
  });
  st.canvas.addEventListener("pointerleave", () => { st.dica.hidden = true; });
  st.canvas.addEventListener("click", (ev) => { const t = alvoEm(ev); if (t?.master) emitir("abrir-direita", "master"); else if (t?.agente) abrir(t.agente); });
  new ResizeObserver(() => desenhar()).observe(palco);
  carregar();
  requestAnimationFrame(laco);
}

ouvir("evento", (e) => { if (/^(execucao|kiro|codex|aprovacao|tarefa|coordenacao)\./.test(String(e.tipo))) recarregar(); });
reduzir.addEventListener?.("change", () => desenhar());
