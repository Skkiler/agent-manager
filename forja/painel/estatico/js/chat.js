// Modo chat (estilo app do Codex): lista de conversas a esquerda (master, o que precisa de voce e as tarefas por projeto) e a
// conversa escolhida ocupando o resto da tela. Usa as mesmas telas da barra da direita (conversa/decisoes/master).
import { api } from "./api.js";
import { emitir, estado, selecionarTarefa } from "./estado.js";
import { el, limpar, tag } from "./ui.js";

const ROTULO_ESTADO = { bloqueada: "precisa de você", aguardando_aprovacao: "aprovação", executando: "executando", validando: "validando",
  concluida: "concluída", falhou: "falhou", cancelada: "cancelada", pronta: "pronta", preparada: "preparada", rascunho: "rascunho" };
let fio = JSON.parse(localStorage.getItem("forja_fio") || '{"tipo":"master"}');
const lembrar = () => localStorage.setItem("forja_fio", JSON.stringify(fio));

export async function montarChat(raiz, { conversa, decisoes, master }) {
  if (fio.tipo === "tarefa" && fio.id !== estado.tarefaId && estado.tarefaId) fio = { tipo: "tarefa", id: estado.tarefaId };
  const [quadro, projetos] = await Promise.all([api("GET", "/kanban").catch(() => null), api("GET", "/projetos").catch(() => [])]);
  const nomes = new Map(projetos.map((p) => [p.id, p.nome]));
  const cartoes = (quadro?.colunas || []).flatMap((c) => c.cartoes);
  const painel = el("section", { className: "chat-painel", "aria-label": "Conversa escolhida" });
  const lista = el("nav", { className: "chat-fios", "aria-label": "Conversas" });

  const desenharPainel = async () => {
    limpar(painel);
    for (const b of lista.querySelectorAll("button[data-fio]")) b.setAttribute("aria-current", b.dataset.fio === chave(fio) ? "true" : "false");
    if (fio.tipo === "master") { master.montar(painel, { compacto: false }); return; }
    const c = cartoes.find((x) => x.id === fio.id);
    painel.append(el("div", { className: "titulo-vista" }, el("h1", { className: "trunc", textContent: c?.titulo || fio.id }),
      c ? tag(ROTULO_ESTADO[c.estado] || c.estado, c.precisa_de_voce ? "aviso" : "") : null, c?.projeto_id ? el("span", { className: "mudo trunc", textContent: nomes.get(c.projeto_id) || "" }) : null,
      el("span", { className: "espaco" }),
      el("button", { type: "button", className: "pequeno", title: "Abrir esta conversa numa janela flutuante e continuar usando a tela", onclick: () => emitir("destacar", fio.id) }, "⧉ Janela"),
      el("button", { type: "button", className: "pequeno", title: "Ver o agente desta tarefa na oficina", onclick: () => emitir("ir", "agentes") }, "Ver na oficina")));
    const corpo = el("div", { className: "chat-conversa" });
    painel.append(corpo);
    const recarregar = async () => { limpar(corpo); await decisoes(corpo, fio.id, recarregar); await conversa(corpo, fio.id, recarregar); };
    await recarregar();
  };
  const escolher = (novo) => {
    fio = novo; lembrar();
    if (novo.tipo === "tarefa") selecionarTarefa(novo.id); else desenharPainel();
  };
  const chave = (f) => (f.tipo === "master" ? "master" : `t:${f.id}`);
  const botaoFio = (f, rotulo, extra = null, titulo = "") => el("button", { type: "button", className: "fio", dataset: { fio: chave(f) }, title: titulo || rotulo,
    "aria-current": chave(f) === chave(fio) ? "true" : "false", onclick: () => escolher(f) }, el("span", { className: "trunc", textContent: rotulo }), extra);

  const precisa = cartoes.filter((c) => c.precisa_de_voce);
  const porProjeto = new Map();
  for (const c of cartoes) {
    if (!porProjeto.has(c.projeto_id)) porProjeto.set(c.projeto_id, []);
    porProjeto.get(c.projeto_id).push(c);
  }
  lista.append(...[
    el("button", { type: "button", className: "primario novo-pedido", textContent: "✎ Novo pedido ao master", onclick: () => {
      escolher({ tipo: "master" });
      requestAnimationFrame(() => painel.querySelector("textarea")?.focus());
    } }),
    el("h3", { textContent: "Master" }), botaoFio({ tipo: "master" }, "Conversa com o master", null, "O master cria e acompanha as tarefas"),
    precisa.length ? el("h3", { textContent: `Precisa de você (${precisa.length})` }) : null,
    ...precisa.map((c) => botaoFio({ tipo: "tarefa", id: c.id }, c.titulo, tag(ROTULO_ESTADO[c.estado] || c.estado, "aviso"))),
    el("div", { className: "linha" }, el("h3", { textContent: "Projetos" }), el("span", { className: "espaco" }),
      el("button", { type: "button", className: "pequeno", title: "Criar projeto (Ctrl+Alt+N)", "aria-label": "Novo projeto", onclick: () => emitir("novo-projeto") }, "+ Projeto")),
    ...[...porProjeto.entries()].map(([pid, cs]) => {
      cs.sort((a, b) => String(b.atualizado_em).localeCompare(String(a.atualizado_em)));
      return el("details", { open: cs.some((c) => chave({ tipo: "tarefa", id: c.id }) === chave(fio)) || porProjeto.size <= 3 },
        el("summary", { className: "trunc", textContent: `${nomes.get(pid) || pid} (${cs.length})` }),
        ...cs.slice(0, 12).map((c) => botaoFio({ tipo: "tarefa", id: c.id }, c.titulo, el("span", { className: `ponto estado-${c.estado}`, "aria-hidden": "true" }),
          `${c.titulo} · ${ROTULO_ESTADO[c.estado] || c.estado}`)));
    }),
    !cartoes.length ? el("p", { className: "mudo", textContent: "Nenhuma tarefa ainda: comece por um pedido ao master." }) : null].filter(Boolean)); // DOM append escreveria "null"
  raiz.append(el("div", { className: "chat-grade" }, lista, painel));
  await desenharPainel();
}
