// Quadro Kanban de tarefas (estilo Jira). As colunas e as acoes validas vem do servidor: a UI nao inventa transicoes.
import { api, consulta } from "../api.js";
import { estado, emitir, ouvir, selecionarTarefa } from "../estado.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";

let projetoFiltro = "";
let ultimo = null;
let quadro = null;

async function preparar(c) {
  const a = await api("POST", `/tarefas/${c.id}/transicao`, { para: "classificada", expected_version: c.versao_estado });
  await api("POST", `/tarefas/${c.id}/transicao`, { para: "preparada", expected_version: a.versao_estado });
}
async function executar(c) {
  const ex = await api("POST", `/tarefas/${c.id}/execucoes`);
  await api("POST", `/execucoes/${ex.id}/iniciar`);
}
async function cancelar(c) {
  if (!confirm(`Cancelar a tarefa "${c.titulo}"? Esta acao nao pode ser desfeita.`)) return;
  await api("POST", `/tarefas/${c.id}/transicao`, { para: "cancelada", expected_version: c.versao_estado });
}

async function acao(id, c) {
  try {
    if (id === "preparar") await preparar(c);
    else if (id === "executar") await executar(c);
    else if (id === "cancelar") await cancelar(c);
    else if (id === "conversa") { selecionarTarefa(c.id); emitir("abrir-direita", "conversa"); }
    else if (id === "aprovacoes") emitir("abrir-direita", "decisoes");
    await atualizar();
  } catch (e) { toast(e.message, "erro"); }
}

// Soltar um cartao numa coluna so e aceito quando equivale a uma acao valida do servidor.
const DESTINO_ACAO = { pronta: "preparar", encerradas: "cancelar" };
async function soltar(colunaId, c) {
  const id = DESTINO_ACAO[colunaId];
  if (!id || !c.acoes.some((a) => a.id === id)) {
    return toast("Movimento nao permitido: os estados avancam pelo orquestrador. Use os botoes do cartao.", "erro");
  }
  await acao(id, c);
}

function cartao(c) {
  const sel = estado.tarefaId === c.id;
  return el("article", {
    className: `cartao${c.precisa_de_voce ? " precisa" : ""}${sel ? " sel" : ""}`, draggable: true, dataset: { id: c.id, prio: c.prioridade },
    "aria-label": `${c.titulo}, ${c.estado}`,
    ondragstart: (ev) => { ev.dataTransfer.setData("text/plain", c.id); ev.dataTransfer.effectAllowed = "move"; },
    onclick: (ev) => { if (!ev.target.closest("button")) { selecionarTarefa(c.id); emitir("abrir-direita", "conversa"); } },
  },
    el("div", { className: "meta" }, tag(c.id, "so-avancado"), tag(`P${c.prioridade}`), tag(c.estado, c.precisa_de_voce ? "aviso" : ""),
      c.tentativas ? tag(`${c.tentativas} tent.`, "so-avancado") : null, c.dependencias ? tag(`${c.dependencias} dep.`) : null),
    el("h3", { textContent: c.titulo }),
    c.motivo ? el("div", { className: "mudo so-avancado", textContent: c.motivo }) : null,
    el("div", { className: "acoes" }, ...c.acoes.map((a) => el("button", { type: "button", textContent: a.rotulo, className: a.id === "executar" || a.id === "preparar" ? "primario" : "", onclick: () => acao(a.id, c) }))));
}

function coluna(col) {
  const corpo = el("div", { className: "cartoes" }, ...(col.cartoes.length ? col.cartoes.map(cartao) : [el("p", { className: "mudo", textContent: "Vazio" })]));
  const raiz = el("section", { className: "coluna", dataset: { id: col.id }, "aria-label": `${col.rotulo}, ${col.total} tarefas`,
    ondragover: (ev) => { ev.preventDefault(); raiz.classList.add("alvo"); }, ondragleave: () => raiz.classList.remove("alvo"),
    ondrop: (ev) => {
      ev.preventDefault(); raiz.classList.remove("alvo");
      const c = quadro.colunas.flatMap((x) => x.cartoes).find((x) => x.id === ev.dataTransfer.getData("text/plain"));
      if (c) soltar(col.id, c);
    } },
    el("header", {}, el("span", { textContent: col.rotulo }), tag(String(col.total))), corpo);
  if (col.total > col.cartoes.length) corpo.append(el("p", { className: "mudo", textContent: `+${col.total - col.cartoes.length} nao exibidas` }));
  return raiz;
}

export async function atualizar() {
  if (!ultimo) return;
  try {
    quadro = await api("GET", `/kanban?${consulta({ projeto_id: projetoFiltro })}`);
    limpar(ultimo.quadro);
    ultimo.quadro.append(...quadro.colunas.map(coluna));
    ultimo.resumo.textContent = `${quadro.total} tarefa(s)` + (quadro.precisa_de_voce ? ` · ${quadro.precisa_de_voce} precisam de voce` : "");
    emitir("kanban", quadro);
  } catch (e) { limpar(ultimo.quadro); ultimo.quadro.append(el("p", { className: "aviso", textContent: `Erro: ${e.message}` })); }
}

function novaTarefa() {
  const titulo = el("input", { required: true, maxLength: 200 });
  const desc = el("textarea", { rows: 3, maxLength: 4000 });
  const crit = el("textarea", { rows: 3, placeholder: "Um criterio por linha", required: true });
  const cenario = el("select", {}, ...["sucesso", "falha", "bloqueio", "conversa"].map((v) => el("option", { value: v, textContent: v })));
  const prio = el("select", {}, ...[1, 2, 3, 4, 5].map((n) => el("option", { value: n, textContent: `P${n}${n === 1 ? " (mais urgente)" : ""}`, selected: n === 3 })));
  const f = el("form", {},
    el("label", { className: "campo" }, el("span", { textContent: "Titulo" }), titulo),
    el("label", { className: "campo" }, el("span", { textContent: "Descricao" }), desc),
    el("label", { className: "campo" }, el("span", { textContent: "Criterios de aceite (obrigatorio)" }), crit),
    el("label", { className: "campo" }, el("span", { textContent: "Prioridade" }), prio),
    el("label", { className: "campo so-avancado" }, el("span", { textContent: "Cenario do agente simulado (so vale para o mock)" }), cenario),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Criar e preparar" }),
      el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo("Nova tarefa", f);
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const sufixo = Date.now().toString(36);
      let pid = projetoFiltro;
      if (!pid) pid = (await api("POST", "/projetos", { nome: `projeto-${sufixo}`, descricao: "criado pelo painel" })).id;
      const o = await api("POST", "/objetivos", { projeto_id: pid, titulo: titulo.value, prioridade: Number(prio.value) });
      const t = await api("POST", "/tarefas", { objetivo_id: o.id, titulo: titulo.value, descricao: desc.value,
        criterios_aceite: crit.value.split("\n").map((s) => s.trim()).filter(Boolean), entrada: { mock_cenario: cenario.value, mock_passos: 3 } });
      await preparar({ id: t.id, versao_estado: t.versao_estado });
      d.fechar(); toast("Tarefa criada e preparada", "ok"); await atualizar();
    } catch (e) { toast(e.message, "erro"); }
  });
}

export async function montarLateral(lat) {
  limpar(lat);
  const sel = el("select", { "aria-label": "Filtrar por projeto", onchange: () => { projetoFiltro = sel.value; atualizar(); } }, el("option", { value: "", textContent: "Todos os projetos" }));
  lat.append(el("h2", { textContent: "Tarefas" }), el("button", { type: "button", className: "primario", textContent: "+ Nova tarefa", onclick: novaTarefa }),
    el("label", { className: "campo" }, el("span", { textContent: "Projeto" }), sel),
    el("p", { className: "aviso", textContent: "Arraste um cartao para Pronta (preparar) ou para Falhou/cancelada (cancelar). Sem arrastar, use os botoes do cartao." }));
  try { for (const p of await api("GET", "/projetos")) sel.append(el("option", { value: p.id, textContent: p.nome, selected: p.id === projetoFiltro })); } catch { /* lista de projetos e opcional */ }
}

export function montar(raiz) {
  limpar(raiz);
  const resumo = el("span", { className: "mudo", role: "status" });
  const quadroEl = el("div", { className: "kanban" });
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Quadro de tarefas" }), resumo,
    el("button", { type: "button", textContent: "Atualizar", onclick: atualizar })), quadroEl);
  ultimo = { quadro: quadroEl, resumo };
  atualizar();
}

ouvir("tarefa", () => { if (ultimo?.quadro.isConnected) atualizar(); });
