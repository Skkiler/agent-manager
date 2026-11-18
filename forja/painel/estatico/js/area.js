// Barra lateral da bancada: Explorador (arvore das pastas dos projetos), Busca nos arquivos, Controle de codigo (Git) e Docker.
// Tudo pela API (/projetos, /area). A Forja esconde segredos (.env, chaves) em todas as listas e recusa abri-los.
import { api, consulta } from "./api.js";
import { abrirArquivo, abrirTexto } from "./bancada.js";
import { emitir, ouvir } from "./estado.js";
import { icone } from "./icones.js";
import { el, limpar, tag, toast } from "./ui.js";
import { dialogoProjeto } from "./views/projetos.js";

const abertos = new Set(JSON.parse(localStorage.getItem("forja_arvore") || "[]"));
const lembrarArvore = () => localStorage.setItem("forja_arvore", JSON.stringify([...abertos].slice(-200)));
let projetosCache = null;

async function projetos(forcar = false) {
  if (!projetosCache || forcar) projetosCache = api("GET", "/projetos").catch(() => []);
  return projetosCache;
}
ouvir("projetos-mudaram", () => { projetosCache = null; });

const botaoAcao = (nome, rotulo, onclick) => el("button", { type: "button", className: "icone pequeno", "aria-label": rotulo, title: rotulo, onclick }, icone(nome, 16));

/** Seletor de projeto (+ pasta) lembrado entre as telas. */
function seletorProjeto(lista, aoMudar, { comPasta = false, soTrabalho = false } = {}) {
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

const semProjeto = (corpo) => corpo.append(el("p", { className: "mudo", textContent: "Nenhum projeto com pasta ainda. Crie um projeto e escolha a pasta de trabalho." }),
  el("button", { type: "button", className: "primario", textContent: "+ Projeto", onclick: () => dialogoProjeto(null, () => emitir("projetos-mudaram")) }));

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
      const r = await api("GET", `/projetos/${p.id}/arquivos?${consulta({ raiz, rel })}`);
      filhos.append(...r.itens.map((it) => el("li", {}, it.pasta ? noPasta(p, raiz, it.rel, it.nome, nivel + 1, papel)
        : (() => {
          const f = el("button", { type: "button", className: "no-arvore arquivo", tabIndex: -1, title: it.rel, onclick: () => abrirArquivo({ projeto: p.id, raiz, rel: it.rel, nome: it.nome }) },
            el("span", { className: "seta vazia", "aria-hidden": "true" }), icone("arquivo", 15), el("span", { className: "trunc", textContent: it.nome }));
          f.style.setProperty("--nivel", String(nivel + 1));
          return f;
        })())));
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
    corpo.append(arvore, el("p", { className: "mudo dica-arvore", textContent: "Arquivos de segredo (.env, chaves) não aparecem e não abrem. Pastas de consulta são somente leitura." }));
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
  const incluir = el("input", { type: "text", maxLength: 60, placeholder: "ex.: *.py", "aria-label": "Arquivos a incluir (padrão)" });
  const resultado = el("div", { className: "resultado-busca", "aria-live": "polite" });
  const buscar = async () => {
    const q = termo.value.trim();
    limpar(resultado);
    if (!q) return;
    const p = sel.projeto();
    resultado.append(el("p", { className: "mudo", textContent: "Buscando…" }));
    const grupos = [];
    let total = 0;
    for (let raiz = 0; raiz < p.pastas.length; raiz += 1) {
      try {
        const r = await api("GET", `/area/buscar?${consulta({ projeto: p.id, raiz, padrao: q, regex: regex.checked ? "true" : "", incluir: incluir.value.trim() })}`);
        const porArquivo = new Map();
        for (const o of r.ocorrencias) { if (!porArquivo.has(o.arquivo)) porArquivo.set(o.arquivo, []); porArquivo.get(o.arquivo).push(o); }
        for (const [arq, os] of porArquivo) { total += os.length; grupos.push({ raiz, arq, os }); }
      } catch (e) { grupos.push({ erro: e.message }); }
    }
    limpar(resultado);
    resultado.append(el("p", { className: "mudo", role: "status", textContent: total ? `${total} resultado(s) em ${grupos.filter((g) => !g.erro).length} arquivo(s)` : "Nenhum resultado." }));
    for (const g of grupos) {
      if (g.erro) { resultado.append(el("p", { className: "aviso", textContent: g.erro })); continue; }
      resultado.append(el("details", { open: true }, el("summary", { className: "trunc", title: g.arq }, icone("arquivo", 14), ` ${g.arq.split("/").pop()} `, el("span", { className: "mudo", textContent: g.arq })),
        el("ul", { className: "lista-ocorrencias" }, ...g.os.map((o) => el("li", {}, el("button", { type: "button", className: "bloco",
          onclick: () => abrirArquivo({ projeto: p.id, raiz: g.raiz, rel: o.arquivo, linha: o.linha }) },
        el("span", { className: "mudo num-linha", textContent: String(o.linha) }), el("span", { className: "trunc", textContent: o.texto })))))));
    }
  };
  termo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); buscar(); } });
  corpo.append(sel.no, termo, el("div", { className: "linha" }, el("label", {}, regex, " expressão regular"), incluir),
    el("button", { type: "button", className: "primario", textContent: "Buscar", onclick: buscar }), resultado);
  requestAnimationFrame(() => termo.focus());
}

// ------------------------------------------------------------------ Controle de codigo (Git)
const ROTULO_GIT = { M: "modificado", A: "adicionado", D: "apagado", R: "renomeado", C: "copiado", U: "conflito", "?": "novo" };

export async function montarGit(corpo, acoes) {
  const lista = (await projetos()).filter((p) => (p.pastas || []).length);
  if (!lista.length) return semProjeto(corpo);
  const conteudo = el("div");
  const sel = seletorProjeto(lista, () => desenhar(), { comPasta: true });
  acoes.append(botaoAcao("atualizar", "Atualizar", () => desenhar()));
  corpo.append(sel.no, conteudo);
  async function acao(nome, arquivos, mensagem = "") {
    try {
      const r = await api("POST", "/area/git", { projeto: sel.projeto().id, raiz: sel.raiz(), acao: nome, arquivos, mensagem });
      for (const a of r.avisos || []) toast(a, "erro");
      if (nome === "commit") toast("Commit feito.", "ok");
      emitir("git-mudou");
      await desenhar();
    } catch (e) { toast(e.message, "erro"); }
  }
  async function diff(arquivo) {
    try {
      const r = await api("GET", `/area/git?${consulta({ projeto: sel.projeto().id, raiz: sel.raiz(), operacao: "diff", arquivo })}`);
      abrirTexto(`diff ${arquivo.split("/").pop()}`, r.resumo, "diff");
    } catch (e) { toast(e.message, "erro"); }
  }
  async function desenhar() {
    limpar(conteudo);
    const p = sel.projeto(), raiz = sel.raiz();
    const trabalho = p.pastas[raiz]?.papel === "trabalho";
    try {
      const st = await api("GET", `/area/git?${consulta({ projeto: p.id, raiz })}`);
      if (st.dados.repositorio === false) {
        conteudo.append(el("p", { className: "mudo", textContent: "Esta pasta não é um repositório Git. Use o terminal (Ctrl+`) com git init, se quiser versionar." }));
        return;
      }
      const log = await api("GET", `/area/git?${consulta({ projeto: p.id, raiz, operacao: "log", limite: 15 })}`).catch(() => null);
      const itens = st.dados.alterados || [];
      const preparados = itens.filter((i) => i.x && i.x !== " " && i.x !== "?");
      const alterados = itens.filter((i) => !i.x || i.y !== " " || i.x === "?");
      const linha = (i, preparado) => {
        const nome = i.arquivo.split(" -> ").pop();
        const cod = (preparado ? i.x : i.y === " " ? i.x : i.y) || i.estado[0];
        return el("li", { className: "linha-git" },
          el("button", { type: "button", className: "bloco", title: `Ver diferenças de ${nome}`, onclick: () => diff(nome) },
            el("span", { className: "trunc", textContent: nome.split("/").pop() }), el("span", { className: "mudo trunc", textContent: nome.includes("/") ? nome.slice(0, nome.lastIndexOf("/")) : "" })),
          el("span", { className: `estado-git git-${cod === "?" ? "novo" : cod}`, title: ROTULO_GIT[cod] || cod, textContent: cod === "?" ? "U" : cod }),
          trabalho ? el("button", { type: "button", className: "icone pequeno", "aria-label": `${preparado ? "Tirar da preparação" : "Preparar"} ${nome}`,
            title: preparado ? "Tirar da preparação (unstage)" : "Preparar para commit (stage)", textContent: preparado ? "−" : "+",
            onclick: () => acao(preparado ? "unstage" : "stage", [nome]) }) : null);
      };
      const msg = el("textarea", { rows: 2, maxLength: 2000, placeholder: "Mensagem do commit", "aria-label": "Mensagem do commit", disabled: !trabalho });
      conteudo.append(el("p", { className: "mudo", textContent: `Branch ${(st.dados.branch || "?").split("...")[0]}` }));
      for (const a of st.avisos || []) conteudo.append(el("p", { className: "aviso", textContent: a }));
      if (trabalho) {
        conteudo.append(msg, el("div", { className: "linha" },
          el("button", { type: "button", className: "primario", textContent: "Commit", disabled: !preparados.length, title: preparados.length ? "Commit das alterações preparadas" : "Prepare arquivos (+) primeiro",
            onclick: () => acao("commit", [], msg.value) }),
          alterados.length ? el("button", { type: "button", className: "pequeno", textContent: "Preparar tudo", onclick: () => acao("stage", []) }) : null),
        el("p", { className: "mudo", textContent: "A Forja não faz push: envie pelo seu terminal ou IDE quando quiser." }));
      } else conteudo.append(el("p", { className: "aviso", textContent: "Pasta de consulta: somente leitura (sem stage nem commit)." }));
      if (preparados.length) conteudo.append(el("h3", { textContent: `Preparadas (${preparados.length})` }), el("ul", { className: "lista-git" }, ...preparados.map((i) => linha(i, true))));
      conteudo.append(el("h3", { textContent: `Alterações (${alterados.length})` }),
        alterados.length ? el("ul", { className: "lista-git" }, ...alterados.map((i) => linha(i, false))) : el("p", { className: "mudo", textContent: "Nada alterado." }));
      if (log?.dados?.commits?.length) conteudo.append(el("details", {}, el("summary", { textContent: "Histórico (últimos commits)" }),
        el("ul", { className: "lista-log" }, ...log.dados.commits.map((c) => el("li", { title: `${c.commit} · ${c.autor || ""} · ${c.data || ""}` },
          el("code", { textContent: (c.commit || "").slice(0, 7) }), " ", el("span", { textContent: c.assunto || "" }))))));
    } catch (e) { conteudo.append(el("p", { className: "aviso", textContent: e.message.includes("git") ? e.message : `Git: ${e.message}` })); }
  }
  await desenhar();
}

// ------------------------------------------------------------------ Docker
export async function montarDocker(corpo, acoes) {
  const conteudo = el("div", { "aria-live": "polite" });
  acoes.append(botaoAcao("atualizar", "Atualizar", () => desenhar()));
  corpo.append(el("p", { className: "mudo", textContent: "Listar, ver logs e iniciar/parar/reiniciar. A Forja não usa inspect nem exec (mostram variáveis de ambiente)." }), conteudo);
  async function acao(id, a) {
    try { await api("POST", "/area/docker", { id, acao: a }); toast(`${a} enviado para ${id}`, "ok"); await desenhar(); } catch (e) { toast(e.message, "erro"); }
  }
  async function logs(c) {
    try { const r = await api("GET", `/area/docker/logs?${consulta({ id: c.ID, linhas: 300 })}`); abrirTexto(`logs ${c.Names}`, r.saida || "(sem saída)", "texto"); }
    catch (e) { toast(e.message, "erro"); }
  }
  async function desenhar() {
    limpar(conteudo);
    try {
      const cs = await api("GET", "/area/docker?recurso=containers");
      conteudo.append(el("h3", { textContent: `Containers (${cs.length})` }),
        cs.length ? el("ul", { className: "lista-docker" }, ...cs.map((c) => {
          const rodando = c.State === "running";
          return el("li", {}, el("div", { className: "linha" }, el("span", { className: `ponto ${rodando ? "ok" : ""}`, "aria-hidden": "true" }),
            el("strong", { className: "trunc", textContent: c.Names, title: c.Image }), tag(c.State || "?", rodando ? "ok" : "")),
          el("div", { className: "mudo trunc", textContent: `${c.Image} · ${c.Status}${c.Ports ? ` · ${c.Ports}` : ""}` }),
          el("div", { className: "linha" },
            rodando ? el("button", { type: "button", className: "pequeno", textContent: "Parar", onclick: () => acao(c.ID, "stop") })
              : el("button", { type: "button", className: "pequeno", textContent: "Iniciar", onclick: () => acao(c.ID, "start") }),
            el("button", { type: "button", className: "pequeno", textContent: "Reiniciar", onclick: () => acao(c.ID, "restart") }),
            el("button", { type: "button", className: "pequeno", textContent: "Logs", onclick: () => logs(c) })));
        })) : el("p", { className: "mudo", textContent: "Nenhum container." }));
      const [imgs, comp] = await Promise.all([api("GET", "/area/docker?recurso=imagens").catch(() => []), api("GET", "/area/docker?recurso=compose").catch(() => [])]);
      conteudo.append(el("details", {}, el("summary", { textContent: `Imagens (${imgs.length})` }),
        el("ul", { className: "lista-log" }, ...imgs.map((i) => el("li", { className: "trunc", textContent: `${i.Repository}:${i.Tag} · ${i.Size}` })))),
      el("details", {}, el("summary", { textContent: `Compose (${comp.length})` }),
        el("ul", { className: "lista-log" }, ...comp.map((c) => el("li", { className: "trunc", textContent: `${c.Name} · ${c.Status}` })))));
    } catch (e) { conteudo.append(el("p", { className: "aviso", textContent: e.message })); }
  }
  await desenhar();
}
