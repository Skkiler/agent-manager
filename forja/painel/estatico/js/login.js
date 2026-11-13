// Tela de acesso: primeiro acesso (cria a conta) e login por usuario e senha, com retorno claro de erro, bloqueio e sucesso.
// A sessao fica so nesta aba (sessionStorage) e e enviada como Bearer; o token da API continua para scripts e MCP.
import { api, definirToken, lerToken } from "./api.js";
import { dialogo, el, toast } from "./ui.js";

const tela = () => document.getElementById("tela-login");
const FUNDO = ["#barra-titulo", "#area", "#barra-status"];

function bloquearFundo(sim) {
  for (const s of FUNDO) { const n = document.querySelector(s); if (n) n.inert = sim; }
}

function campoSenha(id, rotulo, autocomplete) {
  const input = el("input", { id, type: "password", autocomplete, required: true, maxLength: 200, spellcheck: false });
  const olho = el("button", { type: "button", className: "mostrar-senha", "aria-pressed": "false", "aria-label": `Mostrar ${rotulo.toLowerCase()}`,
    title: "Mostrar ou esconder", textContent: "👁",
    onclick: () => { const ver = input.type === "password"; input.type = ver ? "text" : "password"; olho.setAttribute("aria-pressed", String(ver)); input.focus(); } });
  const caps = el("small", { className: "caps", hidden: true, textContent: "Caps Lock ligado" });
  const conferirCaps = (ev) => { if (ev.getModifierState) caps.hidden = !ev.getModifierState("CapsLock"); };
  input.addEventListener("keydown", conferirCaps); input.addEventListener("keyup", conferirCaps);
  const grupo = el("div", { className: "campo-login" }, el("label", { htmlFor: id, textContent: rotulo }),
    el("div", { className: "senha-caixa" }, input, olho), caps);
  return { grupo, input };
}

/** Forca aproximada (comprimento + variedade): so orienta, quem decide e o servidor. */
function forca(s) {
  if (!s) return [0, ""];
  let pts = Math.min(4, Math.floor(s.length / 4));
  pts += [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(s)).length;
  if (s.length < 8) return [1, "curta demais (mínimo 8)"];
  return pts >= 7 ? [4, "forte"] : pts >= 5 ? [3, "boa"] : [2, "fraca: prefira uma frase longa"];
}

function cartao(titulo, subtitulo, ...filhos) {
  return el("div", { className: "login-cartao", role: "dialog", "aria-modal": "true", "aria-labelledby": "login-titulo" },
    el("div", { className: "login-marca" }, el("img", { src: "/estatico/icone.svg", alt: "", width: 40, height: 40 }),
      el("div", {}, el("strong", { textContent: "Forja" }), el("span", { textContent: "orquestrador local" }))),
    el("h1", { id: "login-titulo", textContent: titulo }), subtitulo ? el("p", { className: "mudo", textContent: subtitulo }) : null, ...filhos);
}

function caixaErro() {
  return el("div", { className: "login-erro", role: "alert", hidden: true });
}

function mostrarErro(caixa, texto) {
  caixa.textContent = texto; caixa.hidden = !texto;
}

function rodape(estado) {
  return el("p", { className: "login-rodape mudo",
    textContent: `Conexão com o servidor deste computador. A sessão fica só nesta aba e expira após ${estado.inatividade_min || 60} min sem uso.` });
}

function sucesso(raiz, usuario, resolver) {
  raiz.replaceChildren(cartao(`Bem-vindo, ${usuario}`, "Acesso liberado. Abrindo o painel…", el("div", { className: "login-ok", "aria-hidden": "true", textContent: "✓" })));
  raiz.querySelector(".login-cartao").setAttribute("role", "status");
  setTimeout(() => { raiz.classList.add("saindo"); setTimeout(() => { raiz.hidden = true; raiz.classList.remove("saindo"); bloquearFundo(false); resolver(usuario); }, 220); }, 650);
}

async function enviar(caminho, corpo, botao, erro, rotuloOcupado) {
  const original = botao.textContent;
  botao.disabled = true; botao.textContent = rotuloOcupado; botao.setAttribute("aria-busy", "true");
  mostrarErro(erro, "");
  try { return await api("POST", caminho, corpo); }
  finally { botao.disabled = false; botao.textContent = original; botao.removeAttribute("aria-busy"); }
}

function formEntrar(raiz, estado, resolver, aviso) {
  const usuario = el("input", { id: "login-usuario", autocomplete: "username", required: true, maxLength: 64, spellcheck: false, autocapitalize: "none" });
  const senha = campoSenha("login-senha", "Senha", "current-password");
  const erro = caixaErro();
  const botao = el("button", { type: "submit", className: "primario login-botao", textContent: "Entrar" });
  let contagem = null;
  const bloquear = (s) => {
    clearInterval(contagem);
    let resta = s;
    const tique = () => {
      if (resta <= 0) { clearInterval(contagem); botao.disabled = false; botao.textContent = "Entrar"; mostrarErro(erro, ""); return; }
      botao.disabled = true; botao.textContent = `Aguarde ${resta} s`; resta -= 1;
    };
    tique(); contagem = setInterval(tique, 1000);
  };
  const form = el("form", { className: "login-form", noValidate: true },
    aviso ? el("p", { className: "login-aviso", role: "status", textContent: aviso }) : null,
    el("div", { className: "campo-login" }, el("label", { htmlFor: "login-usuario", textContent: "Usuário" }), usuario),
    senha.grupo, erro, botao, rodape(estado));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!usuario.value.trim() || !senha.input.value) return mostrarErro(erro, "Informe usuário e senha.");
    try {
      const r = await enviar("/auth/entrar", { usuario: usuario.value.trim(), senha: senha.input.value }, botao, erro, "Entrando…");
      definirToken(r.token); senha.input.value = "";
      sucesso(raiz, r.usuario, resolver);
    } catch (e) {
      senha.input.value = ""; senha.input.focus();
      mostrarErro(erro, e.status === 0 ? "Sem conexão com o servidor. Ele está rodando?" : e.message);
      if (e.status === 429 && e.dados?.tentar_em_s) bloquear(e.dados.tentar_em_s);
      form.classList.remove("tremer"); void form.offsetWidth; form.classList.add("tremer");
    }
  });
  raiz.replaceChildren(cartao("Entrar", "Use o usuário e a senha desta instalação.", form));
  usuario.focus();
}

function formConfigurar(raiz, estado, resolver) {
  const usuario = el("input", { id: "login-usuario", autocomplete: "username", required: true, maxLength: 32, spellcheck: false, autocapitalize: "none",
    placeholder: "ex.: ana" });
  const senha = campoSenha("login-senha", "Senha", "new-password");
  const repete = campoSenha("login-senha2", "Repita a senha", "new-password");
  const barra = el("meter", { min: 0, max: 4, low: 2, high: 3, optimum: 4, value: 0, "aria-label": "Força da senha" });
  const textoForca = el("small", { className: "mudo", "aria-live": "polite" });
  senha.input.addEventListener("input", () => { const [v, t] = forca(senha.input.value); barra.value = v; textoForca.textContent = t ? `Força: ${t}` : ""; });
  const erro = caixaErro();
  const botao = el("button", { type: "submit", className: "primario login-botao", textContent: "Criar acesso e entrar" });
  const form = el("form", { className: "login-form", noValidate: true },
    el("div", { className: "campo-login" }, el("label", { htmlFor: "login-usuario", textContent: "Usuário" }), usuario,
      el("small", { className: "mudo", textContent: "3 a 32 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado." })),
    senha.grupo, el("div", { className: "forca" }, barra, textoForca), repete.grupo,
    el("ul", { className: "login-regras mudo" }, el("li", { textContent: "Pelo menos 8 caracteres; uma frase longa é o melhor." }),
      el("li", { textContent: "Não use o nome de usuário nem senhas comuns." })),
    erro, botao, rodape(estado));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!usuario.value.trim()) return mostrarErro(erro, "Escolha um nome de usuário.");
    if (senha.input.value.length < 8) return mostrarErro(erro, "A senha precisa de pelo menos 8 caracteres.");
    if (senha.input.value !== repete.input.value) { repete.input.focus(); return mostrarErro(erro, "As senhas não conferem."); }
    try {
      const r = await enviar("/auth/configurar", { usuario: usuario.value.trim(), senha: senha.input.value }, botao, erro, "Criando…");
      definirToken(r.token); senha.input.value = repete.input.value = "";
      sucesso(raiz, r.usuario, resolver);
    } catch (e) { mostrarErro(erro, e.status === 0 ? "Sem conexão com o servidor. Ele está rodando?" : e.message); }
  });
  raiz.replaceChildren(cartao("Primeiro acesso", "Crie o usuário e a senha que vão proteger este painel.", form));
  usuario.focus();
}

function semPermissao(raiz) {
  raiz.replaceChildren(cartao("Acesso ainda não configurado", "Por segurança, a primeira conta só é criada no computador do servidor.",
    el("p", {}, "No computador (ou contêiner) onde a Forja roda, execute:"),
    el("pre", { className: "saida" }, "python -m forja.usuario.contas_cli criar --usuario SEU_NOME"),
    el("p", { className: "mudo", textContent: "Ou abra o painel por http://127.0.0.1 nesse computador. Depois, recarregue esta página." }),
    el("button", { type: "button", className: "primario login-botao", textContent: "Recarregar", onclick: () => location.reload() })));
}

/** Resolve com o nome do usuario conectado (ou null se o servidor nao exige login). Mostra a tela se preciso. */
export async function garantirAcesso(aviso = "") {
  let estado;
  try { estado = await api("GET", "/auth/estado"); } catch { estado = { exige_login: true, configurado: true, conectado: false }; }
  if (!estado.exige_login) return null;
  if (estado.conectado) return estado.usuario;
  if (lerToken()) definirToken("");  // credencial velha (sessao expirada): descarta
  const raiz = tela();
  raiz.hidden = false; bloquearFundo(true);
  return new Promise((resolver) => {
    if (estado.configurado) formEntrar(raiz, estado, resolver, aviso);
    else if (estado.pode_configurar) formConfigurar(raiz, estado, resolver);
    else semPermissao(raiz);
  });
}

export async function sair() {
  try { await api("POST", "/auth/sair"); } catch { /* sessao ja expirada: tudo bem */ }
  definirToken(""); location.reload();
}

export function dialogoConta(usuario) {
  const atual = campoSenha("conta-atual", "Senha atual", "current-password");
  const nova = campoSenha("conta-nova", "Nova senha", "new-password");
  const repete = campoSenha("conta-nova2", "Repita a nova senha", "new-password");
  const erro = caixaErro();
  const salvar = el("button", { type: "submit", className: "primario", textContent: "Trocar senha" });
  const form = el("form", { className: "login-form", noValidate: true }, el("p", { textContent: `Conectado como ${usuario}.` }),
    atual.grupo, nova.grupo, repete.grupo, erro,
    el("div", { className: "linha" }, salvar, el("button", { type: "button", textContent: "Sair da conta", onclick: sair })));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (nova.input.value !== repete.input.value) return mostrarErro(erro, "As senhas novas não conferem.");
    try {
      await enviar("/auth/senha", { senha_atual: atual.input.value, nova_senha: nova.input.value }, salvar, erro, "Salvando…");
      d.fechar(); toast("Senha trocada. Outras sessões foram encerradas.", "ok");
    } catch (e) { mostrarErro(erro, e.message); }
  });
  const d = dialogo("Sua conta", form);
  atual.input.focus();
}
