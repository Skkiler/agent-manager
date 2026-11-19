// Area Conhecimento (ADR-028): abas "Buscar e aprender" (estudo de pasta/topico e reciclagem de sessoes) e "Organizar"
// (saude e modularidade do grafo, trechos repetidos entre notas, organizar e deduplicar com IA -> fila de revisao).
import { api } from "../api.js";
import { emitir, selecionarTarefa } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";
import { formularioEstudo } from "./memoria.js";

const cabeca = (titulo, texto) => [el("h1", { textContent: titulo }), el("p", { className: "subtitulo", textContent: texto })];
const carregando = (t = "Carregando…") => el("p", { className: "mudo carregando", role: "status", textContent: t });

// ---------------------------------------------------------------- buscar e aprender
export const aprender = {
  montar(raiz) {
    limpar(raiz);
    const recicla = el("div", { "aria-live": "polite" });
    const verReciclagem = async () => {
      limpar(recicla); recicla.append(carregando("Calculando…"));
      try {
        const r = await api("GET", "/reciclagem/previa");
        limpar(recicla);
        if (!r.itens.length) return recicla.append(el("p", { className: "mudo", textContent: `Nenhuma sessão parada há mais de ${r.dias} dias.` }));
        const n = (a) => r.itens.filter((i) => i.acao === a).length;
        recicla.append(el("p", { textContent: `${r.itens.length} sessão(ões) antiga(s): ${n("criar")} viram nota nova, ${n("enriquecer")} completam uma nota, ${n("sem_valor")} só são arquivadas.` }),
          el("button", { type: "button", className: "primario", textContent: "Reciclar agora", onclick: async () => {
            try { const x = await api("POST", "/reciclagem", {}); toast(`${x.reciclados} sessão(ões) recicladas`, "ok"); verReciclagem(); } catch (e) { toast(e.message, "erro"); }
          } }));
      } catch (e) { limpar(recicla); recicla.append(el("p", { className: "aviso", role: "alert", textContent: e.message })); }
    };
    raiz.append(el("div", { className: "conhecimento-aba" },
      ...cabeca("Buscar e aprender", "Peça a um agente para estudar uma pasta ou pesquisar um tópico. Ele cria notas modulares (um assunto por nota, ligadas por tópico) que entram como candidatas."),
      el("div", { className: "grade-conhecimento" },
        el("section", { className: "card" }, el("h2", { textContent: "Novo estudo" }), formularioEstudo()),
        el("section", { className: "card" }, el("h2", { textContent: "Aprender com o que já foi feito" }),
          el("p", { textContent: "Sessões antigas (tarefas terminadas e sub-masters encerrados) viram conhecimento: decisões, o que foi resolvido, erros e pendências, sem duplicar notas que já existem." }),
          el("button", { type: "button", textContent: "Ver o que seria reciclado", onclick: verReciclagem }), recicla,
          el("h3", { textContent: "Como as notas são escritas" }),
          el("ul", { className: "regras-nota" }, ...REGRAS.map((r) => el("li", { textContent: r })))))));
  },
};

const REGRAS = [
  "Um assunto por nota, com título que diz o assunto (ex.: \"Sistema Função: automações por HTTP\").",
  "60 a 350 palavras; acima de 600 vira subtópicos ligados; nota muito curta e solta é juntada a outra.",
  "Primeira linha resume a nota em uma frase.",
  "O que vale para um sistema ou biblioteca fica numa nota só (da entidade); as outras citam [[essa nota]] em vez de repetir.",
  "Tags: a entidade, o tipo (decisão, procedimento, armadilha) e o projeto.",
  "Antes de criar, o agente busca; se já existe, completa a nota existente.",
];

// ---------------------------------------------------------------- organizar e deduplicar
const ROTULOS = { longas: "Notas longas demais", curtas_soltas: "Notas curtas e soltas", sem_tags: "Sem tags úteis", orfas: "Sem nenhuma ligação",
  links_fantasmas: "Links para notas que não existem" };

export const organizar = {
  montar(raiz) {
    limpar(raiz);
    const escopo = el("select", { "aria-label": "Quais notas analisar" }, el("option", { value: "", textContent: "Todas as notas permitidas" }),
      el("option", { value: "pessoal", textContent: "Pessoais (projetos, estudos, aprendizados)" }), el("option", { value: "publico", textContent: "Públicas" }));
    const base = el("input", { type: "checkbox" });
    const painel = el("div", { "aria-live": "polite" });
    const foco = el("input", { type: "text", maxLength: 500, placeholder: "Opcional: ex.: notas do sistema Função; automações HTTP", "aria-label": "Foco da organização" });
    const exec = el("input", { type: "checkbox", checked: true });
    const tarefa = el("input", { type: "text", maxLength: 64, placeholder: "id da tarefa (T-...)", "aria-label": "Tarefa de organização a importar" });
    const saidaIa = el("div", { role: "status", "aria-live": "polite" });
    const ns = () => (escopo.value ? [escopo.value] : null);
    const consultaNs = () => [...(escopo.value ? [`namespace=${encodeURIComponent(escopo.value)}`] : []), base.checked ? "base=true" : ""].filter(Boolean).join("&");

    async function analisar() {
      limpar(painel); painel.append(carregando("Analisando o grafo…"));
      let s;
      try { s = await api("GET", `/memorias/saude?${consultaNs()}`); } catch (e) { limpar(painel); painel.append(el("p", { className: "aviso", role: "alert", textContent: e.message })); return; }
      limpar(painel);
      if (!s.notas) { painel.append(el("p", { className: "mudo", textContent: "Nenhuma nota neste escopo ainda. Use Buscar e aprender para alimentar o segundo cérebro." })); return; }
      const nivel = s.pontuacao >= 80 ? "ok" : s.pontuacao >= 55 ? "aviso" : "erro";
      painel.append(el("div", { className: "metricas-saude" },
        el("div", { className: `medidor medidor-${nivel}`, role: "img", "aria-label": `Modularidade ${s.pontuacao} de 100` },
          el("strong", { textContent: String(s.pontuacao) }), el("span", { textContent: "modularidade" })),
        metrica("Notas", s.notas), metrica("Palavras (mediana)", `${s.palavras.mediana} · ideal ${s.ideal_palavras.join("-")}`),
        metrica("Texto repetido", `${s.percentual_repetido}%`), metrica("Órfãs", s.contagem.orfas), metrica("Sugestões pendentes", s.contagem.sugestoes_pendentes)));
      if (s.repeticoes.length) {
        painel.append(el("h2", { textContent: `Trechos repetidos em várias notas (${s.repeticoes.length})` }),
          el("p", { className: "mudo", textContent: "Cada grupo é candidato a uma nota-módulo: a informação fica escrita uma vez, ligada à entidade, e as notas passam a citar o módulo." }),
          el("ul", { className: "lista-repeticoes" }, ...s.repeticoes.map((r) => el("li", { className: "card" },
            el("div", { className: "linha" }, tag(`${r.notas.length} notas`, "aviso"), r.entidade ? tag(`entidade: ${r.entidade}`, "ok") : null,
              el("span", { className: "mudo", textContent: `≈ ${r.economia_caracteres} caracteres a menos` })),
            el("blockquote", { textContent: r.trecho.slice(0, 400) }),
            el("details", {}, el("summary", { textContent: "Notas" }), el("ul", {}, ...r.notas.map((i) => el("li", { textContent: r.titulos[i] || i }))))))));
      } else painel.append(el("p", { className: "mudo", textContent: "Nenhum trecho se repete entre notas." }));
      const problemas = Object.entries(s.problemas).filter(([, l]) => l.length);
      if (problemas.length) {
        painel.append(el("h2", { textContent: "Notas fora do ponto" }), ...problemas.map(([k, l]) => el("details", { className: "card" },
          el("summary", { textContent: `${ROTULOS[k] || k} (${s.contagem[k] ?? l.length})` }),
          el("ul", {}, ...l.map((x) => el("li", { textContent: `${x.titulo}${x.palavras !== undefined ? ` · ${x.palavras} palavras` : ""}${x.link ? ` → [[${x.link}]]` : ""}` }))))));
      }
    }

    const pedirIa = async () => {
      if (exec.checked && !confirm("O agente vai ler o grafo e propor um plano (consome créditos). Nada muda sem você aceitar na Revisão. Continuar?")) return;
      try {
        const r = await api("POST", "/memorias/organizar-ia", { namespaces: ns(), foco: foco.value.trim(), executar: exec.checked });
        tarefa.value = r.tarefa_id;
        limpar(saidaIa);
        saidaIa.append(el("p", { textContent: `Pedido criado (${r.tarefa_id}). Quando a tarefa terminar, o plano entra sozinho na Revisão; se não entrar, use Importar.` }),
          el("button", { type: "button", className: "pequeno", textContent: "Acompanhar a tarefa", onclick: () => { selecionarTarefa(r.tarefa_id); emitir("ir", "tarefas"); } }));
      } catch (e) { toast(e.message, "erro"); }
    };
    const importar = async () => {
      if (!tarefa.value.trim()) return tarefa.focus();
      try {
        const r = await api("POST", "/memorias/organizar-ia/importar", { tarefa_id: tarefa.value.trim() });
        toast(`${r.total} sugestão(ões) na Revisão`, "ok");
        if (r.recusados?.length) saidaIa.replaceChildren(el("p", { className: "aviso", textContent: `Recusados: ${r.recusados.join("; ")}` }));
      } catch (e) { toast(e.message, "erro"); }
    };
    const local = async () => {
      try { const r = await api("POST", "/memorias/organizar"); toast(`${r.total_novas} sugestão(ões) nova(s) em ${r.analisadas} notas`, "ok"); } catch (e) { toast(e.message, "erro"); }
    };
    escopo.addEventListener("change", analisar); base.addEventListener("change", analisar);
    raiz.append(el("div", { className: "conhecimento-aba" },
      ...cabeca("Organizar e deduplicar", "Mede a modularidade do grafo e tira repetição: o que várias notas repetem sobre a mesma coisa vira uma nota-módulo ligada à entidade, e as outras só apontam para ela."),
      el("div", { className: "linha barra-organizar" }, el("span", { className: "mudo", textContent: "Analisar:" }), escopo,
        el("label", {}, base, " incluir a base da Forja (só leitura)"), el("button", { type: "button", textContent: "Analisar de novo", onclick: analisar })),
      painel,
      el("section", { className: "card" }, el("h2", { textContent: "Organizar com IA" }),
        el("p", { textContent: "O agente recebe só os trechos repetidos e a lista compacta das notas, lê as que precisar e devolve um plano: módulos, ligações, fusões, divisões e tags. Tudo vira sugestão na Revisão." }),
        el("div", { className: "linha" }, foco, el("label", {}, exec, " executar agora"), el("button", { type: "button", className: "primario", textContent: "Organizar com IA", onclick: pedirIa })),
        el("div", { className: "linha" }, tarefa, el("button", { type: "button", textContent: "Importar plano", onclick: importar }),
          el("button", { type: "button", textContent: "Sugestões locais (sem IA)", title: "Duplicatas, notas velhas e ligações por tags", onclick: local }),
          el("button", { type: "button", textContent: "Abrir a Revisão", onclick: () => emitir("ir", "revisao") })), saidaIa)));
    analisar();
  },
};

function metrica(rotulo, valor) {
  return el("div", { className: "metrica" }, el("strong", { textContent: String(valor) }), el("span", { className: "mudo", textContent: rotulo }));
}
