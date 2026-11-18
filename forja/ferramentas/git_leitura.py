"""git.ler: Git SOMENTE LEITURA e estruturado (status, log, diff, blame, show, branches).

Por que existe: o agente roda `git status`/`git diff` pelo shell, o que pede permissao a cada vez (custa tempo) e devolve saida
longa. Aqui:
- argumentos fixos, sem shell; referencias e caminhos validados (nada que comece com '-' vira opcao), caminhos depois de `--`;
- ambiente limpo, sem pager, sem prompt de credencial, sem travas opcionais (GIT_OPTIONAL_LOCKS=0), tempo maximo;
- arquivos com cara de segredo nunca aparecem: saem do diff/blame/status (nem o nome do conteudo e mostrado no diff);
- diff resumido pela mesma analise do `git.diff_analisar` + trecho limitado; tudo com segredos redigidos.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.ferramentas.diff import resumir_diff
from forja.ferramentas.verificacao import ambiente_limpo
from forja.seguranca.sensiveis import caminho_sensivel

OPERACOES = ("status", "log", "diff", "blame", "show", "branches")
TIMEOUT_S = 20.0
MAX_SAIDA = 400_000
MAX_DIFF_TEXTO = 12_000
_REF = re.compile(r"^(?!-)[A-Za-z0-9._/~^@{}+-]{1,120}$")  # sem ':' -> 'HEAD:.env' (conteudo de arquivo) nunca e aceito
_SECAO_DIFF = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")


def _git(args: list[str], cwd: Path) -> str:
    env = {**ambiente_limpo(), "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "PAGER": "cat", "LC_ALL": "C"}
    try:
        # core.fsmonitor=false: um repositorio pode configurar um programa que o git executaria no 'status' (nao rodamos nada do repo)
        r = subprocess.run(["git", "--no-pager", "-c", "core.quotepath=false", "-c", "color.ui=false", "-c", "core.fsmonitor=false",  # noqa: S603, S607
                            *args],
                           cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError as e:
        raise ValidacaoDominio("git nao encontrado nesta maquina") from e
    except subprocess.TimeoutExpired as e:
        raise ValidacaoDominio(f"git demorou mais de {TIMEOUT_S:.0f}s") from e
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()[-1:] or ["erro"]
        if "not a git repository" in msg[0].lower():
            raise ValidacaoDominio("a pasta nao e um repositorio git")
        raise ValidacaoDominio(f"git falhou: {msg[0][:200]}")
    return r.stdout[:MAX_SAIDA]


def _ref(valor: str, nome: str) -> str:
    if valor and not _REF.match(valor):
        raise ValidacaoDominio(f"{nome} invalido (use um nome de branch, tag ou commit)")
    return valor


def _sem_segredos_no_diff(texto: str) -> tuple[str, int]:
    """Remove as secoes de arquivos com cara de segredo (o conteudo de um .env versionado nunca sai daqui)."""
    saida, pulando, removidos = [], False, 0
    for ln in texto.splitlines():
        m = _SECAO_DIFF.match(ln)
        if m:
            pulando = caminho_sensivel(m.group("a")) or caminho_sensivel(m.group("b"))
            removidos += int(pulando)
        if not pulando:
            saida.append(ln)
    return "\n".join(saida), removidos


def ler_git(raiz: Path, caminho: str = ".", operacao: str = "status", ref: str = "", ref2: str = "", arquivo: str = "",
            inicio: int = 1, fim: int = 0, limite: int = 20) -> ResultadoFerramenta:
    if operacao not in OPERACOES:
        raise ValidacaoDominio(f"operacao invalida (use {', '.join(OPERACOES)})")
    pasta = raiz.resolve() if caminho in ("", ".") else resolver_dentro(raiz, caminho, diretorio=True)
    ref, ref2 = _ref(ref, "ref"), _ref(ref2, "ref2")
    alvo_rel = ""
    if arquivo:
        real = resolver_dentro(raiz, arquivo)  # recusa segredo, fora da raiz e link simbolico
        alvo_rel = str(real)
    avisos: list[str] = []
    if operacao == "status":
        bruto = _git(["status", "--porcelain=v1", "-b", "--untracked-files=normal"], pasta)
        linhas = bruto.splitlines()
        ramo = linhas[0][3:] if linhas and linhas[0].startswith("##") else ""
        itens = [{"estado": ln[:2].strip() or "?", "arquivo": ln[3:]} for ln in linhas[1:] if ln.strip()]
        ocultos = sum(1 for i in itens if caminho_sensivel(i["arquivo"].split(" -> ")[-1]))
        itens = [i for i in itens if not caminho_sensivel(i["arquivo"].split(" -> ")[-1])]
        if ocultos:
            avisos.append(f"{ocultos} arquivo(s) de segredo omitidos")
        resumo = f"branch {ramo or '?'}; {len(itens)} arquivo(s) alterado(s)\n" + "\n".join(f"{i['estado']:>2} {i['arquivo']}" for i in itens[:200])
        return montar("git.ler", bruto, resumo, {"branch": ramo, "alterados": itens[:500]}, len(itens) > 200, avisos)
    if operacao == "log":
        n = max(1, min(int(limite), 100))
        args = ["log", f"-n{n}", "--date=short", "--pretty=format:%h%x09%ad%x09%an%x09%s", *([ref] if ref else [])]
        if alvo_rel:
            args += ["--", alvo_rel]
        bruto = _git(args, pasta)
        commits = [dict(zip(("commit", "data", "autor", "assunto"), ln.split("\t", 3), strict=False)) for ln in bruto.splitlines() if ln]
        resumo = "\n".join(f"{c.get('commit')} {c.get('data')} {c.get('assunto', '')[:120]}" for c in commits) or "nenhum commit"
        return montar("git.ler", bruto, resumo, {"commits": commits}, len(commits) >= n, avisos)
    if operacao == "branches":
        bruto = _git(["branch", "--list", "--format=%(HEAD)%09%(refname:short)%09%(committerdate:short)"], pasta)
        ramos = [dict(zip(("atual", "nome", "data"), ln.split("\t"), strict=False)) for ln in bruto.splitlines() if ln]
        resumo = "\n".join(f"{'*' if r.get('atual') == '*' else ' '} {r.get('nome')} ({r.get('data')})" for r in ramos[:100])
        return montar("git.ler", bruto, resumo, {"branches": ramos[:200]}, len(ramos) > 100, avisos)
    if operacao in ("diff", "show"):
        if operacao == "show":
            args = ["show", "--stat", "--format=%h %ad %an%n%s%n", "--date=short", ref or "HEAD"]
            bruto = _git(args, pasta)
            linhas = [ln for ln in bruto.splitlines() if not caminho_sensivel(ln.split("|")[0].strip())]
            return montar("git.ler", bruto, "\n".join(linhas)[:6000], {"ref": ref or "HEAD"}, len(bruto) > 6000, avisos)
        args = ["diff", "--no-ext-diff", "--no-textconv", "-U3", *([ref] if ref else []), *([ref2] if ref2 else [])]
        if alvo_rel:
            args += ["--", alvo_rel]
        bruto, removidos = _sem_segredos_no_diff(_git(args, pasta))
        if removidos:
            avisos.append(f"{removidos} arquivo(s) de segredo omitidos do diff")
        analise = resumir_diff(bruto) if bruto.strip() else None
        trecho = bruto[:MAX_DIFF_TEXTO]
        resumo = (analise.resumo if analise else "sem diferencas") + ("\n--- trecho do diff ---\n" + trecho if trecho else "")
        dados = {"analise": analise.dados if analise else {}, "truncado": len(bruto) > MAX_DIFF_TEXTO}
        return montar("git.ler", bruto, resumo, dados, len(bruto) > MAX_DIFF_TEXTO, avisos)
    # blame
    if not alvo_rel:
        raise ValidacaoDominio("blame exige 'arquivo'")
    ini = max(1, int(inicio))
    fim_ = int(fim) if int(fim) >= ini else ini + 40
    bruto = _git(["blame", "--date=short", "-L", f"{ini},{min(fim_, ini + 200)}", *([ref] if ref else []), "--", alvo_rel], pasta)
    resumo = "\n".join(ln[:200] for ln in bruto.splitlines())
    return montar("git.ler", bruto, resumo, {"arquivo": arquivo, "inicio": ini, "fim": fim_}, fim_ - ini > 200, avisos)
