// Acoes do usuario com risco (push, apagar, reset --hard, segredo no commit...): o servidor responde 428 com os motivos; aqui
// a Forja PERGUNTA e, se o usuario confirmar, reenvia com `confirmado: true`. Nunca bloqueia (bloqueios sao so para os agentes).
import { api } from "./api.js";
import { dialogo, el } from "./ui.js";

/** Pergunta com os motivos. Resolve true (seguir) ou false (cancelar). */
export function confirmarRisco(titulo, motivos = [], { acao = "Executar mesmo assim", risco = "alto", detalhe = "" } = {}) {
  return new Promise((resolver) => {
    let decidido = false;
    const fim = (v) => { if (decidido) return; decidido = true; d.fechar(); resolver(v); };
    const seguir = el("button", { type: "button", className: risco === "alto" ? "perigo-forte" : "primario", textContent: acao, onclick: () => fim(true) });
    const corpo = el("div", { className: "confirmar-risco" },
      el("p", { className: `selo-risco risco-${risco}`, textContent: risco === "alto" ? "Ação de risco alto" : "Confira antes de seguir" }),
      detalhe ? el("pre", { className: "confirmar-linha", textContent: detalhe }) : null,
      motivos.length ? el("ul", {}, ...motivos.map((m) => el("li", { textContent: m }))) : null,
      el("p", { className: "mudo", textContent: "A Forja só pergunta: a decisão é sua. Nada disso é enviado aos agentes." }),
      el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => fim(false) }), seguir));
    const d = dialogo(titulo, corpo);
    const dlg = document.getElementById("dlg-geral");
    dlg.addEventListener("close", () => fim(false), { once: true });
    requestAnimationFrame(() => seguir.focus());
  });
}

/** Chama a API; se vier 428, pergunta e repete com confirmado=true. Devolve a resposta (ou null se o usuario cancelou). */
export async function comConfirmacao(metodo, caminho, corpo, { titulo = "Confirmar ação", detalhe = "" } = {}) {
  try {
    return await api(metodo, caminho, corpo);
  } catch (e) {
    if (e.status !== 428) throw e;
    const info = e.dados?.dados || {};
    const ok = await confirmarRisco(titulo, info.motivos || [], { risco: info.risco || "alto", detalhe: detalhe || e.message.replace(/^Confirme:\s*/, "") });
    if (!ok) return null;
    return api(metodo, caminho, { ...corpo, confirmado: true });
  }
}
