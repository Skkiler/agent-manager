// Barra do agente (direita): conversa da tarefa (briefing do agente + UMA resposta livre), decisoes pendentes (aprovacoes por
// acao) e o master. No modo chat a barra ocupa a tela inteira, com a lista de conversas a esquerda (como no Codex).
import { api } from "./api.js";
import { montarChat } from "./chat.js";
import { agrupar, definirPainel, emitir, estado, ouvir } from "./estado.js";
import { abas, el, limpar, recolhivel, toast } from "./ui.js";
import * as master from "./views/master.js";
import { secaoAnexos } from "./views/projetos.js";

const TITULOS = { entendimento: "Entendimento", plano: "Plano", resposta: "Resposta", evidencias: "Evidências", premissas: "Premissas", decisoes: "Decisões para você",
  riscos: "Riscos", proximos_passos: "Próximos passos", resposta_operador: "Você", verificacao: "Verificação da Forja", status: "Status" };
let aba = "conversa";
let pendentes = 0;

function mensagem(m) {
  const caixa = el("article", { className: `msg ${m.papel}${m.tipo === "verificacao" ? " msg-verificacao" : ""}` },
    el("h3", { textContent: TITULOS[m.tipo] || m.tipo }));
  const ds = m.tipo === "decisoes" && Array.isArray(m.dados?.decisoes) ? m.dados.decisoes : [];
  if (ds.length) {
    for (const d of ds) caixa.append(el("div", { className: "decisao" }, el("strong", { textContent: `${d.numero}. ${d.pergunta}` }),
      d.recomendacao ? el("small", { textContent: `Recomendo: ${d.recomendacao}` }) : null, (d.alternativas || []).length ? el("small", { textContent: `Alternativas: ${d.alternativas.join("; ")}` }) : null));
  } else caixa.append(m.conteudo.length > 400 ? recolhivel(el("p", { textContent: m.conteudo }), 8) : el("p", { textContent: m.conteudo }));
  return caixa;
}

/** Conversa de uma tarefa (usada na barra e no modo chat). */
export async function conversa(corpo, id = estado.tarefaId, aoMudar = () => renderizar()) {
  if (!id) return corpo.append(el("p", { className: "mudo", textContent: "Selecione uma tarefa no quadro (ou no modo Chat) para ver a conversa com o agente." }));
  corpo.append(el("p", { className: "mudo", textContent: `Tarefa ${id}` }));
  try {
    const [msgs, usos] = await Promise.all([api("GET", `/tarefas/${id}/conversa`), api("GET", `/tarefas/${id}/contexto`)]);
    const uso = usos[usos.length - 1];
    if (uso) corpo.append(el("p", { className: "aviso", textContent: uso.itens.length
      ? `Contexto enviado: ${uso.itens.length} item(ns), ~${uso.tokens_contexto} tokens (estimativa); usados pelo agente: ${(uso.uteis || []).length}.`
      : "Nenhum contexto foi enviado (0 tokens): nada na memória era relevante o bastante." }));
    corpo.append(await secaoAnexos(id, aoMudar));
    corpo.append(...(msgs.length ? msgs.map(mensagem) : [el("p", { className: "mudo", textContent: "Sem mensagens ainda. Execute a tarefa para o agente se apresentar." })]));
    const texto = el("textarea", { rows: 4, maxLength: 8000, required: true, "aria-label": "Sua resposta", spellcheck: true, lang: "pt-BR" });
    const retomar = el("input", { type: "checkbox", checked: true });
    const form = el("form", { className: "composer", onsubmit: async (ev) => {
      ev.preventDefault();
      try {
        const r = await api("POST", `/tarefas/${id}/conversa`, { conteudo: texto.value, retomar: retomar.checked });
        texto.value = ""; if (r.aviso) toast(r.aviso);
        emitir("tarefa", id); await aoMudar();
      } catch (e) { toast(e.message, "erro"); }
    } }, el("label", { className: "campo" }, el("span", { textContent: "Sua resposta (uma vez, em texto livre)" }), texto),
    el("div", { className: "linha" }, el("label", {}, retomar, " retomar a execução ao responder"), el("span", { className: "espaco" }),
      el("button", { type: "submit", className: "primario", textContent: "Responder" })));
    texto.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) form.requestSubmit(); });
    corpo.append(form);
  } catch (e) { corpo.append(el("p", { className: "aviso", textContent: e.message })); }
}

function cartaoAprovacao(ap, aoMudar) {
  const itens = ap.itens || [];
  const marcas = itens.map((i) => el("li", {}, el("label", {}, el("input", { type: "checkbox", checked: true, value: i.id }), ` ${i.descricao}`, el("span", { className: `risco ${i.risco}`, textContent: `risco ${i.risco}` }))));
  const adendo = el("input", { type: "text", maxLength: 500, placeholder: "Adendo opcional", "aria-label": "Adendo à autorização" });
  const lembrar = el("input", { type: "checkbox" });
  const decidir = async (decisao) => {
    const aprovados = marcas.map((li) => li.querySelector("input")).filter((c) => c.checked).map((c) => c.value);
    try { await api("POST", `/aprovacoes/${ap.id}/decidir`, { decisao, itens_aprovados: itens.length ? aprovados : null, adendo: adendo.value, lembrar_na_execucao: lembrar.checked }); await aoMudar(); }
    catch (e) { toast(e.message, "erro"); }
  };
  return el("article", { className: "aprov" }, el("strong", { textContent: `${ap.origem === "pre_execucao" ? "Antes de executar" : "Durante a execução"}: ${ap.justificativa || ap.acao}` }),
    itens.length ? el("ul", {}, ...marcas) : el("p", { textContent: ap.acao }),
    el("div", { className: "linha" }, adendo, el("label", {}, lembrar, " lembrar nesta execução"), el("button", { type: "button", className: "primario", textContent: "Aprovar marcadas", onclick: () => decidir("aprovada") }),
      el("button", { type: "button", textContent: "Negar", onclick: () => decidir("negada") })));
}

/** Decisoes pendentes (todas, ou so as de uma tarefa no modo chat). */
export async function decisoes(corpo, tarefaId = null, aoMudar = () => renderizar()) {
  try {
    const todas = await api("GET", "/aprovacoes?estado=pendente");
    pendentes = todas.length; atualizarRotulos();
    const pend = tarefaId ? todas.filter((p) => !p.tarefa_id || p.tarefa_id === tarefaId) : todas;
    if (tarefaId && !pend.length) return;
    corpo.append(el("p", { className: "aviso", textContent: "Cada pedido agrupa ações relacionadas: uma decisão, um adendo opcional. Ações que envolvem segredos nunca chegam aqui (são negadas automaticamente)." }));
    if (!pend.length) return corpo.append(el("p", { className: "mudo", textContent: "Nenhuma decisão pendente." }));
    corpo.append(...pend.map((ap) => cartaoAprovacao(ap, aoMudar)));
    if (pend.length > 1) {
      const adendo = el("input", { type: "text", maxLength: 500, placeholder: "Adendo para todos", "aria-label": "Adendo para todos" });
      const lote = async (decisao) => { try { await api("POST", "/aprovacoes/decidir-lote", { ids: pend.map((p) => p.id), decisao, adendo: adendo.value }); await aoMudar(); } catch (e) { toast(e.message, "erro"); } };
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
  const abasNo = document.getElementById("direita-abas");
  const chat = estado.modo === "chat";
  abasNo.hidden = chat;
  if (chat) {
    corpo.removeAttribute("role"); corpo.removeAttribute("aria-labelledby");
    const temp = el("div", { className: "chat-raiz" });
    await montarChat(temp, { conversa, decisoes, master });
    if (minha === geracao) { limpar(corpo); corpo.append(temp); }
    return;
  }
  abas(abasNo, [{ id: "conversa", rotulo: "Conversa" }, { id: "decisoes", rotulo: `Decisões${pendentes ? ` (${pendentes})` : ""}` }, { id: "master", rotulo: "Master" }], aba, (id) => { aba = id; renderizar(); });
  corpo.setAttribute("role", "tabpanel"); corpo.setAttribute("aria-labelledby", `aba-${aba}`);
  const temp = el("div");
  if (aba === "master") master.montar(temp, { compacto: true });
  else await (aba === "conversa" ? conversa(temp) : decisoes(temp));
  if (minha === geracao) { limpar(corpo); corpo.append(...temp.childNodes); }
}

export function iniciar() {
  ouvir("tarefa", () => { if (aba === "conversa" || estado.modo === "chat") renderizar(); });
  ouvir("abrir-direita", (id) => { aba = id === "master" || id === "decisoes" ? id : "conversa"; definirPainel("direita", true); renderizar(); });
  ouvir("modo", () => renderizar());
  const reagir = agrupar(renderizar);
  ouvir("evento", (e) => {
    const t = String(e.tipo);
    if (t.startsWith("aprovacao.") || (t.startsWith("conversa.") && e.tarefa_id === estado.tarefaId && (aba === "conversa" || estado.modo === "chat"))) reagir();
  });
  renderizar();
}
