// Cartoes especiais das Configuracoes (ADR-027): servidores de linguagem (instalar/estado), catalogo de autocompletar de codigo
// (ramos, pedir a IA um ramo novo ou atualizar um ramo, importar, revisar) e reciclagem de sessoes antigas (previa e reciclar).
import { api } from "../api.js";
import { comConfirmacao } from "../confirmar.js";
import { invalidarEditor } from "../editorcfg.js";
import { emitir, selecionarTarefa } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";

const LINGUAGENS = [["python", "Python"], ["csharp", "C#"], ["javascript", "JavaScript/TypeScript"], ["html", "HTML"], ["css", "CSS"]];
const cabeca = (p) => [el("h3", { textContent: p.rotulo }), el("p", { textContent: p.explicacao })];
const carregando = (texto = "Carregando…") => el("p", { className: "mudo carregando", role: "status", textContent: texto });

// ---------------------------------------------------------------- servidores de linguagem
export function cartaoLsp(p) {
  const corpo = el("div", { "aria-live": "polite" }, carregando());
  let timer = null;
  const desenhar = async () => {
    clearTimeout(timer);
    let e;
    try { e = await api("GET", "/area/lsp"); } catch (err) { limpar(corpo); corpo.append(el("p", { className: "aviso", role: "alert", textContent: err.message })); return; }
    limpar(corpo);
    if (!e.ativo) corpo.append(el("p", { className: "aviso", textContent: "Os servidores de linguagem estão desligados (opção acima)." }));
    const linhas = e.servidores.map((s) => {
      const estado = s.instalando ? tag("instalando…", "aviso") : s.disponivel ? tag(s.rodando.length ? `ativo em ${s.rodando.join(", ")}` : "instalado", "ok")
        : tag("não instalado", "");
      const ultima = s.ultima_instalacao && !s.instalando && !s.disponivel && s.ultima_instalacao.ok === false
        ? el("details", {}, el("summary", { textContent: "A última instalação falhou" }), el("pre", { className: "saida", textContent: s.ultima_instalacao.saida || "" })) : null;
      const instalar = !s.disponivel && !s.instalando ? el("button", { type: "button", className: "pequeno primario", disabled: !s.pode_instalar,
        title: s.pode_instalar ? s.instalacao : `Requer ${s.requisito}`, textContent: "Instalar",
        onclick: async () => {
          try {
            const r = await comConfirmacao("POST", "/area/lsp/instalar", { servidor: s.id }, { titulo: `Instalar ${s.rotulo}`, detalhe: s.instalacao });
            if (r) { toast(`Instalando ${s.rotulo}… (pode levar alguns minutos)`, "ok"); timer = setTimeout(desenhar, 1500); }
          } catch (err) { toast(err.message, "erro"); }
        } }) : null;
      return el("li", { className: "linha-lsp" }, el("strong", { textContent: s.rotulo }), estado,
        el("span", { className: "mudo trunc", textContent: s.disponivel ? s.executavel : `requer ${s.requisito}` }), el("span", { className: "espaco" }), instalar, ultima);
    });
    corpo.append(el("ul", { className: "lista-lsp" }, ...linhas),
      el("p", { className: "mudo", textContent: `Instalados ficam em ${e.pasta || "<dados>/lsp"}. No máximo ${e.max_servidores} abertos ao mesmo tempo; cada um fecha sozinho depois de 10 minutos sem uso.` }));
    if (e.servidores.some((s) => s.instalando)) timer = setTimeout(() => { invalidarEditor(); desenhar(); }, 3000);
  };
  desenhar();
  return el("section", { className: "card opcao", "data-pref": p.id }, ...cabeca(p), corpo);
}

// ---------------------------------------------------------------- catalogo de autocompletar
export function cartaoCatalogoCodigo(p) {
  const corpo = el("div", {}, carregando());
  const filtro = el("select", { "aria-label": "Linguagem" }, el("option", { value: "", textContent: "Todas as linguagens" }),
    ...LINGUAGENS.map(([v, r]) => el("option", { value: v, textContent: r })));
  const desenhar = async () => {
    let e;
    try { e = await api("GET", "/area/editor"); } catch (err) { limpar(corpo); corpo.append(el("p", { className: "aviso", role: "alert", textContent: err.message })); return; }
    limpar(corpo);
    const ramos = e.ramos.filter((r) => !filtro.value || r.linguagem === filtro.value);
    corpo.append(el("table", { className: "tabela-ramos" },
      el("thead", {}, el("tr", {}, ...["Ramo", "Itens", "Liga quando", "Origem", ""].map((t) => el("th", { scope: "col", textContent: t })))),
      el("tbody", {}, ...ramos.map((r) => el("tr", {},
        el("td", {}, el("strong", { textContent: r.rotulo }), el("div", { className: "mudo", textContent: `${r.id} · ${r.descricao}` })),
        el("td", { textContent: String(r.itens) }),
        el("td", { className: "mudo", textContent: r.detectar.length ? (r.modulo ? `importa ${r.modulo}` : "padrão detectado no arquivo") : "sempre" }),
        el("td", {}, r.nao_revisados ? tag(`${r.nao_revisados} da IA para revisar`, "aviso") : tag(r.origem === "padrao" ? "padrão" : r.origem, "")),
        el("td", { className: "acoes" },
          el("button", { type: "button", className: "pequeno", title: "Pedir à IA para corrigir e completar este ramo", textContent: "Atualizar com IA",
            onclick: () => pedir(r.linguagem, r.id) }),
          r.nao_revisados ? el("button", { type: "button", className: "pequeno", textContent: "Marcar revisado", onclick: async () => {
            try { await api("POST", `/area/codigo/ramos/${encodeURIComponent(r.id)}/revisar`); invalidarEditor(); toast("Revisado.", "ok"); desenhar(); } catch (err) { toast(err.message, "erro"); }
          } }) : null))))));
  };
  const pedido = el("input", { type: "text", maxLength: 500, placeholder: "Ex.: biblioteca polars; padrões de async em C#; Tailwind", "aria-label": "O que buscar" });
  const lng = el("select", { "aria-label": "Linguagem do ramo novo" }, ...LINGUAGENS.map(([v, r]) => el("option", { value: v, textContent: r })));
  const tarefaImp = el("input", { type: "text", maxLength: 64, placeholder: "id da tarefa (T-...)", "aria-label": "Tarefa da IA a importar" });
  const saida = el("div", { role: "status", "aria-live": "polite" });
  async function pedir(linguagem, ramo = "") {
    if (!ramo && !pedido.value.trim()) { pedido.focus(); return toast("Diga o que buscar.", "erro"); }
    if (!confirm("A IA vai pesquisar e documentar (consome créditos). O resultado só entra no catálogo quando você importar. Continuar?")) return;
    try {
      const r = await api("POST", "/area/codigo/ia", { linguagem, ramo, pedido: ramo ? pedido.value.trim() : pedido.value.trim() });
      tarefaImp.value = r.tarefa_id;
      limpar(saida);
      saida.append(el("p", { textContent: `Pedido criado (${r.tarefa_id}). Quando a tarefa terminar, clique em Importar.` }),
        el("button", { type: "button", className: "pequeno", textContent: "Acompanhar a tarefa", onclick: () => { selecionarTarefa(r.tarefa_id); emitir("ir", "tarefas"); } }));
    } catch (err) { toast(err.message, "erro"); }
  }
  const importar = async () => {
    if (!tarefaImp.value.trim()) return tarefaImp.focus();
    try {
      const r = await api("POST", "/area/codigo/ia/importar", { tarefa_id: tarefaImp.value.trim() });
      invalidarEditor();
      toast(`Importado: ${r.importados.map((x) => `${x.ramo} (${x.itens})`).join(", ")}`, "ok");
      if (r.recusados?.length) saida.replaceChildren(el("p", { className: "aviso", textContent: `Recusados: ${r.recusados.join("; ")}` }));
      desenhar();
    } catch (err) { toast(err.message, "erro"); }
  };
  filtro.addEventListener("change", desenhar);
  desenhar();
  return el("section", { className: "card opcao", "data-pref": p.id }, ...cabeca(p),
    el("div", { className: "linha" }, el("span", { className: "mudo", textContent: "Mostrar:" }), filtro),
    corpo,
    el("fieldset", { className: "pedir-ia" }, el("legend", { textContent: "Buscar e incluir algo novo com IA" }),
      el("div", { className: "linha" }, lng, pedido, el("button", { type: "button", className: "primario", textContent: "Pedir à IA", onclick: () => pedir(lng.value) })),
      el("div", { className: "linha" }, tarefaImp, el("button", { type: "button", textContent: "Importar resultado", onclick: importar })), saida));
}

// ---------------------------------------------------------------- reciclagem de sessoes antigas
export function cartaoReciclagem(p) {
  const corpo = el("div", { "aria-live": "polite" });
  const ROT = { criar: "vira nota nova", enriquecer: "completa uma nota existente", coberta: "já coberta por nota validada", sem_valor: "só arquiva (sem valor)" };
  const previa = async () => {
    limpar(corpo); corpo.append(carregando("Calculando…"));
    try {
      const r = await api("GET", "/reciclagem/previa");
      limpar(corpo);
      if (!r.itens.length) { corpo.append(el("p", { className: "mudo", textContent: `Nenhuma sessão parada há mais de ${r.dias} dias.` })); return; }
      corpo.append(el("ul", { className: "lista-reciclagem" }, ...r.itens.map((i) => el("li", {},
        el("span", { className: "trunc", textContent: i.titulo }), tag(ROT[i.acao] || i.acao, i.acao === "sem_valor" ? "" : "ok"),
        el("span", { className: "mudo", textContent: `${i.pontos} pts${i.memoria_titulo ? ` · ${i.memoria_titulo}` : ""}` })))));
      corpo.append(el("button", { type: "button", className: "primario", textContent: `Reciclar ${r.itens.length} agora`, onclick: reciclar }));
    } catch (err) { limpar(corpo); corpo.append(el("p", { className: "aviso", role: "alert", textContent: err.message })); }
  };
  const reciclar = async () => {
    try {
      const r = await api("POST", "/reciclagem", {});
      const n = (k) => r.itens.filter((i) => i.resultado === k).length;
      toast(`Reciclagem: ${n("criada")} nota(s) nova(s), ${n("enriquecida")} completada(s), ${n("sem_valor")} só arquivada(s).`, "ok");
      previa();
    } catch (err) { toast(err.message, "erro"); }
  };
  return el("section", { className: "card opcao", "data-pref": p.id }, ...cabeca(p),
    el("div", { className: "linha" }, el("button", { type: "button", textContent: "Ver o que seria reciclado", onclick: previa })), corpo);
}
