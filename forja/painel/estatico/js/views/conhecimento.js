// Area Conhecimento (ADR-028): abas "Buscar e aprender" (estudo de pasta/topico e reciclagem de sessoes) e "Organizar"
// (saude e modularidade do grafo, trechos repetidos entre notas, organizar e deduplicar com IA -> fila de revisao).
import { api } from "../api.js";
import { emitir, selecionarTarefa } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";
import { formularioEstudo } from "./memoria.js";
import { listarPastas } from "./pastas.js";

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
        cartaoLote(),
        el("section", { className: "card" }, el("h2", { textContent: "Aprender com o que já foi feito" }),
          el("p", { textContent: "Sessões antigas (tarefas terminadas e sub-masters encerrados) viram conhecimento: decisões, o que foi resolvido, erros e pendências, sem duplicar notas que já existem." }),
          el("button", { type: "button", textContent: "Ver o que seria reciclado", onclick: verReciclagem }), recicla,
          el("h3", { textContent: "Como as notas são escritas" }),
          el("ul", { className: "regras-nota" }, ...REGRAS.map((r) => el("li", { textContent: r })))))));
  },
};

// ---------------------------------------------------------------- alimentacao em lote (ADR-029)
const ETAPAS = { na_fila: "na fila", indexado: "indexado", estudando: "estudando", estudado: "estudado", ja_estudado: "já estudado",
  teto_de_creditos: "parou no teto", estudo_recusado: "recusado" };
const lista = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);

function cartaoLote() {
  const raiz = el("input", { type: "text", maxLength: 500, required: true, placeholder: "C:\\Codigos (pasta permitida em Configurações > Privacidade)", "aria-label": "Pasta com os projetos" });
  const empresa = el("input", { type: "text", maxLength: 41, value: "trabalho", pattern: "[a-z0-9][a-z0-9._-]{0,40}", "aria-label": "Identificador da empresa" });
  const interno = el("input", { type: "text", maxLength: 41, value: "proprios", pattern: "[a-z0-9][a-z0-9._-]{0,40}", "aria-label": "Identificador dos projetos próprios" });
  const proprios = el("input", { type: "text", maxLength: 500, placeholder: "Ex.: Estudos e projetos pessoais", "aria-label": "Trechos do caminho que marcam projeto próprio" });
  const excluir = el("input", { type: "text", maxLength: 500, placeholder: "Opcional: nomes de pastas a pular", "aria-label": "Pastas a pular" });
  const estudar = el("input", { type: "checkbox", checked: true });
  const paralelo = el("select", { "aria-label": "Estudos ao mesmo tempo" }, ...[1, 2, 3, 4].map((n) => el("option", { value: n, textContent: String(n), selected: n === 2 })));
  const teto = el("input", { type: "number", min: 0, max: 1000, step: 1, value: 300, "aria-label": "Teto de créditos" });
  const saida = el("div", { "aria-live": "polite" });
  const estado = el("div", { "aria-live": "polite" });
  const pedido = () => ({ raiz: raiz.value.trim(), empresa_id: empresa.value.trim() || "trabalho", interno_id: interno.value.trim() || "proprios",
    interno_contem: lista(proprios.value), excluir: lista(excluir.value), estudar: estudar.checked, paralelo: Number(paralelo.value), teto_creditos: Number(teto.value) || 0 });
  const previa = async () => {
    if (!raiz.value.trim()) return raiz.focus();
    limpar(saida); saida.append(carregando("Procurando projetos…"));
    try {
      const d = await api("POST", "/estudos/lote/descobrir", pedido());
      limpar(saida);
      saida.append(el("p", { textContent: `${d.projetos.length} projeto(s): ${Object.entries(d.por_escopo).map(([k, v]) => `${v} ${k === "empresa" ? "da empresa" : "próprio(s)"}`).join(", ")}; ${d.ignorados.length} pasta(s) puladas.` }),
        el("table", { className: "tabela-lote" }, el("thead", {}, el("tr", {}, ...["Projeto", "Escopo", "Pasta no segundo cérebro", "Código"].map((x) => el("th", { scope: "col", textContent: x })))),
          el("tbody", {}, ...d.projetos.map((p) => el("tr", {}, el("td", { textContent: p.grupo ? `${p.grupo} / ${p.nome}` : p.nome }),
            el("td", {}, tag(p.escopo === "empresa" ? "empresa" : "próprio", p.escopo === "empresa" ? "aviso" : "ok")), el("td", { textContent: p.namespace }),
            el("td", { textContent: Object.entries(p.linguagens).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(", ") || "-" }))))));
    } catch (e) { limpar(saida); saida.append(el("p", { className: "aviso", role: "alert", textContent: e.message })); }
  };
  let relogio = null;
  const acompanhar = async () => {
    clearTimeout(relogio);
    if (!estado.isConnected && relogio) return;
    try {
      const e = await api("GET", "/estudos/lote");
      limpar(estado);
      if (!e.projetos?.length) return;
      const cont = {};
      for (const p of e.projetos) cont[p.etapa] = (cont[p.etapa] || 0) + 1;
      estado.append(el("p", { textContent: `Lote ${e.rodando ? "rodando" : e.situacao} · ${e.projetos.length} projeto(s) · ${Number(e.creditos || 0).toFixed(2)} crédito(s)${e.teto_atingido ? " · teto atingido" : ""}` }),
        el("div", { className: "linha" }, ...Object.entries(cont).map(([k, v]) => tag(`${ETAPAS[k] || k.replace("estudo_", "estudo ")}: ${v}`, k === "estudado" ? "ok" : k.startsWith("estudo_") ? "aviso" : ""))),
        ...(e.rodando ? [el("button", { type: "button", textContent: "Parar de iniciar estudos", onclick: async () => { await api("POST", "/estudos/lote/cancelar"); acompanhar(); } })] : []));
      if (e.rodando) relogio = setTimeout(acompanhar, 5000);
    } catch { /* sem lote ainda */ }
  };
  const iniciar = async () => {
    if (!raiz.value.trim()) return raiz.focus();
    const p = pedido();
    if (p.estudar && !confirm(`Indexar o código e estudar cada projeto com IA (até ${p.teto_creditos || "sem teto de"} créditos, ${p.paralelo} por vez)? As notas entram como candidatas.`)) return;
    try { await api("POST", "/estudos/lote", p); toast("Alimentação em lote iniciada", "ok"); relogio = 1; acompanhar(); } catch (e) { toast(e.message, "erro"); }
  };
  requestAnimationFrame(acompanhar);
  return el("section", { className: "card" }, el("h2", { textContent: "Alimentar com uma pasta de projetos" }),
    el("p", { textContent: "Cada projeto vira uma pasta no segundo cérebro (pessoal/empresa/<id>/projetos ou pessoal/interno/<id>/projetos) com o código indexado e uma nota-hub. Com IA, um agente estuda cada um e separa o que é do projeto, o que é de um sistema compartilhado (nota da entidade, uma só) e o que é técnica reutilizável. Pastas de logs e dados e arquivos de segredo ficam de fora." }),
    el("label", { className: "campo" }, el("span", { textContent: "Pasta com os projetos" }), raiz),
    el("div", { className: "linha" }, el("label", { className: "campo" }, el("span", { textContent: "Empresa (id)" }), empresa),
      el("label", { className: "campo" }, el("span", { textContent: "Próprios (id)" }), interno)),
    el("label", { className: "campo" }, el("span", { textContent: "Marca de projeto próprio no caminho (separe por vírgula)" }), proprios),
    el("label", { className: "campo" }, el("span", { textContent: "Pular" }), excluir),
    el("div", { className: "linha" }, el("label", {}, estudar, " estudar com IA"), el("label", {}, "ao mesmo tempo ", paralelo), el("label", {}, "teto de créditos ", teto)),
    el("div", { className: "linha" }, el("button", { type: "button", textContent: "Ver projetos (prévia)", onclick: previa }),
      el("button", { type: "button", className: "primario", textContent: "Iniciar", onclick: iniciar })), saida, estado);
}

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
    listarPastas().then((ps) => escopo.append(...ps.filter((x) => x.nivel >= 1 && x.total > 0 && !x.namespace.startsWith("publico/forja-base"))
      .map((x) => el("option", { value: x.namespace, textContent: `${"· ".repeat(x.nivel)}${x.namespace} (${x.total})` }))));
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
