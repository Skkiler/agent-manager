// Barra lateral da bancada: Explorador, Busca, Controle de codigo (Git completo) e Docker (completo).
// O USUARIO ve e edita tudo, inclusive segredos (marcados com cadeado); nada disto vai para os agentes. Acao arriscada pergunta.
import { api, consulta } from "./api.js";
import { abrirArquivo, abrirDiff, abrirTexto } from "./bancada.js";
import { comConfirmacao } from "./confirmar.js";
import { emitir, ouvir } from "./estado.js";
import { icone } from "./icones.js";
import { dialogo, el, limpar, tag, toast } from "./ui.js";
import { dialogoProjeto } from "./views/projetos.js";

const abertos = new Set(JSON.parse(localStorage.getItem("forja_arvore") || "[]"));
const lembrarArvore = () => localStorage.setItem("forja_arvore", JSON.stringify([...abertos].slice(-200)));
let projetosCache = null;

export async function projetos(forcar = false) {
  if (!projetosCache || forcar) projetosCache = api("GET", "/projetos").catch(() => []);
  return projetosCache;
}
ouvir("projetos-mudaram", () => { projetosCache = null; });

const botaoAcao = (nome, rotulo, onclick) => el("button", { type: "button", className: "icone pequeno", "aria-label": rotulo, title: rotulo, onclick }, icone(nome, 16));

/** Seletor de projeto (+ pasta) lembrado entre as telas. */
export function seletorProjeto(lista, aoMudar, { comPasta = false, soTrabalho = false } = {}) {
  const sel = el("select", { "aria-label": "Projeto" }, ...lista.map((p) => el("option", { value: p.id, textContent: p.nome })));
  const pasta = el("select", { "aria-label": "Pasta do projeto", hidden: !comPasta });
  const salvo = localStorage.getItem("forja_projeto_area");
  if (salvo && lista.some((p) => p.id === salvo)) sel.value = salvo;
  const preencher = () => {
    const p = lista.find((x) => x.id === sel.value);
    limpar(pasta);
    (p?.pastas || []).forEach((x, i) => { if (!soTrabalho || x.papel === "trabalho") pasta.append(el("option", { value: String(i), textContent: `${x.caminho.split(/[\\/]/).pop()} (${x.papel})` })); });
  };
  preencher();
  sel.addEventListener("change", () => { localStorage.setItem("forja_projeto_area", sel.value); preencher(); aoMudar(); });
  pasta.addEventListener("change", aoMudar);
  return { no: el("div", { className: "linha seletor-projeto" }, sel, pasta), projeto: () => lista.find((x) => x.id === sel.value), raiz: () => Number(pasta.value || 0) };
}

const semProjeto = (corpo) => corpo.append(el("div", { className: "vazio-acao" }, icone("pasta", 28),
  el("p", { textContent: "Nenhum projeto com pasta ainda." }), el("p", { className: "mudo", textContent: "Crie um projeto e escolha a pasta de trabalho para abrir arquivos, usar o Git e o terminal." }),
  el("button", { type: "button", className: "primario", textContent: "+ Projeto", onclick: () => dialogoProjeto(null, () => emitir("projetos-mudaram")) })));

// ------------------------------------------------------------------ Explorador
function navegarArvore(ev) {
  const arvore = ev.currentTarget;
  const bs = [...arvore.querySelectorAll("button.no-arvore")];
  const i = bs.indexOf(document.activeElement);
  if (i < 0) return;
  const b = bs[i];
  let j = null;
  if (ev.key === "ArrowDown") j = Math.min(bs.length - 1, i + 1);
  else if (ev.key === "ArrowUp") j = Math.max(0, i - 1);
  else if (ev.key === "Home") j = 0;
  else if (ev.key === "End") j = bs.length - 1;
  else if (ev.key === "ArrowRight" && b.getAttribute("aria-expanded") === "false") { ev.preventDefault(); b.click(); return; }
  else if (ev.key === "ArrowLeft" && b.getAttribute("aria-expanded") === "true") { ev.preventDefault(); b.click(); return; }
  if (j === null) return;
  ev.preventDefault();
  bs.forEach((x, k) => { x.tabIndex = k === j ? 0 : -1; });
  bs[j].focus();
}

function noArquivo(p, raiz, it, nivel) {
  const f = el("button", { type: "button", className: `no-arvore arquivo${it.segredo ? " segredo" : ""}`, tabIndex: -1,
    title: it.segredo ? `${it.rel} (segredo: só você vê; nunca vai para os agentes)` : it.rel,
    onclick: () => abrirArquivo({ projeto: p.id, raiz, rel: it.rel, nome: it.nome }) },
  el("span", { className: "seta vazia", "aria-hidden": "true" }), icone(it.segredo ? "cadeado" : "arquivo", 15), el("span", { className: "trunc", textContent: it.nome }),
  it.segredo ? el("span", { className: "sr-only", textContent: " (arquivo de segredo)" }) : null);
  f.style.setProperty("--nivel", String(nivel));
  return f;
}

function noPasta(p, raiz, rel, nome, nivel, papel) {
  const chave = `${p.id}:${raiz}:${rel}`;
  const filhos = el("ul");
  const b = el("button", { type: "button", className: "no-arvore pasta", tabIndex: -1, "aria-expanded": "false", title: rel || nome },
    el("span", { className: "seta", "aria-hidden": "true" }), icone("pasta", 15), el("span", { className: "trunc", textContent: nome }),
    papel === "consulta" && !rel ? tag("consulta") : null);
  b.style.setProperty("--nivel", String(nivel));
  const abrir = async (ligado) => {
    b.setAttribute("aria-expanded", String(ligado));
    if (ligado) abertos.add(chave); else abertos.delete(chave);
    lembrarArvore();
    limpar(filhos);
    if (!ligado) return;
    try {
      const r = await api("GET", `/area/arvore?${consulta({ projeto: p.id, raiz, rel })}`);
      filhos.append(...r.itens.map((it) => el("li", {}, it.pasta ? noPasta(p, raiz, it.rel, it.nome, nivel + 1, papel) : noArquivo(p, raiz, it, nivel + 1))));
      if (!r.itens.length) filhos.append(el("li", { className: "mudo vazio-arvore", textContent: "(vazia)" }));
      if (r.truncado) filhos.append(el("li", { className: "mudo", textContent: "… lista cortada (muitos itens)" }));
    } catch (e) { filhos.append(el("li", { className: "aviso", textContent: e.message })); }
  };
  b.addEventListener("click", () => abrir(b.getAttribute("aria-expanded") !== "true"));
  const frag = document.createDocumentFragment();
  frag.append(b, filhos);
  if (abertos.has(chave)) abrir(true);
  return frag;
}

export async function montarExplorador(corpo, acoes) {
  const desenhar = async (forcar) => {
    const lista = (await projetos(forcar)).filter((p) => (p.pastas || []).length);
    limpar(corpo);
    if (!lista.length) return semProjeto(corpo);
    const arvore = el("ul", { className: "arvore", "aria-label": "Arquivos dos projetos", onkeydown: navegarArvore });
    for (const p of lista) {
      arvore.append(el("li", { className: "raiz-projeto" }, el("div", { className: "nome-projeto trunc", textContent: p.nome, title: p.descricao || p.nome }),
        el("ul", {}, ...p.pastas.map((x, i) => el("li", {}, noPasta(p, i, "", x.caminho.split(/[\\/]/).pop() || x.caminho, 0, x.papel))))));
    }
    corpo.append(arvore, el("p", { className: "mudo dica-arvore" }, icone("cadeado", 12),
      " Segredos (.env, chaves) aparecem só para você e nunca vão para os agentes. Pastas de consulta são somente leitura."));
    requestAnimationFrame(() => { const primeiro = arvore.querySelector("button.no-arvore"); if (primeiro) primeiro.tabIndex = 0; });
  };
  acoes.append(botaoAcao("mais", "Novo projeto", () => dialogoProjeto(null, () => { emitir("projetos-mudaram"); desenhar(true); })),
    botaoAcao("atualizar", "Atualizar", () => desenhar(true)),
    el("button", { type: "button", className: "icone pequeno", "aria-label": "Recolher tudo", title: "Recolher tudo", textContent: "⊟", onclick: () => { abertos.clear(); lembrarArvore(); desenhar(); } }));
  await desenhar();
}

// ------------------------------------------------------------------ Busca nos arquivos
export async function montarBusca(corpo) {
  const lista = (await projetos()).filter((p) => (p.pastas || []).length);
  if (!lista.length) return semProjeto(corpo);
  const sel = seletorProjeto(lista, () => {}, {});
  const termo = el("input", { type: "search", maxLength: 200, placeholder: "Buscar (Enter)", "aria-label": "Texto a buscar nos arquivos", spellcheck: false });
  const regex = el("input", { type: "checkbox" });
  const segredos = el("input", { type: "checkbox" });
  const incluir = el("input", { type: "text", maxLength: 60, placeholder: "ex.: *.py", "aria-label": "Arquivos a incluir (padrão)" });
  const resultado = el("div", { className: "resultado-busca", "aria-live": "polite" });
  const buscar = async () => {
    const q = termo.value.trim();
    limpar(resultado);
    if (!q) return;
    const p = sel.projeto();
    resultado.append(el("p", { className: "mudo", textContent: "Buscando…" }));
    const grupos = [];
    let total = 0, pulados = 0;
    for (let raiz = 0; raiz < p.pastas.length; raiz += 1) {
      try {
        const r = await api("GET", `/area/buscar?${consulta({ projeto: p.id, raiz, padrao: q, regex: regex.checked ? "true" : "", incluir: incluir.value.trim(), segredos: segredos.checked ? "true" : "" })}`);
        pulados += r.segredos_pulados || 0;
        const porArquivo = new Map();
        for (const o of r.ocorrencias) { if (!porArquivo.has(o.arquivo)) porArquivo.set(o.arquivo, []); porArquivo.get(o.arquivo).push(o); }
        for (const [arq, os] of porArquivo) { total += os.length; grupos.push({ raiz, arq, os }); }
      } catch (e) { grupos.push({ erro: e.message }); }
    }
    limpar(resultado);
    resultado.append(el("p", { className: "mudo", role: "status", textContent: (total ? `${total} resultado(s) em ${grupos.filter((g) => !g.erro).length} arquivo(s)` : "Nenhum resultado.")
      + (pulados && !segredos.checked ? ` · ${pulados} arquivo(s) de segredo fora da busca` : "") }));
    for (const g of grupos) {
      if (g.erro) { resultado.append(el("p", { className: "aviso", textContent: g.erro })); continue; }
      resultado.append(el("details", { open: true }, el("summary", { className: "trunc", title: g.arq }, icone("arquivo", 14), ` ${g.arq.split("/").pop()} `, el("span", { className: "mudo", textContent: g.arq })),
        el("ul", { className: "lista-ocorrencias" }, ...g.os.map((o) => el("li", {}, el("button", { type: "button", className: "bloco",
          onclick: () => abrirArquivo({ projeto: p.id, raiz: g.raiz, rel: o.arquivo, linha: o.linha }) },
        el("span", { className: "mudo num-linha", textContent: String(o.linha) }), el("span", { className: "trunc", textContent: o.texto })))))));
    }
  };
  termo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); buscar(); } });
  corpo.append(sel.no, termo, el("div", { className: "linha" }, el("label", {}, regex, " regex"), el("label", { title: "Inclui .env e chaves (só você vê)" }, segredos, " incluir segredos")),
    incluir, el("button", { type: "button", className: "primario", textContent: "Buscar", onclick: buscar }), resultado);
  requestAnimationFrame(() => termo.focus());
}

// ------------------------------------------------------------------ Git
const ROTULO_GIT = { M: "modificado", A: "adicionado", D: "apagado", R: "renomeado", C: "copiado", U: "conflito", "?": "novo" };
const DICAS_GIT = [
  [/rejected|fetch first|non-fast-forward/i, "O remoto tem commits que você não tem. Use a receita \"Push rejeitado\" (pull --rebase e push de novo).", "git.push_rejeitado"],
  [/please tell me who you are|user\.email/i, "Configure seu nome e e-mail dos commits.", "git.identidade"],
  [/no upstream|has no upstream branch|set-upstream/i, "O branch ainda não está ligado ao remoto: use Enviar (push -u).", ""],
  [/not a git repository/i, "A pasta não é um repositório Git: use \"Iniciar repositório\".", "git.vincular_remoto"],
  [/terminal prompts disabled|could not read Username|Authentication failed/i, "O Git precisa de login: configure o Git Credential Manager ou SSH pelo seu terminal.", ""],
  [/CONFLICT|merge conflict|fix conflicts/i, "Há conflitos: edite os arquivos marcados, prepare (+) e conclua (commit ou rebase --continue).", ""],
  [/would be overwritten by (checkout|merge)/i, "Há alterações locais no caminho: faça commit ou guarde (stash) antes.", "git.guardar_temporariamente"],
];

function mostrarResultado(titulo, r) {
  const texto = [r.saida, r.erro].filter((x) => x && x.trim()).join("\n").trim();
  if (r.codigo === 0) { toast(texto.split("\n").slice(-1)[0]?.slice(0, 160) || `${titulo}: ok`, "ok"); return; }
  const dica = DICAS_GIT.find(([re]) => re.test(texto));
  const corpo = el("div", { className: "resultado-comando" }, el("pre", { className: "saida", textContent: texto || "(sem saída)" }),
    dica ? el("p", { className: "dica" }, icone("lampada", 14), ` ${dica[1]}`) : null,
    dica?.[2] ? el("button", { type: "button", className: "primario", textContent: "Abrir a receita", onclick: () => { d.fechar(); emitir("receita", dica[2]); } }) : null);
  const d = dialogo(`${titulo}: falhou (código ${r.codigo})`, corpo);
}

export async function montarGit(corpo, acoes) {
  const lista = (await projetos()).filter((p) => (p.pastas || []).length);
  if (!lista.length) return semProjeto(corpo);
  const conteudo = el("div", { className: "scm" });
  const sel = seletorProjeto(lista, () => desenhar(), { comPasta: true });
  acoes.append(botaoAcao("atualizar", "Atualizar", () => desenhar()),
    el("button", { type: "button", className: "icone pequeno", "aria-label": "Receitas de Git", title: "Receitas de Git (passo a passo)", onclick: () => emitir("receitas", "git") }, icone("lampada", 16)));
  corpo.append(sel.no, conteudo);
  const git = async (args, titulo = `git ${args[0]}`, { silencioso = false } = {}) => {
    try {
      const r = await comConfirmacao("POST", "/area/git/executar", { projeto: sel.projeto().id, raiz: sel.raiz(), args }, { titulo: `Confirmar: git ${args.join(" ").slice(0, 80)}` });
      if (!r) return null;
      if (!silencioso || r.codigo !== 0) mostrarResultado(titulo, r);
      emitir("git-mudou");
      await desenhar();
      return r;
    } catch (e) { toast(e.message, "erro"); return null; }
  };
  const pedirTexto = (titulo, rotulo, padrao = "") => new Promise((resolver) => {
    const campo = el("input", { type: "text", value: padrao, maxLength: 300, "aria-label": rotulo });
    const ok = () => { d.fechar(); resolver(campo.value.trim()); };
    campo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); ok(); } });
    const d = dialogo(titulo, el("div", {}, el("label", { className: "campo" }, el("span", { textContent: rotulo }), campo),
      el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => { d.fechar(); resolver(""); } }),
        el("button", { type: "button", className: "primario", textContent: "OK", onclick: ok }))));
    requestAnimationFrame(() => campo.select());
  });

  let geracao = 0;
  async function desenhar() {
    const minha = ++geracao; // atualizacoes sobrepostas (botao + fim de um comando): so a ultima desenha
    const p = sel.projeto(), raiz = sel.raiz();
    const trabalho = p.pastas[raiz]?.papel === "trabalho";
    let st;
    try { st = await api("GET", `/area/git?${consulta({ projeto: p.id, raiz })}`); } catch (e) { if (minha === geracao) { limpar(conteudo); conteudo.append(el("p", { className: "aviso", textContent: e.message })); } return; }
    if (minha !== geracao) return;
    limpar(conteudo);
    const d = st.dados;
    if (d.repositorio === false) {
      conteudo.append(el("div", { className: "vazio-acao" }, icone("git", 28), el("p", { textContent: "Esta pasta ainda não é um repositório Git." }),
        trabalho ? el("button", { type: "button", className: "primario", textContent: "Iniciar repositório (git init)", onclick: () => git(["init", "-b", "main"], "git init") }) : null,
        el("button", { type: "button", className: "link", textContent: "Receita: vincular a um repositório remoto e enviar", onclick: () => emitir("receita", "git.vincular_remoto") })));
      return;
    }
    // cabecalho: branch, sincronia
    const ramos = el("select", { "aria-label": "Branch atual (trocar)" }, ...d.branches.map((b) => el("option", { value: b, textContent: b, selected: b === d.branch })),
      el("option", { value: "__novo", textContent: "+ Novo branch…" }));
    if (!d.branches.includes(d.branch)) ramos.prepend(el("option", { value: d.branch, textContent: d.branch, selected: true }));
    ramos.addEventListener("change", async () => {
      if (ramos.value === "__novo") { const n = await pedirTexto("Novo branch", "Nome do branch", "feature/"); if (n) await git(["switch", "-c", n], "Criar branch"); else desenhar(); }
      else await git(["switch", ramos.value], "Trocar de branch");
    });
    const sinc = d.upstream ? `${d.atras ? `↓${d.atras} ` : ""}${d.a_frente ? `↑${d.a_frente}` : ""}`.trim() || "em dia" : "sem remoto ligado";
    conteudo.append(el("div", { className: "scm-cabeca" }, icone("git", 16), ramos, el("span", { className: "mudo", title: d.upstream || "", textContent: sinc })),
      el("div", { className: "linha scm-sinc" },
        el("button", { type: "button", className: "pequeno", title: "Baixar novidades sem mexer nos arquivos (fetch)", onclick: () => git(["fetch", "--all", "--prune"], "Buscar") }, "⟳ Buscar"),
        el("button", { type: "button", className: "pequeno", disabled: !trabalho || !d.upstream, title: "Trazer e integrar (pull)", onclick: () => git(["pull", "--ff-only"], "Puxar") }, `↓ Puxar${d.atras ? ` (${d.atras})` : ""}`),
        el("button", { type: "button", className: "pequeno", disabled: !trabalho || !Object.keys(d.remotos).length, title: "Enviar commits (push)",
          onclick: () => git(d.upstream ? ["push"] : ["push", "-u", Object.keys(d.remotos)[0], d.branch], "Enviar") }, `↑ Enviar${d.a_frente ? ` (${d.a_frente})` : ""}`)));
    for (const a of st.avisos || []) conteudo.append(el("p", { className: "aviso", textContent: a }));
    const itens = d.alterados || [];
    const preparados = itens.filter((i) => i.x && i.x !== " " && i.x !== "?");
    const alterados = itens.filter((i) => !i.x || i.y !== " " || i.x === "?");
    // commit
    if (trabalho) {
      const msg = el("textarea", { rows: 2, maxLength: 2000, placeholder: `Mensagem (Ctrl+Enter faz commit em "${d.branch}")`, "aria-label": "Mensagem do commit", spellcheck: true, lang: "pt-BR" });
      const alterar = el("input", { type: "checkbox" });
      const fazer = async (enviar) => {
        if (!msg.value.trim() && !alterar.checked) { msg.focus(); return toast("Escreva a mensagem do commit."); }
        const args = alterar.checked ? ["commit", "--amend", ...(msg.value.trim() ? ["-m", msg.value.trim()] : ["--no-edit"])] : ["commit", "-m", msg.value.trim()];
        if (!preparados.length && !alterar.checked) args.splice(1, 0, "-a");
        const r = await git(args, "Commit", { silencioso: true });
        if (r?.codigo === 0) { toast("Commit feito.", "ok"); if (enviar) await git(d.upstream ? ["push"] : ["push", "-u", Object.keys(d.remotos)[0] || "origin", d.branch], "Enviar"); }
      };
      msg.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); fazer(false); } });
      conteudo.append(el("div", { className: "scm-commit" }, msg,
        el("div", { className: "linha" },
          el("button", { type: "button", className: "primario", disabled: !itens.length && !alterar.checked, title: preparados.length ? "Commit do que está preparado" : "Commit de todas as alterações (-a)",
            onclick: () => fazer(false) }, `✓ Commit${preparados.length ? "" : " tudo"}`),
          el("button", { type: "button", className: "pequeno", disabled: !itens.length || !Object.keys(d.remotos).length, title: "Commit e enviar ao remoto", onclick: () => fazer(true) }, "Commit e enviar"),
          el("label", { className: "mudo", title: "Substitui o último commit" }, alterar, " alterar último"))));
    } else conteudo.append(el("p", { className: "aviso", textContent: "Pasta de consulta: só leitura (status, histórico e diferenças)." }));
    const linha = (i, preparado) => {
      const nome = i.arquivo.split(" -> ").pop().replace(/^"|"$/g, "");
      const cod = (preparado ? i.x : i.y === " " ? i.x : i.y) || i.estado[0];
      return el("li", { className: `linha-git${i.segredo ? " segredo" : ""}` },
        el("button", { type: "button", className: "bloco", title: `${nome}${i.segredo ? " (segredo)" : ""}: ver diferenças`,
          onclick: () => abrirDiff({ projeto: p.id, raiz, rel: nome, versao: preparado ? "HEAD" : (i.x !== " " && i.x !== "?" ? "index" : "HEAD"), versaoDireita: preparado ? "index" : "" }) },
        i.segredo ? icone("cadeado", 13) : null, el("span", { className: "trunc", textContent: nome.split("/").pop() }), el("span", { className: "mudo trunc", textContent: nome.includes("/") ? nome.slice(0, nome.lastIndexOf("/")) : "" })),
        trabalho ? el("span", { className: "acoes-git" },
          el("button", { type: "button", className: "icone pequeno", "aria-label": `Abrir ${nome}`, title: "Abrir arquivo", onclick: () => abrirArquivo({ projeto: p.id, raiz, rel: nome }) }, icone("arquivo", 13)),
          !preparado && cod !== "?" ? el("button", { type: "button", className: "icone pequeno", "aria-label": `Descartar alterações de ${nome}`, title: "Descartar alterações (pede confirmação)",
            onclick: () => git(["restore", "--", nome], "Descartar") }, "↺") : null,
          el("button", { type: "button", className: "icone pequeno", "aria-label": `${preparado ? "Tirar da preparação" : "Preparar"} ${nome}`,
            title: preparado ? "Tirar da preparação (unstage)" : "Preparar para commit (stage)", textContent: preparado ? "−" : "+",
            onclick: () => git(preparado ? ["restore", "--staged", "--", nome] : ["add", "--", nome], preparado ? "Tirar da preparação" : "Preparar", { silencioso: true }) })) : null,
        el("span", { className: `estado-git git-${cod === "?" ? "novo" : cod}`, title: ROTULO_GIT[cod] || cod, textContent: cod === "?" ? "U" : cod }));
    };
    const secao = (titulo, lista, preparado, acaoTudo) => el("section", { className: "scm-secao" },
      el("h3", {}, el("span", { textContent: `${titulo} (${lista.length})` }), trabalho && lista.length ? acaoTudo : null),
      lista.length ? el("ul", { className: "lista-git" }, ...lista.map((i) => linha(i, preparado))) : el("p", { className: "mudo", textContent: preparado ? "Nada preparado." : "Nada alterado." }));
    if (preparados.length) conteudo.append(secao("Preparadas", preparados, true,
      el("button", { type: "button", className: "icone pequeno", title: "Tirar tudo da preparação", "aria-label": "Tirar tudo da preparação", textContent: "−", onclick: () => git(["reset", "-q"], "Tirar da preparação", { silencioso: true }) })));
    conteudo.append(secao("Alterações", alterados, false,
      el("button", { type: "button", className: "icone pequeno", title: "Preparar tudo", "aria-label": "Preparar tudo", textContent: "+", onclick: () => git(["add", "-A"], "Preparar tudo", { silencioso: true }) })));
    // stash, remotos, historico
    const stash = el("details", { className: "scm-mais" }, el("summary", { textContent: `Guardados (stash) (${d.stash.length})` }),
      trabalho ? el("button", { type: "button", className: "pequeno", disabled: !itens.length, onclick: async () => { const m = await pedirTexto("Guardar alterações", "Descrição", "trabalho em andamento"); if (m) git(["stash", "push", "-u", "-m", m], "Guardar"); } }, "Guardar alterações agora") : null,
      el("ul", { className: "lista-log" }, ...d.stash.map((s) => { const [ref, desc] = s.split("\t"); return el("li", { className: "linha" }, el("code", { textContent: ref }), el("span", { className: "trunc", textContent: desc || "" }),
        trabalho ? el("button", { type: "button", className: "pequeno", textContent: "Devolver", onclick: () => git(["stash", "pop", ref], "Devolver") }) : null,
        trabalho ? el("button", { type: "button", className: "pequeno perigo", textContent: "Apagar", onclick: () => git(["stash", "drop", ref], "Apagar guardado") }) : null); })));
    const remotos = el("details", { className: "scm-mais" }, el("summary", { textContent: `Remotos (${Object.keys(d.remotos).length})` }),
      el("ul", { className: "lista-log" }, ...Object.entries(d.remotos).map(([n, u]) => el("li", { className: "linha" }, el("strong", { textContent: n }), el("span", { className: "trunc mudo", textContent: u }),
        trabalho ? el("button", { type: "button", className: "pequeno perigo", textContent: "Remover", onclick: () => git(["remote", "remove", n], "Remover remoto") }) : null))),
      trabalho ? el("button", { type: "button", className: "pequeno", onclick: async () => { const u = await pedirTexto("Adicionar remoto", "URL do repositório (https:// ou git@)"); if (u) git(["remote", "add", Object.keys(d.remotos).length ? "upstream" : "origin", u], "Adicionar remoto"); } }, "+ Adicionar remoto") : null);
    const historico = el("details", { className: "scm-mais" }, el("summary", { textContent: "Histórico" }));
    historico.addEventListener("toggle", async () => {
      if (!historico.open || historico.dataset.carregado) return;
      historico.dataset.carregado = "1";
      try {
        const log = await api("GET", `/area/git?${consulta({ projeto: p.id, raiz, operacao: "log", limite: 25 })}`);
        historico.append(el("ul", { className: "lista-log" }, ...(log.dados.commits || []).map((c) => el("li", { title: `${c.commit} · ${c.autor || ""} · ${c.data || ""}` },
          el("button", { type: "button", className: "bloco", onclick: async () => { const r = await api("POST", "/area/git/executar", { projeto: p.id, raiz, args: ["show", "--stat", "--format=%H%n%an <%ae>%n%ad%n%n%s%n%n%b", c.commit] }); abrirTexto(`commit ${c.commit.slice(0, 7)}`, r.saida || r.erro, "diff"); } },
            el("code", { textContent: (c.commit || "").slice(0, 7) }), el("span", { className: "trunc", textContent: c.assunto || "" }))))));
      } catch (e) { historico.append(el("p", { className: "aviso", textContent: e.message })); }
    });
    conteudo.append(stash, remotos, historico);
  }
  await desenhar();
}

// ------------------------------------------------------------------ Docker
export async function montarDocker(corpo, acoes) {
  const conteudo = el("div", { "aria-live": "polite" });
  acoes.append(botaoAcao("atualizar", "Atualizar", () => desenhar()),
    el("button", { type: "button", className: "icone pequeno", "aria-label": "Receitas de Docker", title: "Receitas de Docker", onclick: () => emitir("receitas", "docker") }, icone("lampada", 16)));
  corpo.append(conteudo);
  const docker = async (args, titulo, { projeto = null, raiz = 0, mostrar = false } = {}) => {
    try {
      const r = await comConfirmacao("POST", "/area/docker/executar", { args, projeto, raiz }, { titulo: `Confirmar: docker ${args.join(" ").slice(0, 80)}` });
      if (!r) return null;
      if (mostrar && r.codigo === 0) abrirTexto(titulo, r.saida || r.erro || "(sem saída)", args[0] === "inspect" ? "json" : "texto");
      else mostrarResultado(titulo, r);
      for (const a of r.avisos || []) toast(a);
      await desenhar();
      return r;
    } catch (e) { toast(e.message, "erro"); return null; }
  };
  const exec = (c) => {
    const campo = el("input", { type: "text", value: "ls /", maxLength: 1000, "aria-label": "Comando dentro do container", spellcheck: false });
    const ok = () => { d.fechar(); const args = campo.value.trim().split(/\s+/).filter(Boolean); if (args.length) docker(["exec", c.Names, ...args], `exec ${c.Names}`, { mostrar: true }); };
    campo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); ok(); } });
    const d = dialogo(`Rodar comando em ${c.Names}`, el("div", {}, el("label", { className: "campo" }, el("span", { textContent: "Comando (sem terminal interativo)" }), campo),
      el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() }), el("button", { type: "button", className: "primario", textContent: "Rodar", onclick: ok }))));
    requestAnimationFrame(() => campo.select());
  };
  let geracao = 0;
  async function desenhar() {
    const minha = ++geracao;
    let cs;
    try { cs = await api("GET", "/area/docker?recurso=containers"); }
    catch (e) {
      if (minha !== geracao) return;
      limpar(conteudo);
      conteudo.append(el("div", { className: "vazio-acao" }, icone("docker", 28), el("p", { textContent: e.message }),
        el("p", { className: "mudo", textContent: "Instale o Docker Desktop (ou ligue o serviço) e clique em Atualizar." })));
      return;
    }
    if (minha !== geracao) return;
    limpar(conteudo);
    const rodando = cs.filter((c) => c.State === "running").length;
    conteudo.append(el("h3", { textContent: `Containers (${rodando} rodando de ${cs.length})` }),
      cs.length ? el("ul", { className: "lista-docker" }, ...cs.map((c) => {
        const vivo = c.State === "running";
        return el("li", {}, el("div", { className: "linha" }, el("span", { className: `ponto ${vivo ? "ok" : ""}`, "aria-hidden": "true" }),
          el("strong", { className: "trunc", textContent: c.Names, title: c.Image }), tag(c.State || "?", vivo ? "ok" : "")),
        el("div", { className: "mudo trunc", textContent: `${c.Image} · ${c.Status}${c.Ports ? ` · ${c.Ports}` : ""}` }),
        el("div", { className: "linha acoes-docker" },
          vivo ? el("button", { type: "button", className: "pequeno", textContent: "■ Parar", onclick: () => docker(["stop", c.ID], `parar ${c.Names}`) })
            : el("button", { type: "button", className: "pequeno", textContent: "▶ Iniciar", onclick: () => docker(["start", c.ID], `iniciar ${c.Names}`) }),
          el("button", { type: "button", className: "pequeno", textContent: "↻", title: "Reiniciar", "aria-label": `Reiniciar ${c.Names}`, onclick: () => docker(["restart", c.ID], `reiniciar ${c.Names}`) }),
          el("button", { type: "button", className: "pequeno", textContent: "Logs", onclick: async () => { const r = await api("GET", `/area/docker/logs?${consulta({ id: c.ID, linhas: 500 })}`); abrirTexto(`logs ${c.Names}`, r.saida || "(sem saída)"); } }),
          vivo ? el("button", { type: "button", className: "pequeno", textContent: "Exec…", title: "Rodar um comando dentro do container", onclick: () => exec(c) }) : null,
          el("button", { type: "button", className: "pequeno", textContent: "Inspecionar", title: "Detalhes (mostra variáveis de ambiente: só na sua tela)", onclick: () => docker(["inspect", c.ID], `inspect ${c.Names}`, { mostrar: true }) }),
          el("button", { type: "button", className: "pequeno perigo", textContent: "Apagar", onclick: () => docker(["rm", ...(vivo ? ["-f"] : []), c.ID], `apagar ${c.Names}`) })));
      })) : el("p", { className: "mudo", textContent: "Nenhum container. Use a receita \"Rodar uma imagem publicando uma porta\"." }));
    const [imgs, vols, redes, comp] = await Promise.all(["imagens", "volumes", "redes", "compose"].map((r) => api("GET", `/area/docker?recurso=${r}`).catch(() => [])));
    if (minha !== geracao) return;
    conteudo.append(
      el("details", {}, el("summary", { textContent: `Imagens (${imgs.length})` }), el("ul", { className: "lista-log" }, ...imgs.map((i) => el("li", { className: "linha" },
        el("span", { className: "trunc", textContent: `${i.Repository}:${i.Tag}` }), el("span", { className: "mudo", textContent: i.Size }),
        el("button", { type: "button", className: "pequeno", textContent: "Rodar…", onclick: () => emitir("receita", { id: "docker.rodar_imagem", valores: { imagem: `${i.Repository}:${i.Tag}` } }) }),
        el("button", { type: "button", className: "pequeno perigo", textContent: "Apagar", onclick: () => docker(["rmi", `${i.Repository}:${i.Tag}` === "<none>:<none>" ? i.ID : `${i.Repository}:${i.Tag}`], "apagar imagem") }))))),
      el("details", {}, el("summary", { textContent: `Volumes (${vols.length})` }), el("ul", { className: "lista-log" }, ...vols.map((v) => el("li", { className: "linha" },
        el("span", { className: "trunc", textContent: v.Name }), el("button", { type: "button", className: "pequeno perigo", textContent: "Apagar", onclick: () => docker(["volume", "rm", v.Name], "apagar volume") }))))),
      el("details", {}, el("summary", { textContent: `Redes (${redes.length})` }), el("ul", { className: "lista-log" }, ...redes.map((n) => el("li", { className: "trunc", textContent: `${n.Name} · ${n.Driver}` })))),
      el("details", {}, el("summary", { textContent: `Compose (${comp.length})` }), el("ul", { className: "lista-log" }, ...comp.map((c) => el("li", { className: "linha" },
        el("strong", { className: "trunc", textContent: c.Name }), el("span", { className: "mudo trunc", textContent: c.Status }),
        el("button", { type: "button", className: "pequeno", textContent: "Parar", onclick: () => docker(["compose", "-p", c.Name, "stop"], `compose ${c.Name}`) }))))),
      el("div", { className: "linha" },
        el("button", { type: "button", className: "pequeno", textContent: "Uso de disco", onclick: () => docker(["system", "df"], "Uso de disco do Docker", { mostrar: true }) }),
        el("button", { type: "button", className: "pequeno perigo", textContent: "Liberar espaço", title: "docker system prune (pede confirmação)", onclick: () => docker(["system", "prune", "-f"], "Liberar espaço") })),
      el("p", { className: "mudo", textContent: "Comandos livres (compose up, build, run...): use o terminal (Ctrl+`), com o assistente explicando cada parte." }));
  }
  await desenhar();
}
