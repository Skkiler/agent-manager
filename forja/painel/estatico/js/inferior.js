// Painel inferior: Problemas (do arquivo aberto), Terminal (um comando por vez na pasta de trabalho), Eventos (SSE com
// filtro), Controle do master e Oficina pixel art.
import { api } from "./api.js";
import { abaAtiva, abas as abasEditor, ativar } from "./bancada.js";
import { comConfirmacao } from "./confirmar.js";
import { configEditor } from "./editorcfg.js";
import { definirPainel, emitir, ouvir } from "./estado.js";
import { icone } from "./icones.js";
import { atualizarOficina, montarOficina } from "./oficina.js";
import { abas, dataCurta, el, limpar, tag, toast } from "./ui.js";
import { definirPreferencia } from "./views/config.js";

const ABAS = [{ id: "problemas", rotulo: "Problemas" }, { id: "terminal", rotulo: "Terminal" }, { id: "eventos", rotulo: "Eventos" },
  { id: "controle", rotulo: "Controle" }, { id: "oficina", rotulo: "Oficina" }];
let aba = localStorage.getItem("forja_aba_inferior") || "eventos";
let oficinaLigada = localStorage.getItem("forja_oficina") !== "off";
let ultimoQuadro = null;
const eventos = [];
const problemas = new Map(); // chave da aba do editor -> { titulo, itens }
const terminal = { historico: [], comandos: JSON.parse(localStorage.getItem("forja_terminal_historico") || "[]"), indice: -1, rodando: false, pasta: "", rotulo: "", colar: "" };
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

// ------------------------------------------------------------------ Terminal (com assistente: explica, completa, aponta erros)
const ROTULO_RISCO = { baixo: "seguro", medio: "atenção", alto: "perigoso" };
const contextoTerminal = { chave: "", dados: {} };

async function opcoesTerminal() {
  let lista = [];
  try { lista = (await api("GET", "/projetos")).filter((p) => (p.pastas || []).some((x) => x.papel === "trabalho")); } catch { lista = []; }
  return lista.flatMap((p) => p.pastas.map((x, i) => [p, x, i]).filter(([, x]) => x.papel === "trabalho"));
}

/** Nomes de branches, remotos, containers e arquivos da pasta (para as sugestoes); carregados uma vez por pasta. */
async function carregarContexto(valor) {
  if (!valor || contextoTerminal.chave === valor) return contextoTerminal.dados;
  contextoTerminal.chave = valor;
  const [projeto, raiz] = valor.split("|");
  const dados = {};
  const [git, arvore, cont, imgs] = await Promise.all([
    api("GET", `/area/git?projeto=${encodeURIComponent(projeto)}&raiz=${raiz}`).catch(() => null),
    api("GET", `/area/arvore?projeto=${encodeURIComponent(projeto)}&raiz=${raiz}`).catch(() => null),
    api("GET", "/area/docker?recurso=containers").catch(() => []), api("GET", "/area/docker?recurso=imagens").catch(() => [])]);
  if (git?.dados?.repositorio) { dados.ramos = git.dados.branches || []; dados.remotos = Object.keys(git.dados.remotos || {}); }
  if (arvore) dados.arquivos = arvore.itens.map((i) => i.nome).slice(0, 200);
  dados.containers = cont.map((c) => c.Names).filter(Boolean);
  dados.imagens = imgs.map((i) => `${i.Repository}:${i.Tag}`).filter((x) => !x.includes("<none>"));
  contextoTerminal.dados = dados;
  return dados;
}

let desenharSaidaAtual = null;
async function executarComando(comando, { pasta = terminal.pasta } = {}) {
  comando = (comando || "").trim();
  if (!comando) return null;
  if (!pasta) {
    const ops = await opcoesTerminal();
    if (!ops.length) { toast("O terminal precisa de um projeto com pasta de trabalho.", "erro"); return null; }
    pasta = terminal.pasta = `${ops[0][0].id}|${ops[0][2]}`;
  }
  if (terminal.rodando) { toast("Espere o comando atual terminar."); return null; }
  const [projeto, raiz] = pasta.split("|");
  const h = { comando, pasta: terminal.rotulo || "", codigo: null, saida: "", avisos: [] };
  terminal.historico.push(h); terminal.historico = terminal.historico.slice(-60);
  terminal.comandos = [comando, ...terminal.comandos.filter((c) => c !== comando)].slice(0, 80); terminal.indice = -1;
  localStorage.setItem("forja_terminal_historico", JSON.stringify(terminal.comandos.slice(0, 50)));
  terminal.rodando = true; desenharSaidaAtual?.();
  let r = null;
  try {
    r = await comConfirmacao("POST", "/area/terminal", { projeto, raiz: Number(raiz), comando }, { titulo: "Comando perigoso", detalhe: comando });
    if (r) Object.assign(h, r); else { h.codigo = -1; h.saida = "Cancelado por você (nada foi executado)."; h.cancelado = true; }
  } catch (e) { h.codigo = -1; h.saida = e.message; }
  terminal.rodando = false;
  desenharSaidaAtual?.();
  return r ? h : null;
}

async function montarTerminal(corpo) {
  const opcoes = await opcoesTerminal();
  if (!opcoes.length) return corpo.append(el("div", { className: "vazio-acao" }, icone("terminal", 28),
    el("p", { textContent: "O terminal roda na pasta de TRABALHO de um projeto." }), el("p", { className: "mudo", textContent: "Crie um projeto com pasta de trabalho (Explorador > +)." })));
  const sel = el("select", { "aria-label": "Pasta onde o comando roda" }, ...opcoes.map(([p, x, i]) => el("option", { value: `${p.id}|${i}`, textContent: `${p.nome} · ${x.caminho.split(/[\\/]/).pop()}` })));
  // segue o projeto do arquivo aberto (se for pasta de trabalho); senao, a ultima pasta usada
  const aberta = abaAtiva();
  const doArquivo = aberta?.tipo === "arquivo" ? `${aberta.projeto}|${aberta.raiz}` : "";
  const salvo = [doArquivo, terminal.pasta, localStorage.getItem("forja_terminal_pasta")].find((v) => v && opcoes.some(([p, , i]) => `${p.id}|${i}` === v));
  if (salvo) sel.value = salvo;
  const fixar = () => { terminal.pasta = sel.value; terminal.rotulo = sel.selectedOptions[0]?.textContent.split(" · ").pop() || ""; localStorage.setItem("forja_terminal_pasta", sel.value); carregarContexto(sel.value); };
  sel.addEventListener("change", fixar); fixar();
  const saida = el("div", { className: "terminal-saida", role: "log", "aria-live": "polite", "aria-label": "Saída do terminal", tabIndex: 0 });
  const entrada = el("input", { type: "text", className: "terminal-entrada", maxLength: 4000, spellcheck: false, autocomplete: "off", role: "combobox",
    "aria-autocomplete": "list", "aria-expanded": "false", "aria-controls": "terminal-sugestoes", "aria-describedby": "terminal-ajuda",
    "aria-label": "Comando do terminal", placeholder: "Digite um comando (Tab completa, ↑/↓ histórico, Enter executa)", disabled: terminal.rodando });
  const sugestoes = el("ul", { id: "terminal-sugestoes", className: "completar terminal-sugestoes", role: "listbox", "aria-label": "Sugestões de comando", hidden: true });
  const assist = el("div", { className: "terminal-assist", id: "terminal-ajuda", "aria-live": "polite" });
  let itens = [], marcado = -1, analiseAtual = null;
  const desenharSaida = () => {
    if (!saida.isConnected) return;
    limpar(saida);
    for (const h of terminal.historico) {
      saida.append(el("div", { className: "terminal-cmd" }, el("span", { className: "prompt", textContent: `${h.pasta} ❯ ` }), el("span", { textContent: h.comando }),
        h.codigo === null ? tag("rodando…") : tag(h.cancelado ? "cancelado" : h.tempo_esgotado ? "tempo esgotado" : `código ${h.codigo}`, h.codigo === 0 ? "ok" : "erro"),
        h.risco && h.risco !== "baixo" ? tag(ROTULO_RISCO[h.risco], h.risco === "alto" ? "erro" : "aviso") : null),
      ...(h.avisos || []).map((a) => el("p", { className: "terminal-aviso", textContent: `⚠ ${a}` })),
      h.saida ? el("pre", { className: "terminal-texto", textContent: h.saida }) : null);
    }
    if (!terminal.historico.length) saida.append(el("div", { className: "terminal-boas-vindas" },
      el("p", { textContent: "Terminal da pasta de trabalho. Enquanto você digita, o assistente explica cada parte, aponta erros e sugere como completar." }),
      el("p", { className: "mudo", textContent: "Comandos perigosos pedem confirmação. A saída (inclusive de .env) aparece só para você: não vai para os agentes nem para o log." }),
      el("div", { className: "linha" }, ...["git status -sb", "git log --oneline -n 10", "python -m pytest -q", "docker ps -a"].map((c) =>
        el("button", { type: "button", className: "chip-info", textContent: c, onclick: () => { entrada.value = c; entrada.focus(); analisar(); } })))));
    saida.scrollTop = saida.scrollHeight;
    entrada.disabled = terminal.rodando;
  };
  desenharSaidaAtual = desenharSaida;
  const fecharSugestoes = () => { sugestoes.hidden = true; entrada.setAttribute("aria-expanded", "false"); entrada.removeAttribute("aria-activedescendant"); marcado = -1; };
  const marcar = () => {
    [...sugestoes.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === marcado)));
    const ativo = sugestoes.children[marcado];
    if (ativo) { entrada.setAttribute("aria-activedescendant", ativo.id); ativo.scrollIntoView({ block: "nearest" }); }
  };
  const aceitar = (i = marcado < 0 ? 0 : marcado) => {
    const it = itens[i];
    if (!it) return;
    const v = entrada.value;
    const prefixo = analiseAtual?.sugestoes?.prefixo || "";
    entrada.value = `${v.slice(0, v.length - prefixo.length)}${/\s/.test(it.texto) ? `"${it.texto}"` : it.texto} `;
    fecharSugestoes(); entrada.focus(); analisar();
  };
  const desenharAssistente = (r) => {
    limpar(assist);
    const a = r.analise, s = r.sugestoes;
    const seg = a.segmentos[a.segmentos.length - 1];
    if (s.assinatura) assist.append(el("div", { className: "assinatura" }, el("code", { textContent: s.assinatura.sintaxe }),
      s.assinatura.parametro ? el("span", { className: "parametro", textContent: ` → ${s.assinatura.parametro}` }) : null));
    if (seg?.comando) assist.append(el("div", { className: "explicacao-cmd" }, tag(ROTULO_RISCO[a.risco] || a.risco, a.risco === "alto" ? "erro" : a.risco === "medio" ? "aviso" : "ok"),
      el("strong", { textContent: seg.comando.resumo }), seg.comando.origem === "ia" && !seg.comando.revisado ? tag("documentado pela IA, revisar", "aviso") : null));
    if (seg?.partes?.length > 1) assist.append(el("div", { className: "partes-cmd" }, ...seg.partes.map((p) => el("span", { className: `parte parte-${p.tipo}`, title: p.explicacao || p.tipo, tabIndex: 0,
      "aria-label": `${p.texto}: ${p.explicacao || p.tipo}` }, el("code", { textContent: p.texto }), p.explicacao ? el("small", { textContent: p.explicacao }) : null))));
    for (const e of a.erros) assist.append(el("p", { className: "erro-cmd", textContent: `✗ ${e}` }));
    for (const m of a.motivos) assist.append(el("p", { className: "aviso-cmd", textContent: `⚠ ${m}` }));
    for (const m of a.avisos) assist.append(el("p", { className: "mudo", textContent: `ⓘ ${m}` }));
    if (!seg?.comando && entrada.value.trim()) assist.append(el("p", { className: "mudo" }, "Comando fora do catálogo. ",
      el("button", { type: "button", className: "link", textContent: "Pedir à IA para documentar", onclick: () => emitir("ir", "comandos") })));
    itens = s.itens || [];
    if (itens.length && document.activeElement === entrada) {
      sugestoes.replaceChildren(...itens.map((it, i) => el("li", { id: `terminal-sug-${i}`, role: "option", className: `comp-${it.tipo}`,
        onpointerdown: (ev) => { ev.preventDefault(); aceitar(i); } },
      el("span", { className: "comp-texto", textContent: it.rotulo || it.texto }), it.risco === "alto" ? tag("perigoso", "erro") : null,
      el("span", { className: "comp-det mudo trunc", textContent: it.descricao || it.tipo }))));
      sugestoes.hidden = false; entrada.setAttribute("aria-expanded", "true"); marcado = -1; marcar();
    } else fecharSugestoes();
  };
  let tAnalise = null, geracaoAnalise = 0;
  const analisar = () => {
    clearTimeout(tAnalise);
    tAnalise = setTimeout(async () => {
      const minha = ++geracaoAnalise;
      const linha = entrada.value;
      if (!linha.trim()) { limpar(assist); fecharSugestoes(); return; }
      if (!(await configEditor()).preferencias.terminal_assistente) { limpar(assist); fecharSugestoes(); return; } // Configurações > Editor
      try {
        const r = await api("POST", "/area/comandos/analisar", { linha, contexto: contextoTerminal.dados });
        if (minha !== geracaoAnalise) return;
        analiseAtual = r; desenharAssistente(r);
      } catch { /* assistente e ajuda: sem ele o terminal funciona */ }
    }, 110);
  };
  const executar = async () => { fecharSugestoes(); const c = entrada.value; entrada.value = ""; limpar(assist); await executarComando(c); if (entrada.isConnected) entrada.focus(); };
  entrada.addEventListener("input", analisar);
  entrada.addEventListener("blur", () => setTimeout(fecharSugestoes, 150));
  entrada.addEventListener("keydown", (ev) => {
    const aberta = !sugestoes.hidden;
    if (ev.key === "Tab" && aberta && itens.length) { ev.preventDefault(); aceitar(); return; }
    if (ev.key === "Escape" && aberta) { ev.preventDefault(); ev.stopPropagation(); fecharSugestoes(); return; }
    if ((ev.key === "ArrowUp" || ev.key === "ArrowDown") && aberta && (marcado >= 0 || ev.key === "ArrowDown")) {
      ev.preventDefault(); marcado = (marcado + (ev.key === "ArrowDown" ? 1 : -1) + itens.length) % itens.length; marcar(); return;
    }
    if (ev.key === "Enter") { ev.preventDefault(); if (aberta && marcado >= 0) aceitar(); else executar(); return; }
    if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
      ev.preventDefault();
      terminal.indice = Math.max(-1, Math.min(terminal.comandos.length - 1, terminal.indice + (ev.key === "ArrowUp" ? 1 : -1)));
      entrada.value = terminal.indice < 0 ? "" : terminal.comandos[terminal.indice];
      analisar();
    }
  });
  const caixa = el("div", { className: "terminal-caixa" }, sugestoes, entrada);
  corpo.append(el("div", { className: "terminal" }, saida, assist, el("div", { className: "linha terminal-linha" }, sel, caixa,
    el("button", { type: "button", className: "pequeno primario", textContent: "Executar", onclick: executar }),
    el("button", { type: "button", className: "pequeno", title: "Processos passo a passo (Git, Docker, Python...)", onclick: () => emitir("receitas", "") }, icone("lampada", 14), "Receitas"),
    el("button", { type: "button", className: "pequeno", textContent: "Limpar", onclick: () => { terminal.historico = []; desenharSaida(); } }))));
  desenharSaida();
  if (terminal.colar) { entrada.value = terminal.colar; terminal.colar = ""; analisar(); }
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
  // receitas e atalhos: rodar (mostrando o terminal) ou so colar um comando
  ouvir("terminal-executar", async ({ linha, resolver }) => {
    definirPainel("inferior", true);
    if (aba !== "terminal") mostrar("terminal");
    resolver(await executarComando(linha));
  });
  ouvir("terminal-colar", (linha) => { terminal.colar = linha; definirPainel("inferior", true); mostrar("terminal"); });
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
export const comandoTerminal = (texto) => emitir("terminal-colar", texto);
