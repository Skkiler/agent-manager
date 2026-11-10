// Projetos (estilo Codex): cada projeto tem pastas de TRABALHO (o agente altera, conforme a autonomia) e de CONSULTA (so leitura).
// Tambem: explorador/@mencao de arquivos do projeto e anexos de tarefa (do projeto ou enviados de qualquer lugar).
import { api } from "../api.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";

const PAPEIS = [["trabalho", "Trabalho (agente pode alterar)"], ["consulta", "Consulta (so leitura)"]];

function editorPastas(pastas) {
  const lista = el("div", { className: "pastas-projeto" });
  const linha = (p = { caminho: "", papel: "trabalho" }) => {
    const caminho = el("input", { value: p.caminho, maxLength: 500, placeholder: "C:\\caminho\\completo\\da\\pasta", "aria-label": "Caminho da pasta", spellcheck: false });
    const papel = el("select", { "aria-label": "Papel da pasta" }, ...PAPEIS.map(([v, r]) => el("option", { value: v, textContent: r, selected: v === p.papel })));
    const row = el("div", { className: "linha" }, caminho, papel, el("button", { type: "button", textContent: "remover", "aria-label": "Remover pasta", onclick: () => row.remove() }));
    row.ler = () => ({ caminho: caminho.value.trim(), papel: papel.value });
    lista.append(row);
  };
  (pastas.length ? pastas : [undefined]).forEach((p) => linha(p));
  return { no: el("div", {}, lista, el("button", { type: "button", textContent: "+ pasta", onclick: () => linha() })),
    ler: () => [...lista.children].map((r) => r.ler()).filter((p) => p.caminho) };
}

export function dialogoProjeto(projeto, aoSalvar) {
  const nome = el("input", { required: true, maxLength: 200, value: projeto?.nome || "", disabled: Boolean(projeto), "aria-label": "Nome do projeto" });
  const desc = el("textarea", { rows: 2, maxLength: 4000, value: projeto?.descricao || "", disabled: Boolean(projeto), "aria-label": "Descricao" });
  const pastas = editorPastas(projeto?.pastas || []);
  const form = el("form", {},
    el("label", { className: "campo" }, el("span", { textContent: "Nome" }), nome),
    el("label", { className: "campo" }, el("span", { textContent: "Descricao" }), desc),
    el("h3", { textContent: "Pastas" }),
    el("p", { className: "mudo", textContent: "Trabalho: o agente trabalha ali (o que ele pode fazer depende do nivel de autonomia). Consulta: o agente so le, para se basear. Pastas proibidas, .git e os dados da Forja nunca entram." }),
    pastas.no,
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Salvar" }), el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo(projeto ? `Pastas de ${projeto.nome}` : "Novo projeto", form);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const p = projeto || await api("POST", "/projetos", { nome: nome.value.trim(), descricao: desc.value });
      const salvo = await api("PUT", `/projetos/${p.id}/pastas`, { expected_version: p.versao ?? 1, pastas: pastas.ler() });
      d.fechar(); toast("Projeto salvo", "ok"); aoSalvar?.(salvo);
    } catch (e) { toast(e.status === 409 ? "O projeto mudou em outra aba. Reabra." : e.message, "erro"); }
  });
}

export function resumoPastas(p) {
  const t = (p.pastas || []).filter((x) => x.papel === "trabalho").length, c = (p.pastas || []).filter((x) => x.papel === "consulta").length;
  return t || c ? `${t} de trabalho, ${c} de consulta` : "sem pastas (agente usa pasta isolada)";
}

// ------------------------------------------------------------------ escolher arquivo do projeto (@mencao + explorador)
export function escolherArquivo(projeto, aoEscolher) {
  const busca = el("input", { type: "search", maxLength: 100, placeholder: "@ nome do arquivo", "aria-label": "Buscar arquivo do projeto" });
  const resultados = el("ul", { className: "lista-notas", "aria-label": "Arquivos encontrados", "aria-live": "polite" });
  const arvore = el("ul", { className: "lista-notas explorador", "aria-label": "Explorador do projeto" });
  const caminhoAtual = el("p", { className: "mudo mono" });
  let estado = { raiz: 0, rel: "" };
  const escolher = (raiz, rel) => { d.fechar(); aoEscolher(raiz, rel); };
  const item = (r) => el("li", {}, el("button", { type: "button", onclick: () => escolher(r.raiz, r.rel) },
    el("span", { textContent: r.nome }), " ", el("span", { className: "mudo mono", textContent: r.rel }), " ", tag(r.papel)));
  const listar = async () => {
    try {
      const r = await api("GET", `/projetos/${projeto.id}/arquivos?raiz=${estado.raiz}&rel=${encodeURIComponent(estado.rel)}`);
      limpar(arvore);
      caminhoAtual.textContent = `${projeto.pastas[estado.raiz].caminho}${r.rel ? "/" + r.rel : ""}`;
      if (estado.rel) arvore.append(el("li", {}, el("button", { type: "button", textContent: "⬑ ..", onclick: () => { estado.rel = estado.rel.split("/").slice(0, -1).join("/"); listar(); } })));
      arvore.append(...r.itens.map((i) => el("li", {}, el("button", { type: "button", textContent: `${i.pasta ? "▸ " : ""}${i.nome}`,
        onclick: () => (i.pasta ? (estado.rel = i.rel, listar()) : escolher(estado.raiz, i.rel)) }))));
    } catch (e) { toast(e.message, "erro"); }
  };
  busca.addEventListener("input", () => {
    clearTimeout(busca._t);
    busca._t = setTimeout(async () => {
      limpar(resultados);
      const q = busca.value.replace(/^@/, "").trim();
      if (!q) return;
      try { const r = await api("GET", `/projetos/${projeto.id}/buscar-arquivos?q=${encodeURIComponent(q)}`); resultados.append(...(r.length ? r.map(item) : [el("li", { className: "mudo", textContent: "Nada encontrado." })])); }
      catch (e) { toast(e.message, "erro"); }
    }, 200);
  });
  const raizes = el("select", { "aria-label": "Pasta do projeto", onchange: () => { estado = { raiz: Number(raizes.value), rel: "" }; listar(); } },
    ...projeto.pastas.map((p, i) => el("option", { value: i, textContent: `${p.papel}: ${p.caminho}` })));
  const d = dialogo(`Anexar arquivo de ${projeto.nome}`, el("div", { className: "escolher-arquivo" }, busca, resultados, el("h3", { textContent: "Explorar" }), raizes, caminhoAtual, arvore,
    el("div", { className: "linha" }, el("button", { type: "button", textContent: "Fechar", onclick: () => d.fechar() }))));
  listar(); busca.focus();
}

// ------------------------------------------------------------------ anexos da tarefa (painel de conversa)
const lerBase64 = (arquivo) => new Promise((ok, erro) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",", 2)[1] || "");
  r.onerror = () => erro(new Error("nao foi possivel ler o arquivo"));
  r.readAsDataURL(arquivo);
});

export async function secaoAnexos(tarefaId, aoMudar) {
  const caixa = el("section", { className: "anexos", "aria-label": "Anexos da tarefa" });
  let projeto = null;
  try {
    const t = await api("GET", `/tarefas/${tarefaId}`);
    const o = await api("GET", `/objetivos/${t.objetivo_id}`);
    projeto = await api("GET", `/projetos/${o.projeto_id}`);
  } catch { /* sem projeto: so envio */ }
  const lista = await api("GET", `/tarefas/${tarefaId}/anexos`).catch(() => []);
  const enviar = el("input", { type: "file", multiple: true, className: "sr-only", id: `anexo-${tarefaId}`,
    accept: ".txt,.md,.py,.js,.ts,.json,.csv,.log,.sql,.yaml,.yml,.toml,.ini,.html,.css,.ps1,.sh,.xml,.png,.jpg,.jpeg,.gif,.webp" });
  enviar.addEventListener("change", async () => {
    for (const f of enviar.files) {
      try { await api("POST", `/tarefas/${tarefaId}/anexos/envio`, { nome: f.name, conteudo_b64: await lerBase64(f), mime: f.type || "" }); toast(`Anexado: ${f.name}`, "ok"); }
      catch (e) { toast(`${f.name}: ${e.message}`, "erro"); }
    }
    aoMudar();
  });
  const doProjeto = projeto?.pastas?.length ? el("button", { type: "button", textContent: "@ do projeto", title: "Buscar ou explorar arquivos das pastas do projeto",
    onclick: () => escolherArquivo(projeto, async (raiz, rel) => {
      try { await api("POST", `/tarefas/${tarefaId}/anexos/projeto`, { raiz, rel }); toast("Anexado", "ok"); aoMudar(); } catch (e) { toast(e.message, "erro"); }
    }) }) : null;
  caixa.append(el("div", { className: "linha" }, el("strong", { textContent: `Anexos (${lista.length})` }), el("span", { className: "espaco" }),
    el("label", { htmlFor: `anexo-${tarefaId}`, className: "botao", tabIndex: 0, role: "button", textContent: "Anexar arquivo",
      onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); enviar.click(); } } }), enviar, doProjeto),
    projeto ? el("p", { className: "mudo", textContent: `Projeto ${projeto.nome}: ${resumoPastas(projeto)}` }) : null,
    lista.length ? el("ul", { className: "chips" }, ...lista.map((a) => el("li", { className: "chip-anexo" },
      el("span", { textContent: `${a.mime.startsWith("image/") ? "🖼 " : ""}${a.nome}`, title: a.caminho || "enviado por voce (so este arquivo e visivel)" }),
      a.truncado ? tag("cortado", "aviso") : null,
      el("button", { type: "button", textContent: "×", "aria-label": `Remover anexo ${a.nome}`, onclick: async () => {
        try { await api("DELETE", `/tarefas/${tarefaId}/anexos/${a.id}`); aoMudar(); } catch (e) { toast(e.message, "erro"); }
      } })))) : el("p", { className: "mudo", textContent: "Anexe arquivos (do projeto ou de qualquer pasta) para o agente ler na proxima execucao." }));
  return caixa;
}
