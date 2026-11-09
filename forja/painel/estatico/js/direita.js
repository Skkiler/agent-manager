// Painel direito: conversa da tarefa (briefing do agente + UMA resposta livre) e decisoes pendentes (aprovacoes por acao).
import { api } from "./api.js";
import { agrupar, emitir, estado, ouvir } from "./estado.js";
import { abas, el, limpar, toast } from "./ui.js";

const TITULOS = { entendimento: "Entendimento", resposta: "Resposta", premissas: "Premissas", decisoes: "Decisões para você",
  riscos: "Riscos", proximos_passos: "Próximos passos", resposta_operador: "Você" };
let aba = "conversa";
let pendentes = 0;

function mensagem(m) {
  const caixa = el("article", { className: `msg ${m.papel}` }, el("h3", { textContent: TITULOS[m.tipo] || m.tipo }));
  const ds = m.tipo === "decisoes" && Array.isArray(m.dados?.decisoes) ? m.dados.decisoes : [];
  if (ds.length) {
    for (const d of ds) caixa.append(el("div", { className: "decisao" }, el("strong", { textContent: `${d.numero}. ${d.pergunta}` }),
      d.recomendacao ? el("small", { textContent: `Recomendo: ${d.recomendacao}` }) : null, (d.alternativas || []).length ? el("small", { textContent: `Alternativas: ${d.alternativas.join("; ")}` }) : null));
  } else caixa.append(el("p", { textContent: m.conteudo }));
  return caixa;
}

async function conversa(corpo) {
  const id = estado.tarefaId;
  if (!id) return corpo.append(el("p", { className: "mudo", textContent: "Selecione uma tarefa no quadro para ver a conversa com o agente." }));
  corpo.append(el("p", { className: "mudo", textContent: `Tarefa ${id}` }));
  try {
    const [msgs, usos] = await Promise.all([api("GET", `/tarefas/${id}/conversa`), api("GET", `/tarefas/${id}/contexto`)]);
    const uso = usos[usos.length - 1];
    if (uso) corpo.append(el("p", { className: "aviso", textContent: uso.itens.length
      ? `Contexto enviado: ${uso.itens.length} item(ns), ~${uso.tokens_contexto} tokens (estimativa); usados pelo agente: ${(uso.uteis || []).length}.`
      : "Nenhum contexto foi enviado (0 tokens): nada na memoria era relevante o bastante." }));
    corpo.append(...(msgs.length ? msgs.map(mensagem) : [el("p", { className: "mudo", textContent: "Sem mensagens ainda. Execute a tarefa para o agente se apresentar." })]));
    const texto = el("textarea", { rows: 4, maxLength: 8000, required: true, "aria-label": "Sua resposta" });
    const retomar = el("input", { type: "checkbox", checked: true });
    corpo.append(el("form", { onsubmit: async (ev) => {
      ev.preventDefault();
      try {
        const r = await api("POST", `/tarefas/${id}/conversa`, { conteudo: texto.value, retomar: retomar.checked });
        texto.value = ""; if (r.aviso) toast(r.aviso);
        emitir("tarefa", id); await renderizar();
      } catch (e) { toast(e.message, "erro"); }
    } }, el("label", { className: "campo" }, el("span", { textContent: "Sua resposta (uma vez, em texto livre)" }), texto),
    el("label", {}, retomar, " retomar a execução ao responder"), el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Responder" }))));
  } catch (e) { corpo.append(el("p", { className: "aviso", textContent: e.message })); }
}

function cartaoAprovacao(ap) {
  const itens = ap.itens || [];
  const marcas = itens.map((i) => el("li", {}, el("label", {}, el("input", { type: "checkbox", checked: true, value: i.id }), ` ${i.descricao}`, el("span", { className: `risco ${i.risco}`, textContent: `risco ${i.risco}` }))));
  const adendo = el("input", { type: "text", maxLength: 500, placeholder: "Adendo opcional", "aria-label": "Adendo à autorização" });
  const lembrar = el("input", { type: "checkbox" });
  const decidir = async (decisao) => {
    const aprovados = marcas.map((li) => li.querySelector("input")).filter((c) => c.checked).map((c) => c.value);
    try { await api("POST", `/aprovacoes/${ap.id}/decidir`, { decisao, itens_aprovados: itens.length ? aprovados : null, adendo: adendo.value, lembrar_na_execucao: lembrar.checked }); await renderizar(); }
    catch (e) { toast(e.message, "erro"); }
  };
  return el("article", { className: "aprov" }, el("strong", { textContent: `${ap.origem === "pre_execucao" ? "Antes de executar" : "Durante a execução"}: ${ap.justificativa || ap.acao}` }),
    itens.length ? el("ul", {}, ...marcas) : el("p", { textContent: ap.acao }),
    el("div", { className: "linha" }, adendo, el("label", {}, lembrar, " lembrar nesta execução"), el("button", { type: "button", className: "primario", textContent: "Aprovar marcadas", onclick: () => decidir("aprovada") }),
      el("button", { type: "button", textContent: "Negar", onclick: () => decidir("negada") })));
}

async function decisoes(corpo) {
  try {
    const pend = await api("GET", "/aprovacoes?estado=pendente");
    pendentes = pend.length; atualizarRotulos();
    corpo.append(el("p", { className: "aviso", textContent: "Cada pedido agrupa acoes relacionadas: uma decisao, um adendo opcional. Acoes que envolvem segredos nunca chegam aqui (sao negadas automaticamente)." }));
    if (!pend.length) return corpo.append(el("p", { className: "mudo", textContent: "Nenhuma decisão pendente." }));
    corpo.append(...pend.map(cartaoAprovacao));
    if (pend.length > 1) {
      const adendo = el("input", { type: "text", maxLength: 500, placeholder: "Adendo para todos", "aria-label": "Adendo para todos" });
      const lote = async (decisao) => { try { await api("POST", "/aprovacoes/decidir-lote", { ids: pend.map((p) => p.id), decisao, adendo: adendo.value }); await renderizar(); } catch (e) { toast(e.message, "erro"); } };
      corpo.append(el("div", { className: "linha" }, adendo, el("button", { type: "button", textContent: "Aprovar todos", onclick: () => lote("aprovada") }), el("button", { type: "button", textContent: "Negar todos", onclick: () => lote("negada") })));
    }
  } catch (e) { corpo.append(el("p", { className: "aviso", textContent: e.message })); }
}

function atualizarRotulos() {
  const b = document.getElementById("aba-decisoes");
  if (b) b.textContent = `Decisões${pendentes ? ` (${pendentes})` : ""}`;
}

let geracao = 0;
export async function renderizar() {
  const minha = ++geracao; // chamadas concorrentes: so a ultima pode escrever (evita conteudo duplicado)
  const corpo = document.getElementById("direita-corpo");
  abas(document.getElementById("direita-abas"), [{ id: "conversa", rotulo: "Conversa" }, { id: "decisoes", rotulo: `Decisões${pendentes ? ` (${pendentes})` : ""}` }], aba, (id) => { aba = id; renderizar(); });
  limpar(corpo);
  corpo.setAttribute("role", "tabpanel"); corpo.setAttribute("aria-labelledby", `aba-${aba}`);
  const temp = el("div");
  await (aba === "conversa" ? conversa(temp) : decisoes(temp));
  if (minha === geracao) corpo.append(...temp.childNodes);
}

export function iniciar() {
  ouvir("tarefa", () => { if (aba === "conversa") renderizar(); });
  ouvir("abrir-direita", (id) => {
    aba = id; document.getElementById("area").dataset.direita = "on";
    document.getElementById("alternar-direita").setAttribute("aria-pressed", "true"); renderizar();
  });
  const reagir = agrupar(renderizar);
  ouvir("evento", (e) => {
    const t = String(e.tipo);
    if (t.startsWith("aprovacao.") || (t.startsWith("conversa.") && e.tarefa_id === estado.tarefaId && aba === "conversa")) reagir();
  });
  renderizar();
}
