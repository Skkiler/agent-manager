// Master: voce conversa com o coordenador; ele cria tarefas (e sub-masters, quando o pedido envolve 2+ projetos) e relata.
// Conteudo vindo do backend e DADO: so textContent.
import { api } from "../api.js";
import { agrupar, emitir, ouvir, selecionarTarefa } from "../estado.js";
import { dataCurta, el, limpar, recolhivel, tag, toast } from "../ui.js";

const PAPEIS = { usuario: "Você", master: "Master", submaster: "Sub-master", sistema: "Forja", status: "Status" };
const ESTADO_TAG = { concluida: "ok", bloqueada: "aviso", falhou: "aviso", cancelada: "", expirada: "" };
let ultimo = null;
let alvo = null; // null = master; id = conversa de um sub-master

function abrirTarefa(id) { selecionarTarefa(id); emitir("abrir-direita", "conversa"); }

function linhaTarefa(t) {
  return el("li", {}, el("button", { type: "button", className: "link", title: "Abrir a conversa da tarefa", onclick: () => abrirTarefa(t.id) },
    tag(t.estado, ESTADO_TAG[t.estado] ?? ""), " ", el("span", { className: "trunc", textContent: t.titulo })));
}

function arvore(p) {
  const m = p.master;
  const no = (c, rotulo) => el("li", { className: "no-coord" },
    el("div", { className: "linha" },
      el("button", { type: "button", className: "coord", textContent: rotulo,
        "aria-pressed": String(alvo === (c.tipo === "master" ? null : c.id)), onclick: () => { alvo = c.tipo === "master" ? null : c.id; atualizar(); } }),
      tag(`${c.chamadas_usadas}/${c.max_chamadas} turnos`, "so-avancado"), c.estado !== "ativo" ? tag(c.estado) : null),
    (c.tarefas || []).length ? el("ul", { className: "tarefas-coord" }, ...c.tarefas.map(linhaTarefa)) : null);
  return el("ul", { className: "arvore-coord", "aria-label": "Master, sub-masters e tarefas" },
    no(m, "Master"), ...p.submasters.map((s) => no(s, s.titulo)));
}

function fala(m) {
  const dados = m.dados || {};
  const criadas = dados.criadas || [];
  const recusadas = dados.recusadas || [];
  return el("article", { className: `msg msg-coord ${m.papel}` },
    el("h3", {}, PAPEIS[m.papel] || m.papel, " ", el("small", { className: "mudo", textContent: dataCurta(m.criado_em) }),
      dados.simulado ? tag("simulado", "aviso") : null),
    m.conteudo.length > 500 ? recolhivel(el("p", { textContent: m.conteudo }), 8) : el("p", { textContent: m.conteudo }),
    criadas.length ? el("ul", { className: "criadas" }, ...criadas.map((c) => el("li", {},
      c.tipo === "tarefa" ? el("button", { type: "button", className: "link", onclick: () => abrirTarefa(c.id), textContent: `Tarefa: ${c.titulo}` })
        : el("span", { textContent: `${c.titulo} (coordena o projeto)` })))) : null,
    recusadas.length ? el("details", { className: "so-avancado" }, el("summary", { textContent: `${recusadas.length} ação(ões) recusada(s) pela Forja` }),
      el("ul", {}, ...recusadas.map((r) => el("li", { textContent: r })))) : null,
    m.tarefa_id && !criadas.length && m.papel === "sistema" ? el("button", { type: "button", className: "link", textContent: "Abrir tarefa", onclick: () => abrirTarefa(m.tarefa_id) }) : null);
}

export async function atualizar() {
  if (!ultimo?.conversa.isConnected) return;
  try {
    const p = await api("GET", "/master");
    const sub = alvo ? p.submasters.find((s) => s.id === alvo) : null;
    if (alvo && !sub) alvo = null;
    const msgs = sub ? (await api("GET", `/coordenacoes/${alvo}`)).conversa : p.conversa;
    limpar(ultimo.arvore); ultimo.arvore.append(arvore(p));
    ultimo.titulo.textContent = sub ? sub.titulo : "Master";
    ultimo.encerrar.hidden = !sub && !p.master.chamadas_usadas;
    ultimo.encerrar.onclick = () => encerrar(sub || p.master);
    limpar(ultimo.conversa);
    ultimo.conversa.append(...(msgs.length ? msgs.map(fala) : [el("p", { className: "mudo", textContent:
      "Diga o que você quer. O master entende, cria as tarefas certas (uma tarefa bem descrita quando basta) e conta o resultado aqui." })]));
    ultimo.conversa.scrollTop = ultimo.conversa.scrollHeight;
  } catch (e) { limpar(ultimo.conversa); ultimo.conversa.append(el("p", { className: "aviso", textContent: `Erro: ${e.message}` })); }
}

async function encerrar(c) {
  if (!confirm(`Encerrar ${c.titulo}? A conversa fica guardada; um novo coordenador é aberto na próxima fala.`)) return;
  try { await api("POST", `/coordenacoes/${c.id}/encerrar`); alvo = null; await atualizar(); } catch (e) { toast(e.message, "erro"); }
}

export function montar(raiz) {
  limpar(raiz);
  const titulo = el("h1", { textContent: "Master" });
  const encerrar = el("button", { type: "button", textContent: "Encerrar conversa", hidden: true });
  const conversa = el("div", { className: "conversa-master", role: "log", "aria-live": "polite", "aria-label": "Conversa com o master" });
  const arvoreNo = el("aside", { className: "lado-master", "aria-label": "Coordenadores e tarefas" });
  const texto = el("textarea", { rows: 3, maxLength: 8000, required: true, "aria-label": "Seu pedido ao master",
    placeholder: "Ex.: revise a autenticação do projeto api e documente o que mudou" });
  const enviar = el("button", { type: "submit", className: "primario", textContent: "Enviar" });
  const form = el("form", { className: "form-master", onsubmit: async (ev) => {
    ev.preventDefault();
    enviar.disabled = true;
    try {
      const r = await api("POST", "/master/conversa", { texto: texto.value, coordenacao_id: alvo });
      if (r.recusado === "orcamento") toast("Orçamento de turnos deste coordenador esgotado: encerre a conversa para abrir outra.", "erro");
      texto.value = ""; await atualizar();
    } catch (e) { toast(e.message, "erro"); } finally { enviar.disabled = false; }
  } }, texto, el("div", { className: "linha" }, enviar,
    el("span", { className: "mudo", textContent: "O master não executa nada sozinho: cria tarefas dentro da sua autonomia e dos limites da Forja." })));
  texto.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) form.requestSubmit(); });
  raiz.append(el("div", { className: "titulo-vista" }, titulo, el("div", { className: "linha" }, el("button", { type: "button", textContent: "Atualizar", onclick: atualizar }), encerrar)),
    el("div", { className: "master-grade" }, el("section", { className: "master-chat" }, conversa, form), arvoreNo));
  ultimo = { conversa, arvore: arvoreNo, titulo, encerrar };
  atualizar();
}

const reagir = agrupar(() => atualizar());
ouvir("evento", (e) => {
  const t = String(e.tipo);
  if (t.startsWith("coordenacao.") || t === "status.resumo" || (ultimo && /^tarefa\.(estado|transicao)/.test(t))) reagir();
});
