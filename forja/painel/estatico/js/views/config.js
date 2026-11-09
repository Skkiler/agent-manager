// Configuracao (modelo e esforco de IA por parte, nivel de detalhe) e pedido de revisao do esquema.
import { api } from "../api.js";
import { definirNivel, emitir, estado, selecionarTarefa } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";

const ESCOPOS = [["arquitetura", "Arquitetura"], ["busca_e_memoria", "Busca e memoria"], ["ferramentas", "Ferramentas"],
  ["interface", "Interface"], ["seguranca", "Seguranca"], ["custo_e_modelos", "Custo e modelos"]];
const ESFORCOS = [["", "padrao"], ["low", "baixo"], ["medium", "medio"], ["high", "alto"], ["xhigh", "muito alto"], ["max", "maximo"]];
let ctx = {};

export async function recarregar() {
  const c = await api("GET", "/configuracao");
  estado.config = c;
  const exec = c.partes.find((p) => p.id === "execucao");
  document.getElementById("st-config").textContent = `config v${c.versao}`;
  document.getElementById("st-modelo").textContent = `modelo: ${exec?.modelo_efetivo ?? "—"}`;
  return c;
}

function secaoConfig(c, catalogo) {
  const nivel = el("select", { "aria-label": "Nivel de detalhe" }, el("option", { value: "simples", textContent: "Simples — so o essencial" }), el("option", { value: "avancado", textContent: "Avancado — mostra campos tecnicos" }));
  nivel.value = c.configuracao.nivel_detalhe;
  const custos = new Map(catalogo.modelos.map((m) => [m.id, m]));
  const lista = el("datalist", { id: "lista-modelos" }, ...catalogo.modelos.map((m) => el("option", { value: m.id, label: `${m.custo}x creditos — ${m.descricao}` })));
  const campos = new Map();
  const linhas = c.partes.map((p) => {
    const modelo = el("input", { value: p.modelo, maxLength: 80, list: "lista-modelos", placeholder: p.usa_modelo ? "vazio = padrao da conta" : "sem modelo", disabled: !p.usa_modelo,
      "aria-label": `Modelo de ${p.rotulo}`, pattern: "[A-Za-z0-9][A-Za-z0-9._:/\\-]{0,79}" });
    const esforco = el("select", { disabled: !p.usa_modelo, "aria-label": `Esforco de ${p.rotulo}` }, ...ESFORCOS.map(([v, r]) => el("option", { value: v, textContent: r, selected: v === p.esforco })));
    const custo = el("span", { className: "mudo", role: "status" });
    const mostrarCusto = () => { const m = custos.get(modelo.value.trim()); custo.textContent = m ? `${m.custo}x creditos` : ""; };
    modelo.addEventListener("input", mostrarCusto); mostrarCusto();
    campos.set(p.id, { modelo, esforco });
    return el("tr", {}, el("td", {}, el("strong", { textContent: p.rotulo }), el("div", { className: "mudo", textContent: p.descricao })),
      el("td", {}, modelo, custo), el("td", {}, esforco), el("td", { className: "so-avancado mono", textContent: p.usa_modelo ? p.modelo_efetivo : "deterministico" }));
  });
  const salvar = el("button", { type: "button", className: "primario", textContent: "Salvar configuracao", onclick: async () => {
    const partes = {};
    for (const [id, f] of campos) if (!f.modelo.disabled && (f.modelo.value.trim() || f.esforco.value)) partes[id] = { modelo: f.modelo.value.trim(), esforco: f.esforco.value };
    try {
      await api("PUT", "/configuracao", { expected_version: c.versao, configuracao: { nivel_detalhe: nivel.value, partes } });
      definirNivel(nivel.value); document.getElementById("nivel").value = nivel.value;
      toast("Configuracao salva", "ok"); await recarregar(); montar(ctx.raiz);
    } catch (e) { toast(e.status === 409 ? "A configuracao mudou em outra aba. Recarregue." : e.message, "erro"); }
  } });
  return el("section", { className: "card" }, el("h2", { textContent: "Modelo e esforco de IA por parte do sistema" }),
    el("p", { className: "aviso", textContent: catalogo.modelos.length
      ? "Cada parte pode usar um modelo e um esforco diferentes. Os modelos abaixo vem da sua conta, com o custo relativo em creditos (menor e mais barato). Vazio usa o padrao da conta."
      : `Cada parte pode usar um modelo e um esforco diferentes. ${catalogo.aviso || ""} Um nome invalido faz o Kiro recusar a sessao.` }),
    el("label", { className: "campo" }, el("span", { textContent: "Nivel de detalhe da interface" }), nivel), lista,
    el("table", {}, el("thead", {}, el("tr", {}, el("th", { textContent: "Parte" }), el("th", { textContent: "Modelo" }), el("th", { textContent: "Esforco" }), el("th", { className: "so-avancado", textContent: "Efetivo" }))), el("tbody", {}, ...linhas)),
    el("div", { className: "linha" }, salvar, tag(`versao ${c.versao}`, "so-avancado")));
}

function secaoRevisao() {
  const marcas = ESCOPOS.map(([v, r]) => el("label", {}, el("input", { type: "checkbox", value: v, checked: v === "arquitetura" }), ` ${r}`));
  const web = el("input", { type: "checkbox" });
  const exec = el("input", { type: "checkbox" });
  const saida = el("div", { role: "status", "aria-live": "polite" });
  const pedir = el("button", { type: "button", className: "primario", textContent: "Solicitar revisao", onclick: async () => {
    const escopo = marcas.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (!escopo.length) return toast("Escolha ao menos um eixo.", "erro");
    if (exec.checked && !confirm("Executar agora consome creditos do provedor de IA. Continuar?")) return;
    pedir.disabled = true;
    try {
      const r = await api("POST", "/revisoes", { escopo, pesquisar_web: web.checked, executar: exec.checked });
      limpar(saida);
      saida.append(el("p", { textContent: exec.checked ? "Revisao iniciada." : "Revisao criada e preparada (nao executada)." }),
        el("button", { type: "button", textContent: "Abrir no quadro", onclick: () => { selecionarTarefa(r.tarefa.id); emitir("ir", "tarefas"); } }),
        el("details", { className: "so-avancado" }, el("summary", { textContent: "fatos medidos enviados ao agente" }), el("pre", { className: "saida", textContent: JSON.stringify(r.snapshot, null, 1) })));
    } catch (e) { toast(e.message, "erro"); } finally { pedir.disabled = false; }
  } });
  return el("section", { className: "card" }, el("h2", { textContent: "Validar o esquema atual" }),
    el("p", { textContent: "Pede a um agente que reavalie a plataforma: ha melhorias que valem o custo agora (novos modelos, pesquisas, bibliotecas) ou o esquema esta num ponto agradavel? O orquestrador entrega fatos medidos (versoes, uso das ferramentas, modelos, volume) e exige fontes e prioridades." }),
    el("fieldset", {}, el("legend", { className: "mudo", textContent: "Eixos" }), ...marcas.map((m) => el("div", {}, m))),
    el("label", {}, web, " pedir pesquisa de novidades (passa pelas aprovacoes por acao)"), el("br"),
    el("label", {}, exec, " executar agora (consome creditos)"), el("div", { className: "linha" }, pedir), saida);
}

export function montarLateral(lat) {
  limpar(lat);
  lat.append(el("h2", { textContent: "Configuracao" }), el("p", { className: "mudo", textContent: "Modelo e esforco por parte, nivel de detalhe e revisao do esquema." }));
}

export async function montar(raiz) {
  ctx.raiz = raiz;
  limpar(raiz);
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Configuracao e revisao" })));
  try {
    const [c, catalogo] = await Promise.all([recarregar(), api("GET", "/configuracao/modelos").catch(() => ({ modelos: [], aviso: "Nao foi possivel consultar os modelos." }))]);
    raiz.append(el("div", { className: "grade", style: "grid-template-columns:repeat(auto-fit,minmax(380px,1fr))" }, secaoConfig(c, catalogo), secaoRevisao()));
  } catch (e) { raiz.append(el("p", { className: "aviso", textContent: e.message })); }
}
