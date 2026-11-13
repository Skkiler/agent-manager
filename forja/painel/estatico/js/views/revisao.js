// Fila de revisao do segundo cerebro: notas candidatas + sugestoes da organizacao automatica (duplicata, desatualizada,
// ligacao). Nada muda sem o usuario decidir; cada acao usa a API normal da memoria (auditavel).
import { api } from "../api.js";
import { dataCurta, el, janela, limpar, tag, toast } from "../ui.js";

const TIPOS = { duplicata: ["Duplicata", "aviso"], desatualizada: ["Desatualizada", "aviso"], ligacao: ["Ligação sugerida", ""],
  topico: ["Tópico sugerido", "ok"] };

export async function contarRevisao() {
  try { return (await api("GET", "/memorias/revisao?limite=200")).total; } catch { return null; }
}

async function transicionar(m, para, motivo) {
  await api("POST", `/memorias/${m.id}/transicao`, { para, expected_version: m.versao, motivo });
}

function cartaoSugestao(s, aoMudar) {
  const [rotulo, cls] = TIPOS[s.tipo] || [s.tipo, ""];
  const titulos = (s.dados && s.dados.titulos) || {};
  let fica = null;
  const lista = el("ul", { className: "mudo" }, ...s.memorias.map((id) => el("li", { textContent: titulos[id] || id })));
  const extras = [];
  if (s.tipo === "duplicata") {
    fica = el("select", { "aria-label": "Qual nota fica" }, ...s.memorias.map((id) => el("option", { value: id, textContent: titulos[id] || id,
      selected: id === s.dados?.vencedora_sugerida })));
    extras.push(el("label", { className: "campo" }, el("span", { textContent: "Fica (as outras viram 'substituída', nada é apagado)" }), fica));
  }
  const decidir = async (aceitar) => {
    try {
      await api("POST", `/memorias/sugestoes/${s.id}/decidir`, { aceitar, vencedora_id: fica ? fica.value : null });
      toast(!aceitar ? "Sugestão rejeitada" : s.tipo === "topico" ? "O Kiro está escrevendo o tópico: acompanhe a tarefa no quadro." : "Sugestão aplicada", "ok");
      aoMudar();
    } catch (e) { toast(e.message, "erro"); }
  };
  const acao = { duplicata: "Unir", desatualizada: s.dados?.destino === "revogado" ? "Revogar" : "Marcar obsoleta", ligacao: "Ligar",
    topico: "Resumir com o Kiro" }[s.tipo] || "Aceitar";
  return el("article", { className: "card sugestao", "aria-label": `${rotulo}: ${s.motivo}` },
    el("div", { className: "linha" }, tag(rotulo, cls), el("span", { className: "mudo", textContent: dataCurta(s.criado_em) })),
    el("p", { textContent: s.motivo }), lista, ...extras,
    el("div", { className: "linha" }, el("button", { type: "button", className: "primario", textContent: acao, onclick: () => decidir(true) }),
      el("button", { type: "button", textContent: "Rejeitar", onclick: () => decidir(false) })));
}

function cartaoCandidata(m, aoMudar) {
  const agir = async (para, motivo, confirmar) => {
    if (confirmar && !confirm(confirmar)) return;
    try { await transicionar(m, para, motivo); toast("Nota atualizada", "ok"); aoMudar(); } catch (e) { toast(e.message, "erro"); }
  };
  return el("article", { className: "card candidata", "aria-label": `Nota candidata: ${m.titulo}` },
    el("div", { className: "linha" }, el("strong", { textContent: m.titulo }), tag(m.namespace), m.usos ? tag(`${m.usos} uso(s)`, "ok") : null,
      m.suspeita_injecao ? tag("possível prompt injection", "erro") : null),
    m.resumo ? el("p", { className: "mudo", textContent: m.resumo }) : null,
    m.tags?.length ? el("div", { className: "linha" }, ...m.tags.slice(0, 8).map((t) => tag(`#${t}`))) : null,
    el("div", { className: "linha" },
      el("button", { type: "button", className: "primario", textContent: "Promover (observada)", title: "Você conferiu e a nota faz sentido; validar exige evidência real",
        onclick: () => agir("observado", "revisada na fila") }),
      el("button", { type: "button", textContent: "Contestar", onclick: () => agir("contestado", "contestada na revisão") }),
      el("button", { type: "button", textContent: "Revogar", onclick: () => agir("revogado", "revogada na revisão", `Revogar "${m.titulo}"? Ela sai das buscas.`) })));
}

/** Janela da fila. `aoFechar` atualiza o contador da barra lateral. */
export function abrirRevisao(aoFechar) {
  const status = el("p", { className: "mudo", role: "status", "aria-live": "polite", textContent: "Carregando…" });
  const sugestoes = el("section", { "aria-label": "Sugestões da organização automática" });
  const candidatas = el("section", { "aria-label": "Notas candidatas" });
  const organizar = el("button", { type: "button", textContent: "Organizar agora", title: "Procura duplicatas, notas velhas e ligações (local, sem IA)",
    onclick: async () => {
      organizar.disabled = true;
      try { const r = await api("POST", "/memorias/organizar"); toast(`${r.total_novas} sugestão(ões) nova(s) em ${r.analisadas} notas`, "ok"); await desenhar(); }
      catch (e) { toast(e.message, "erro"); } finally { organizar.disabled = false; }
    } });
  const corpo = el("div", { className: "revisao" }, el("div", { className: "linha" }, organizar, status), sugestoes, candidatas);
  janela("Revisão do segundo cérebro", corpo, { classe: "janela-larga", aoFechar });
  async function desenhar() {
    try {
      const f = await api("GET", "/memorias/revisao?limite=100");
      status.textContent = `${f.sugestoes.length} sugestão(ões) e ${f.candidatas.length} nota(s) candidata(s)` + (f.modo === "desligada" ? " · organização automática desligada" : "");
      limpar(sugestoes); limpar(candidatas);
      sugestoes.append(el("h3", { textContent: "Sugestões" }), ...(f.sugestoes.length ? f.sugestoes.map((s) => cartaoSugestao(s, desenhar))
        : [el("p", { className: "mudo", textContent: "Nada a organizar agora." })]));
      candidatas.append(el("h3", { textContent: "Notas candidatas" }), ...(f.candidatas.length ? f.candidatas.map((m) => cartaoCandidata(m, desenhar))
        : [el("p", { className: "mudo", textContent: "Nenhuma nota esperando revisão." })]));
    } catch (e) { status.textContent = `Erro: ${e.message}`; }
  }
  desenhar();
}
