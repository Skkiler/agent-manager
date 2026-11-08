// Painel tecnico Forja (Fase 1). Consome apenas a API autorizada; sem acesso a banco/CLI.
// Nunca exibe token, stack trace ou PII. Projeta estados reais vindos do backend.
"use strict";

const $ = (s) => document.querySelector(s);
const API = "/api/v1";
let token = sessionStorage.getItem("forja_token") || "";
let fonte = null;

function cab() {
  const h = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function api(metodo, caminho, corpo, extra = {}) {
  const resp = await fetch(API + caminho, {
    method: metodo,
    headers: { ...cab(), ...extra },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  const texto = await resp.text();
  const dados = texto ? JSON.parse(texto) : null;
  if (!resp.ok) throw new Error(dados?.mensagem || `Falha HTTP ${resp.status}`);
  return dados;
}

function escapar(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function listarTarefas() {
  try {
    const tarefas = await api("GET", "/tarefas");
    $("#tarefas").innerHTML = tarefas
      .map((t) => {
        const acoes = acoesPara(t);
        return `<tr><td>${escapar(t.id)}</td><td>${escapar(t.titulo)}</td>
          <td class="estado">${escapar(t.estado)}</td><td>${t.versao_estado}</td><td>${acoes}</td></tr>`;
      })
      .join("");
  } catch (e) {
    $("#tarefas").innerHTML = `<tr><td colspan="5">Erro: ${escapar(e.message)}</td></tr>`;
  }
}

function acoesPara(t) {
  const b = [];
  if (t.estado === "rascunho")
    b.push(`<button data-acao="fluxo" data-id="${t.id}" data-v="${t.versao_estado}">preparar</button>`);
  if (t.estado === "pronta") b.push(`<button data-acao="executar" data-id="${t.id}">executar</button>`);
  if (!["concluida", "falhou", "cancelada", "expirada"].includes(t.estado))
    b.push(`<button data-acao="cancelar" data-id="${t.id}" data-v="${t.versao_estado}">cancelar</button>`);
  return b.join(" ");
}

async function preparar(id, v) {
  // rascunho -> classificada -> preparada (cada passo e uma transicao manual permitida)
  let r = await api("POST", `/tarefas/${id}/transicao`, { para: "classificada", expected_version: v });
  await api("POST", `/tarefas/${id}/transicao`, { para: "preparada", expected_version: r.versao_estado });
}

async function executar(id) {
  const ex = await api("POST", `/tarefas/${id}/execucoes`);
  await api("POST", `/execucoes/${ex.id}/iniciar`);
}

document.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-acao]");
  if (!btn) return;
  const { acao, id, v } = btn.dataset;
  btn.disabled = true;
  try {
    if (acao === "fluxo") await preparar(id, Number(v));
    else if (acao === "executar") await executar(id);
    else if (acao === "cancelar")
      await api("POST", `/tarefas/${id}/transicao`, { para: "cancelada", expected_version: Number(v) });
    await listarTarefas();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
});

$("#criar-demo").addEventListener("click", async () => {
  const saida = $("#criar-saida");
  saida.textContent = "criando...";
  try {
    const sufixo = Date.now().toString(36);
    const p = await api("POST", "/projetos", { nome: `demo-${sufixo}`, descricao: "projeto sintetico" });
    const o = await api("POST", "/objetivos", { projeto_id: p.id, titulo: "objetivo demo" });
    const t = await api("POST", "/tarefas", {
      objetivo_id: o.id,
      titulo: "tarefa simulada",
      criterios_aceite: ["mock conclui a simulacao"],
      modo: "analise",
      entrada: { mock_cenario: $("#cenario").value, mock_passos: 3 },
    });
    await preparar(t.id, t.versao_estado);
    saida.textContent = `criada ${t.id} (estado pronta). Clique em executar.`;
    await listarTarefas();
  } catch (e) {
    saida.textContent = `erro: ${e.message}`;
  }
});

$("#atualizar").addEventListener("click", listarTarefas);

// ---- Aprovacoes por ACAO (grupo): uma pergunta em linguagem natural, itens marcaveis, adendo, lote ----
function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  for (const f of filhos) n.append(f);
  return n;
}

function cartaoAprovacao(ap) {
  const itens = ap.itens || [];
  const checks = itens.map((i) => {
    const cb = el("input", { type: "checkbox", checked: true, value: i.id });
    return el("li", {}, el("label", {}, cb, el("span", { textContent: i.descricao }),
      el("span", { className: `risco ${i.risco}`, textContent: `risco ${i.risco}` })));
  });
  const adendo = el("input", { type: "text", maxLength: 500, placeholder: "Adendo opcional (orientação ao agente)" });
  adendo.setAttribute("aria-label", "Adendo à autorização");
  const lembrar = el("input", { type: "checkbox" });
  const decidir = async (decisao) => {
    const marcados = [...checks.map((li) => li.querySelector("input"))].filter((c) => c.checked).map((c) => c.value);
    try {
      await api("POST", `/aprovacoes/${ap.id}/decidir`, {
        decisao,
        itens_aprovados: itens.length ? marcados : null,
        adendo: adendo.value,
        lembrar_na_execucao: lembrar.checked,
      });
      await listarAprovacoes();
    } catch (e) {
      alert(e.message);
    }
  };
  const aprovar = el("button", { type: "button", textContent: "Aprovar marcadas" });
  const negar = el("button", { type: "button", textContent: "Negar" });
  aprovar.addEventListener("click", () => decidir("aprovada"));
  negar.addEventListener("click", () => decidir("negada"));
  const origem = ap.origem === "pre_execucao" ? "Antes de executar" : "Durante a execução";
  return el("article", { className: "aprov" },
    el("strong", { textContent: `${origem}: ${ap.justificativa || ap.acao}` }),
    itens.length ? el("ul", {}, ...checks) : el("p", { textContent: ap.acao }),
    el("div", { className: "aprov-acoes" }, adendo,
      el("label", {}, lembrar, " lembrar nesta execução"), aprovar, negar));
}

async function listarAprovacoes() {
  try {
    const pend = await api("GET", "/aprovacoes?estado=pendente");
    $("#aprov-contagem").textContent = String(pend.length);
    const caixa = $("#aprovacoes");
    caixa.replaceChildren(...pend.map(cartaoAprovacao));
    $("#lote").hidden = pend.length < 2;
    $("#lote").dataset.ids = JSON.stringify(pend.map((p) => p.id));
  } catch (e) {
    $("#aprovacoes").textContent = `Erro: ${e.message}`;
  }
}

async function decidirLote(decisao) {
  const ids = JSON.parse($("#lote").dataset.ids || "[]");
  try {
    await api("POST", "/aprovacoes/decidir-lote", { ids, decisao, adendo: $("#lote-adendo").value });
    await listarAprovacoes();
  } catch (e) {
    alert(e.message);
  }
}
$("#lote-aprovar").addEventListener("click", () => decidirLote("aprovada"));
$("#lote-negar").addEventListener("click", () => decidirLote("negada"));

$("#salvar-token").addEventListener("click", () => {
  token = $("#token").value.trim();
  sessionStorage.setItem("forja_token", token);
  $("#token").value = "";
  conectarSse();
  listarTarefas();
  listarAprovacoes();
});

function conectarSse() {
  if (fonte) fonte.close();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  fonte = new EventSource(`${API}/eventos/stream${q}`);
  const conexao = $("#conexao");
  fonte.onopen = () => {
    conexao.textContent = "conectado";
    conexao.classList.add("ok");
  };
  fonte.onerror = () => {
    conexao.textContent = "reconectando...";
    conexao.classList.remove("ok");
  };
  fonte.onmessage = registrarEvento; // o servidor nao nomeia eventos SSE: o tipo vem em d.tipo
}

const vistos = new Set();
function registrarEvento(e) {
  let d;
  try {
    d = JSON.parse(e.data);
  } catch {
    return;
  }
  if (vistos.has(d.seq)) return; // ignora duplicados/reentrega
  vistos.add(d.seq);
  const li = document.createElement("li");
  li.textContent = `#${d.seq} ${d.tipo} ${d.tarefa_id || ""} ${d.ts}`;
  $("#eventos").prepend(li);
  if (String(d.tipo).startsWith("tarefa.") || String(d.tipo).startsWith("execucao.")) listarTarefas();
  if (String(d.tipo).startsWith("aprovacao.")) listarAprovacoes();
}

if (token) {
  conectarSse();
  listarTarefas();
  listarAprovacoes();
}
