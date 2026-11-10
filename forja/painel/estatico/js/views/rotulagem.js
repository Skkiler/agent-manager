// 4.8: avaliar a busca no SEU corpus. Voce escreve uma pergunta real, marca o que e relevante e ve recall/MRR/nDCG.
// Os candidatos misturam o baseline e a busca nova em ordem embaralhada: assim voce nao rotula so o que a busca ja acha.
import { api } from "../api.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";

const fmt = (m, k) => `recall@${k} ${m[`recall@${k}`].toFixed(2)} · MRR ${m.mrr.toFixed(2)} · nDCG@${k} ${m[`ndcg@${k}`].toFixed(2)}`;

function painelMetricas(e) {
  if (!e.metricas) return el("p", { className: "mudo", textContent: e.aviso || "Sem medicao ainda." });
  const { baseline, nova } = e.metricas;
  return el("div", {},
    el("p", {}, el("strong", { textContent: "Busca atual: " }), fmt(nova.global, e.k)),
    el("p", { className: "mudo" }, el("strong", { textContent: "Baseline lexical: " }), fmt(baseline.global, e.k)),
    el("p", { className: "mudo", textContent: `${e.com_relevantes} pergunta(s) com algo relevante; ${e.sem_relevantes} sem nada relevante no corpus.` }),
    e.aviso ? el("p", { className: "aviso", textContent: e.aviso }) : null);
}

export async function abrirRotulagem(namespaces) {
  const caixa = el("div", { className: "rotulagem" });
  const d = dialogo("Avaliar a busca com perguntas reais", caixa);
  let estado = await api("GET", "/busca/rotulagem");
  const metricas = el("section", { className: "card", "aria-live": "polite" });
  const lista = el("ul", { className: "mudo" });
  const pergunta = el("input", { type: "search", maxLength: 300, placeholder: "Ex.: como faço backup do banco sem parar o servidor?", "aria-label": "Pergunta real" });
  const categoria = el("input", { maxLength: 40, value: "geral", "aria-label": "Categoria (opcional)" });
  const candidatos = el("div", { role: "group", "aria-label": "Resultados para marcar" });

  const redesenhar = () => {
    limpar(metricas); metricas.append(el("h3", { textContent: `Medicao (${estado.rotulados} rotulada(s))` }), painelMetricas(estado));
    limpar(lista);
    lista.append(...estado.casos.slice(-15).reverse().map((c) => el("li", {}, tag(c.categoria), ` ${c.consulta} `, tag(`${c.relevantes.length} relevante(s)`),
      el("button", { type: "button", textContent: "remover", "aria-label": `Remover rotulo ${c.consulta}`, onclick: async () => {
        try { await api("DELETE", `/busca/rotulagem/casos/${c.id}?expected_version=${estado.versao}`); estado = await api("GET", "/busca/rotulagem"); redesenhar(); }
        catch (e) { toast(e.message, "erro"); }
      } }))));
  };

  const buscar = async () => {
    limpar(candidatos);
    const q = pergunta.value.trim();
    if (q.length < 2) return toast("Escreva uma pergunta.", "erro");
    try {
      const r = await api("POST", "/busca/rotulagem/candidatos", { consulta: q, namespaces: [...namespaces] });
      if (!r.candidatos.length) candidatos.append(el("p", { className: "mudo", textContent: "Nenhum resultado. Salve assim mesmo: uma pergunta sem resposta tambem conta." }));
      const marcas = r.candidatos.map((c) => {
        const caixa = el("input", { type: "checkbox", value: c.id, "aria-label": `Relevante: ${c.titulo || c.caminho || c.id}` });
        return { caixa, no: el("label", { className: "card linha", style: "align-items:flex-start" }, caixa,
          el("div", {}, el("strong", { textContent: c.titulo || c.caminho || c.id }), el("div", { className: "mudo", textContent: (c.trecho || c.resumo || "").slice(0, 240) }),
            el("div", {}, tag(c.fonte || "?"), tag(c.namespace || ""))) ) };
      });
      const salvar = el("button", { type: "button", className: "primario", textContent: "Salvar rotulos desta pergunta", onclick: async () => {
        try {
          await api("POST", "/busca/rotulagem/casos", { expected_version: estado.versao, consulta: r.consulta, namespaces: r.namespaces, categoria: categoria.value.trim() || "geral",
            relevantes: marcas.filter((m) => m.caixa.checked).map((m) => m.caixa.value), vistos: r.candidatos.length ? r.candidatos.map((c) => c.id) : ["(nenhum)"] });
          estado = await api("GET", "/busca/rotulagem"); pergunta.value = ""; limpar(candidatos); redesenhar(); toast("Rotulos salvos", "ok");
        } catch (e) { toast(e.status === 409 ? "Os rotulos mudaram em outra aba. Reabra." : e.message, "erro"); }
      } });
      candidatos.append(el("p", { className: "mudo", textContent: "Marque TODOS os resultados que respondem a pergunta (ordem embaralhada de proposito)." }),
        ...marcas.map((m) => m.no), el("div", { className: "linha" }, salvar));
    } catch (e) { toast(e.message, "erro"); }
  };
  pergunta.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); buscar(); } });

  caixa.append(
    el("p", { textContent: "Escreva perguntas que voce realmente faria. Os rotulos ficam so no seu perfil (fora do Git) e guardam a pergunta e os IDs marcados, nunca o conteudo." }),
    metricas,
    el("div", { className: "linha" }, pergunta, el("button", { type: "button", textContent: "Ver resultados", onclick: buscar })),
    el("label", { className: "campo" }, el("span", { textContent: "Categoria (opcional, ex.: codigo, decisoes, procedimentos)" }), categoria),
    candidatos, el("h3", { textContent: "Ultimas perguntas rotuladas" }), lista,
    el("div", { className: "linha" }, el("button", { type: "button", textContent: "Fechar", onclick: () => d.fechar() })));
  redesenhar();
  pergunta.focus();
}
