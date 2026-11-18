// Painel inferior: Problemas (do arquivo aberto), Terminal (um comando por vez na pasta de trabalho), Eventos (SSE com
// filtro), Controle do master e Oficina pixel art.
import { api } from "./api.js";
import { abas as abasEditor, ativar } from "./bancada.js";
import { definirPainel, ouvir } from "./estado.js";
import { atualizarOficina, montarOficina } from "./oficina.js";
import { abas, dataCurta, el, limpar, tag } from "./ui.js";
import { definirPreferencia } from "./views/config.js";

const ABAS = [{ id: "problemas", rotulo: "Problemas" }, { id: "terminal", rotulo: "Terminal" }, { id: "eventos", rotulo: "Eventos" },
  { id: "controle", rotulo: "Controle" }, { id: "oficina", rotulo: "Oficina" }];
let aba = localStorage.getItem("forja_aba_inferior") || "eventos";
let oficinaLigada = localStorage.getItem("forja_oficina") !== "off";
let ultimoQuadro = null;
const eventos = [];
const problemas = new Map(); // chave da aba do editor -> { titulo, itens }
const terminal = { historico: [], comandos: [], indice: -1, rodando: false };
let filtroEventos = { texto: "", tipo: "" };

// ------------------------------------------------------------------ Problemas
function listaProblemas(corpo) {
  const grupos = [...problemas.entries()].filter(([, g]) => g.itens.length);
  if (!grupos.length) return corpo.append(el("p", { className: "mudo", textContent: "Nenhum problema nos arquivos abertos (JSON e Python são verificados ao abrir, editar e salvar)." }));
  for (const [chave, g] of grupos) {
    corpo.append(el("details", { open: true, className: "grupo-problemas" }, el("summary", { textContent: `${g.titulo} (${g.itens.length})` }),
      el("ul", { className: "lista-problemas" }, ...g.itens.map((p) => el("li", {}, el("button", { type: "button", className: "bloco", onclick: () => irProblema(chave, p) },
        el("span", { className: `sev sev-${p.gravidade}`, "aria-label": p.gravidade, textContent: p.gravidade === "erro" ? "⊗" : "⚠" }),
        el("span", { className: "trunc", textContent: p.mensagem }), el("span", { className: "mudo", textContent: `${p.codigo} · Ln ${p.linha}, Col ${p.coluna}` })))))));
  }
}
function irProblema(chave, p) {
  const a = abasEditor().find((x) => x.chave === chave);
  if (!a) return;
  ativar(chave);
  requestAnimationFrame(() => a.editor?.irPara(p.linha, p.coluna));
}

// ------------------------------------------------------------------ Terminal
async function montarTerminal(corpo) {
  let lista = [];
  try { lista = (await api("GET", "/projetos")).filter((p) => (p.pastas || []).some((x) => x.papel === "trabalho")); } catch { lista = []; }
  if (!lista.length) return corpo.append(el("p", { className: "mudo", textContent: "O terminal roda na pasta de TRABALHO de um projeto. Crie um projeto com pasta de trabalho primeiro." }));
  const opcoes = lista.flatMap((p) => p.pastas.map((x, i) => [p, x, i]).filter(([, x]) => x.papel === "trabalho"));
  const sel = el("select", { "aria-label": "Pasta onde o comando roda" }, ...opcoes.map(([p, x, i]) => el("option", { value: `${p.id}|${i}`, textContent: `${p.nome} · ${x.caminho.split(/[\\/]/).pop()}` })));
  const salvo = localStorage.getItem("forja_terminal_pasta");
  if (salvo && opcoes.some(([p, , i]) => `${p.id}|${i}` === salvo)) sel.value = salvo;
  sel.addEventListener("change", () => localStorage.setItem("forja_terminal_pasta", sel.value));
  const saida = el("div", { className: "terminal-saida", role: "log", "aria-live": "polite", "aria-label": "Saída do terminal", tabIndex: 0 });
  const entrada = el("input", { type: "text", className: "terminal-entrada", maxLength: 2000, spellcheck: false, autocomplete: "off",
    "aria-label": "Comando do terminal (Enter executa; ↑/↓ histórico)", placeholder: "comando (ex.: git status, pytest -q, npm test)", disabled: terminal.rodando });
  const desenharSaida = () => {
    limpar(saida);
    for (const h of terminal.historico) {
      saida.append(el("div", { className: "terminal-cmd" }, el("span", { className: "prompt", textContent: `${h.pasta} ❯ ` }), el("span", { textContent: h.comando }),
        h.codigo === null ? tag("rodando…") : tag(h.tempo_esgotado ? "tempo esgotado" : `código ${h.codigo}`, h.codigo === 0 ? "ok" : "erro")),
      h.saida ? el("pre", { className: "terminal-texto", textContent: h.saida }) : null);
    }
    if (!terminal.historico.length) saida.append(el("p", { className: "mudo", textContent:
      "Um comando por vez, sem shell interativo, com ambiente limpo e tempo máximo de 2 minutos. Comandos que leem segredos (.env, variáveis de ambiente) são recusados." }));
    saida.scrollTop = saida.scrollHeight;
  };
  const executar = async () => {
    const comando = entrada.value.trim();
    if (!comando || terminal.rodando) return;
    const [projeto, raiz] = sel.value.split("|");
    if (comando === "clear" || comando === "cls") { terminal.historico = []; entrada.value = ""; return desenharSaida(); }
    const h = { comando, pasta: sel.selectedOptions[0]?.textContent.split(" · ").pop() || "", codigo: null, saida: "" };
    terminal.historico.push(h); terminal.historico = terminal.historico.slice(-40);
    terminal.comandos = [comando, ...terminal.comandos.filter((c) => c !== comando)].slice(0, 50); terminal.indice = -1;
    entrada.value = ""; terminal.rodando = true; entrada.disabled = true; desenharSaida();
    try { Object.assign(h, await api("POST", "/area/terminal", { projeto, raiz: Number(raiz), comando })); }
    catch (e) { h.codigo = -1; h.saida = e.message; }
    terminal.rodando = false;
    if (entrada.isConnected) { entrada.disabled = false; entrada.focus(); }
    desenharSaida();
  };
  entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); executar(); }
    else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
      ev.preventDefault();
      terminal.indice = Math.max(-1, Math.min(terminal.comandos.length - 1, terminal.indice + (ev.key === "ArrowUp" ? 1 : -1)));
      entrada.value = terminal.indice < 0 ? "" : terminal.comandos[terminal.indice];
    }
  });
  corpo.append(el("div", { className: "terminal" }, saida, el("div", { className: "linha terminal-linha" }, sel, entrada,
    el("button", { type: "button", className: "pequeno", textContent: "Executar", onclick: executar }),
    el("button", { type: "button", className: "pequeno", textContent: "Limpar", onclick: () => { terminal.historico = []; desenharSaida(); } }))));
  desenharSaida();
  requestAnimationFrame(() => entrada.focus({ preventScroll: true }));
}

// ------------------------------------------------------------------ Eventos
const ICONE_EVENTO = { tarefa: "▦", execucao: "▶", aprovacao: "✋", conversa: "💬", kiro: "◆", codex: "◇", memoria: "◉", coordenacao: "✦",
  configuracao: "⚙", agente: "¤", status: "•" };
function listaEventos(corpo) {
  const tipos = [...new Set(eventos.map((e) => String(e.tipo).split(".")[0]))].sort();
  const filtro = el("input", { type: "search", placeholder: "Filtrar eventos", "aria-label": "Filtrar eventos", value: filtroEventos.texto });
  const tipo = el("select", { "aria-label": "Tipo de evento" }, el("option", { value: "", textContent: "Todos" }),
    ...tipos.map((t) => el("option", { value: t, textContent: t, selected: t === filtroEventos.tipo })));
  const lista = el("ul", { id: "eventos", "aria-label": "Eventos" });
  const desenhar = () => {
    filtroEventos = { texto: filtro.value, tipo: tipo.value };
    const q = filtro.value.toLowerCase();
    const vis = eventos.filter((e) => (!tipo.value || String(e.tipo).startsWith(`${tipo.value}.`)) && (!q || `${e.tipo} ${e.tarefa_id || ""}`.toLowerCase().includes(q)));
    limpar(lista);
    lista.append(...vis.slice(0, 200).map((e) => {
      const grupo = String(e.tipo).split(".")[0];
      return el("li", { className: `ev ev-${grupo}` }, el("span", { className: "ev-ico", "aria-hidden": "true", textContent: ICONE_EVENTO[grupo] || "·" }),
        el("time", { className: "mudo", dateTime: e.ts, textContent: e.ts ? new Date(e.ts).toLocaleTimeString("pt-BR") : "" }),
        el("span", { className: "ev-tipo", textContent: e.tipo }), e.tarefa_id ? el("span", { className: "mudo", textContent: e.tarefa_id }) : null,
        el("span", { className: "mudo so-avancado", textContent: `#${e.seq}` }));
    }));
    if (!vis.length) lista.append(el("li", { className: "mudo", textContent: eventos.length ? "Nenhum evento com esse filtro." : "Aguardando eventos do servidor (tempo real)." }));
  };
  filtro.addEventListener("input", desenhar); tipo.addEventListener("change", desenhar);
  corpo.append(el("div", { className: "linha filtros-eventos" }, filtro, tipo), lista);
  desenhar();
}

async function controle(corpo) {
  try {
    const p = await api("GET", "/controle/painel");
    corpo.append(el("div", { className: "alertas" }, ...(p.alertas.length ? p.alertas.map((a) => tag(a, "aviso")) : [tag("Nada exige atenção agora", "ok")])),
      el("div", { className: "linha so-avancado" }, tag(`quadro: ${p.quadro.abertas} abertas`), ...Object.entries(p.tarefas.por_estado).map(([k, v]) => tag(`${k}: ${v}`)), tag(`gerado ${dataCurta(p.gerado_em)}`)),
      p.tarefas.aguardando_decisao.length ? el("p", { textContent: `Aguardando decisão: ${p.tarefas.aguardando_decisao.map((t) => t.titulo).join("; ")}` }) : null,
      p.execucoes_paradas.length ? el("p", { className: "aviso", textContent: `Execuções vencidas ou sem progresso: ${p.execucoes_paradas.map((e) => e.id).join(", ")}` }) : null);
  } catch (e) { corpo.append(el("p", { className: "aviso", textContent: e.message })); }
}

function oficina(corpo) {
  const alternar = el("button", { type: "button", "aria-pressed": String(oficinaLigada), textContent: oficinaLigada ? "Desligar oficina" : "Ligar oficina",
    onclick: () => { oficinaLigada = !oficinaLigada; renderizar(); definirPreferencia("oficina_pixel", oficinaLigada).catch(() => localStorage.setItem("forja_oficina", oficinaLigada ? "on" : "off")); } });
  const cena = el("div");
  corpo.append(el("div", { className: "linha" }, alternar, el("span", { className: "mudo", textContent: "Mostra o estado real das execuções; não decide nada." })), cena);
  if (oficinaLigada) montarOficina(cena, ultimoQuadro);
}

export function renderizar() {
  const corpo = document.getElementById("inferior-corpo");
  const nProb = [...problemas.values()].reduce((s, g) => s + g.itens.length, 0);
  abas(document.getElementById("inferior-abas"), ABAS.map((a) => (a.id === "problemas" && nProb ? { ...a, rotulo: `Problemas (${nProb})` } : a)), aba, (id) => mostrar(id));
  limpar(corpo);
  corpo.setAttribute("role", "tabpanel"); corpo.setAttribute("aria-labelledby", `aba-${aba}`);
  if (aba === "eventos") listaEventos(corpo); else if (aba === "controle") controle(corpo); else if (aba === "problemas") listaProblemas(corpo);
  else if (aba === "terminal") montarTerminal(corpo); else oficina(corpo);
}

export function mostrar(id) {
  aba = ABAS.some((a) => a.id === id) ? id : "eventos";
  localStorage.setItem("forja_aba_inferior", aba);
  renderizar();
}

export function iniciar() {
  ouvir("evento", (e) => {
    eventos.unshift(e); eventos.length = Math.min(eventos.length, 300);
    if (aba === "eventos" && document.getElementById("area").dataset.inferior === "on") renderizarEventosDepressa();
  });
  ouvir("kanban", (q) => { ultimoQuadro = q; if (aba === "oficina" && oficinaLigada) atualizarOficina(q); });
  ouvir("oficina", (ligada) => { oficinaLigada = ligada; if (aba === "oficina") renderizar(); });
  ouvir("problemas", ({ aba: chave, titulo, itens }) => { problemas.set(chave, { titulo, itens }); if (aba === "problemas") renderizar(); else atualizarRotuloProblemas(); });
  ouvir("inferior", (id) => { definirPainel("inferior", true); mostrar(id); });
  ouvir("painel", ({ nome, ligado }) => { if (nome === "inferior" && ligado && aba === "eventos") renderizar(); });
  renderizar();
}

let tEventos = null;
function renderizarEventosDepressa() { clearTimeout(tEventos); tEventos = setTimeout(() => { if (aba === "eventos") renderizar(); }, 250); }
function atualizarRotuloProblemas() {
  const b = document.getElementById("aba-problemas");
  const n = [...problemas.values()].reduce((s, g) => s + g.itens.length, 0);
  if (b) b.textContent = n ? `Problemas (${n})` : "Problemas";
}
export const atualizarControle = () => { if (aba === "controle") renderizar(); };
export const comandoTerminal = (texto) => { mostrar("terminal"); definirPainel("inferior", true); requestAnimationFrame(() => { const i = document.querySelector(".terminal-entrada"); if (i) { i.value = texto; i.focus(); } }); };
