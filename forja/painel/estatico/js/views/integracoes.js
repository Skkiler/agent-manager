// Integracoes: locais (prontas para usar) e de rede (nascem DESLIGADAS; configuradas aqui, com o segredo so no ambiente).
// Esta tela NUNCA pede nem mostra o valor de um token: guarda apenas o NOME da variavel de ambiente (FORJA_INT_*).
import { api } from "../api.js";
import { dataCurta, dialogo, el, limpar, tag, toast } from "../ui.js";

let raizAtual = null;

function estadoRede(c) {
  const r = c.rede_estado;
  if (!r) return null;
  const pronta = r.pronta;
  return tag(pronta ? "pronta" : r.motivo, pronta ? "ok" : r.configurada ? "aviso" : "");
}

function campoVariavel(campo, valor, presentes) {
  const entrada = el("input", { value: valor, maxLength: 60, placeholder: "FORJA_INT_...", pattern: "FORJA_INT_[A-Z0-9_]{1,50}", autocomplete: "off", spellcheck: false, "aria-label": campo.rotulo });
  const aviso = el("span", { className: "mudo", role: "status" });
  const atualizar = () => {
    const v = entrada.value.trim();
    aviso.textContent = !v ? "" : v in presentes ? (presentes[v] ? "✓ presente no ambiente" : "✗ ausente no ambiente") : "(salve para verificar)";
    aviso.style.color = v in presentes ? (presentes[v] ? "var(--ok)" : "var(--aviso)") : "";
  };
  entrada.addEventListener("input", atualizar); atualizar();
  const dica = el("code", { className: "mono mudo", textContent: valor ? `${valor}=<valor secreto>` : "NOME_DA_VARIAVEL=<valor secreto>  (no arquivo .env)" });
  return { no: el("div", {}, entrada, el("div", {}, aviso), dica), ler: () => entrada.value.trim() };
}

function formulario(c, aoSalvar) {
  const r = c.rede_estado;
  const cfg = r.versao === 0 ? Object.fromEntries(r.campos.map((f) => [f.id, f.padrao])) : r.configuracao;
  const ativo = el("input", { type: "checkbox", checked: Boolean(r.configuracao.ativo) });
  const leitores = {};
  const linhas = r.campos.map((f) => {
    const atual = cfg[f.id] ?? f.padrao ?? "";
    let no;
    if (f.tipo === "variavel") { const v = campoVariavel(f, atual, r.variaveis); no = v.no; leitores[f.id] = v.ler; }
    else if (f.tipo === "lista") { const t = el("textarea", { rows: 3, value: (atual || []).join("\n"), "aria-label": f.rotulo }); no = t; leitores[f.id] = () => t.value.split("\n").map((s) => s.trim()).filter(Boolean); }
    else if (f.tipo === "bool") { const b = el("input", { type: "checkbox", checked: Boolean(atual), "aria-label": f.rotulo }); no = b; leitores[f.id] = () => b.checked; }
    else if (f.tipo === "numero") { const n = el("input", { type: "number", value: atual || f.padrao, min: 1, max: 120, "aria-label": f.rotulo }); no = n; leitores[f.id] = () => Number(n.value); }
    else if (f.tipo === "selecao") { const s = el("select", { "aria-label": f.rotulo }, ...f.opcoes.map(([v, rot]) => el("option", { value: v, textContent: rot, selected: v === (atual || f.padrao) }))); no = s; leitores[f.id] = () => s.value; }
    else { const i = el("input", { value: atual, maxLength: 300, "aria-label": f.rotulo, type: f.tipo === "url" ? "url" : "text" }); no = i; leitores[f.id] = () => i.value.trim(); }
    return el("div", { className: "campo" }, el("span", { textContent: f.rotulo + (f.obrigatorio ? " *" : "") }), no, f.ajuda ? el("small", { className: "mudo", textContent: f.ajuda }) : null);
  });
  const form = el("form", {},
    el("p", { className: "aviso", textContent: "Segredos nunca sao digitados aqui. Coloque o token no arquivo .env (ou na variavel de ambiente) com o nome indicado e informe so o NOME. A integracao so alcanca o servidor configurado. Escrita (quando houver e estiver ligada) so acontece depois da sua aprovacao, acao por acao." }),
    el("label", {}, ativo, " Ativar esta integracao"), ...linhas,
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Salvar" }), el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo(`Configurar ${c.nome}`, form);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const corpo = { ativo: ativo.checked };
    for (const [id, ler] of Object.entries(leitores)) corpo[id] = ler();
    try {
      await api("PUT", `/integracoes/${c.id}/configuracao`, { expected_version: r.versao, configuracao: corpo });
      d.fechar(); toast("Integracao salva", "ok"); await aoSalvar();
    } catch (e) { toast(e.status === 409 ? "A configuracao mudou em outra aba. Reabra." : e.message, "erro"); }
  });
}

async function testar(c, botao) {
  botao.disabled = true;
  try {
    const r = await api("POST", `/integracoes/${c.id}/testar`);
    toast(r.ok ? `${c.nome}: conexao e credencial validas (${r.ms} ms)` : `${c.nome}: ${r.mensagem}`, r.ok ? "ok" : "erro");
  } catch (e) { toast(e.message, "erro"); } finally { botao.disabled = false; }
}

function cartao(c, recarregar) {
  const rede = c.modo === "rede" && c.configuravel;
  const botoes = [];
  if (rede) {
    botoes.push(el("button", { type: "button", className: "primario", textContent: "Configurar", onclick: () => formulario(c, recarregar) }));
    const t = el("button", { type: "button", textContent: "Testar conexão", disabled: !c.rede_estado.pronta, title: c.rede_estado.pronta ? "" : "Ative e configure primeiro" });
    t.addEventListener("click", () => testar(c, t));
    botoes.push(t);
  }
  return el("article", { className: "card" },
    el("div", { className: "linha" }, el("h3", { textContent: c.nome }), el("span", { className: "espaco" }),
      rede ? estadoRede(c) : tag(c.estado === "implementado" ? (c.disponivel ? "disponivel" : "ferramenta ausente") : "requer aprovacao", c.disponivel ? "ok" : "aviso")),
    el("div", { className: "linha" }, tag(c.categoria), tag(c.custo), tag(c.rede ? "usa rede" : "local"), tag(c.credencial ? "usa credencial" : "sem credencial")),
    el("p", { className: "recolhivel", textContent: c.como_usar }),
    c.ferramentas.length ? el("p", { className: "mudo so-avancado mono", textContent: c.ferramentas.join(", ") }) : null,
    c.riscos.length ? el("ul", {}, ...c.riscos.map((r) => el("li", { className: "mudo", textContent: r }))) : null,
    c.aprovacao ? el("p", { className: "aviso", textContent: `Para ativar, voce precisa aprovar: ${c.aprovacao}` }) : null,
    botoes.length ? el("div", { className: "linha" }, ...botoes) : null);
}

const RISCO = { baixo: "ok", medio: "aviso", alto: "erro" };

function cartaoAcao(a, recarregar) {
  const adendo = el("textarea", { rows: 2, maxLength: 1000, placeholder: "Adendo opcional (fica registrado com a decisao)", "aria-label": `Adendo para ${a.id}` });
  const decidir = async (aprovar, botao) => {
    if (aprovar && a.risco === "alto" && !confirm(`Risco alto: ${a.descricao}\n\nConfirmar e executar agora?`)) return;
    botao.disabled = true;
    try {
      const r = await api("POST", `/acoes-externas/${a.id}/decidir`, { aprovar, expected_version: a.versao, adendo: adendo.value.trim() });
      toast(r.estado === "executada" ? `Executada: ${r.resultado}` : r.estado === "negada" ? "Acao negada" : `Nao executada: ${r.resultado}`,
        r.estado === "falhou" ? "erro" : "ok");
      await recarregar();
    } catch (e) { toast(e.status === 409 ? "A acao mudou (decidida em outra aba ou expirada). Recarregue." : e.message, "erro"); botao.disabled = false; }
  };
  const aprovar = el("button", { type: "button", className: "primario", textContent: "Aprovar e executar" });
  const negar = el("button", { type: "button", textContent: "Negar" });
  aprovar.addEventListener("click", () => decidir(true, aprovar));
  negar.addEventListener("click", () => decidir(false, negar));
  return el("article", { className: "card acao-externa", "data-acao": a.id },
    el("div", { className: "linha" }, el("h3", { textContent: a.descricao }), el("span", { className: "espaco" }), tag(`risco ${a.risco}`, RISCO[a.risco] || "")),
    el("div", { className: "linha mudo" }, tag(a.integracao), el("span", { textContent: `pedido por ${a.solicitado_por} em ${dataCurta(a.criado_em)}` }),
      el("span", { className: "so-avancado mono", textContent: a.id })),
    el("details", { className: "so-avancado" }, el("summary", { textContent: "parametros que serao enviados" }), el("pre", { className: "saida", textContent: JSON.stringify(a.parametros, null, 1) })),
    adendo, el("div", { className: "linha" }, aprovar, negar));
}

function secaoAcoes(pendentes, historico, recarregar) {
  const itens = pendentes.length ? pendentes.map((a) => cartaoAcao(a, recarregar))
    : [el("p", { className: "mudo", textContent: "Nenhuma acao externa aguardando voce. Quando um agente propuser comentar, mudar status ou criar um cartao, a pergunta aparece aqui e no quadro." })];
  return [el("h2", { id: "acoes-externas", textContent: `Acoes aguardando voce (${pendentes.length})` }), el("div", { className: "grade" }, ...itens),
    historico.length ? el("details", { className: "so-avancado" }, el("summary", { textContent: `Historico (${historico.length})` }),
      el("ul", {}, ...historico.map((a) => el("li", {}, tag(a.estado, a.estado === "executada" ? "ok" : a.estado === "falhou" ? "erro" : ""), ` ${a.descricao} `,
        el("span", { className: "mudo", textContent: a.resultado || a.adendo || "" }))))) : null].filter(Boolean);
}

export function montarLateral(lat) {
  limpar(lat);
  lat.append(el("h2", { textContent: "Integracoes" }),
    el("p", { className: "aviso", textContent: "Conectores de rede nascem desligados. Voce liga, escolhe o que pode ser lido e guarda o token no .env. Leitura por padrao; escrita so com 'permitir escrita' ligado e sua aprovacao, acao por acao." }),
    el("p", { className: "mudo", textContent: "Conectores locais nao usam rede nem credencial." }));
}

export async function montar(raiz) {
  raizAtual = raiz;
  limpar(raiz);
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Integracoes e servicos" })));
  try {
    const [lista, acoes] = await Promise.all([api("GET", "/integracoes"), api("GET", "/acoes-externas").catch(() => [])]);
    const recarregar = () => montar(raizAtual);
    const grupo = (titulo, itens) => [el("h2", { textContent: titulo }), el("div", { className: "grade" }, ...itens.map((c) => cartao(c, recarregar)))];
    raiz.append(...secaoAcoes(acoes.filter((a) => a.estado === "pendente"), acoes.filter((a) => a.estado !== "pendente").slice(0, 20), recarregar),
      ...grupo("De rede (desligadas ate voce configurar)", lista.filter((c) => c.modo === "rede" && c.estado === "implementado")),
      ...grupo("Locais (gratuitas, sem credencial)", lista.filter((c) => c.modo === "local")),
      ...grupo("Planejadas (dependem da sua aprovacao)", lista.filter((c) => c.estado !== "implementado")));
  } catch (e) { raiz.append(el("p", { className: "aviso", textContent: e.message })); }
}
