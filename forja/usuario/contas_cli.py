"""Contas do painel pela linha de comando (no computador/conteiner do servidor, que ja e confiavel).

  python -m forja.usuario.contas_cli criar --usuario ana            (pede a senha sem mostrar)
  python -m forja.usuario.contas_cli redefinir --usuario ana        (esqueceu a senha: define outra e derruba as sessoes)
  python -m forja.usuario.contas_cli listar
  ... --senha-stdin                                                  (le a senha da entrada padrao: automacao)
A senha nunca vai para argumento de linha de comando (ficaria no historico e na lista de processos).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import delete


def _senha(stdin: bool) -> str:
    if stdin:
        return sys.stdin.readline().rstrip("\r\n")
    s1 = getpass.getpass("Senha: ")
    if getpass.getpass("Repita a senha: ") != s1:
        raise SystemExit("As senhas nao conferem.")
    return s1


def main(argv: list[str] | None = None) -> int:
    from forja.adapters.sqlite import tabelas as T
    from forja.adapters.sqlite.banco import criar_engines, migrar
    from forja.adapters.sqlite.repositorio import RepositorioSqlite
    from forja.config import obter_configuracoes
    from forja.dominio.erros import ErroDominio
    from forja.dominio.tempo import RelogioSistema, iso
    from forja.orquestracao.contas_servico import ContasServico
    from forja.seguranca import senhas

    ap = argparse.ArgumentParser(prog="python -m forja.usuario.contas_cli", description="Contas de acesso ao painel da Forja")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("criar", "redefinir"):
        p = sub.add_parser(nome)
        p.add_argument("--usuario", required=True)
        p.add_argument("--senha-stdin", action="store_true")
    sub.add_parser("listar")
    a = ap.parse_args(argv)
    cfg = obter_configuracoes()
    migrar(cfg.db_path)
    w, r = criar_engines(cfg.db_path)
    repo = RepositorioSqlite(w, r)
    try:
        contas = ContasServico(repo, cfg.app_session_ttl_minutes)
        if a.cmd == "listar":
            with repo.leitura() as t:
                for u in t.listar(T.Usuario, limite=1000):
                    print(f"{u['nome']}\tcriada {u['criado_em'][:10]}\tultimo acesso {(u['ultimo_acesso'] or '-')[:16]}")
            return 0
        senha = _senha(a.senha_stdin)
        if a.cmd == "criar":
            print(f"conta criada: {contas.criar(a.usuario, senha, 'linha_de_comando')['usuario']}")
            return 0
        nome = senhas.normalizar_nome(a.usuario)
        senhas.validar_senha(senha, nome)
        with repo.escrita() as t:
            achados = t.listar(T.Usuario, nome=nome, limite=1)
            if not achados:
                raise SystemExit("Conta nao encontrada.")
            u = achados[0]
            t.atualizar(T.Usuario, u["id"], senha_hash=senhas.gerar_hash(senha), falhas=0, bloqueado_ate=None,
                        atualizado_em=iso(RelogioSistema().agora()))
            t.s.execute(delete(T.Sessao).where(T.Sessao.usuario_id == u["id"]))
            t.emitir_evento("auth.senha_redefinida", iso(RelogioSistema().agora()), {"usuario_id": u["id"]})
        print(f"senha redefinida: {nome} (sessoes abertas encerradas)")
        return 0
    except ErroDominio as e:
        print(f"erro: {e.mensagem}", file=sys.stderr)
        return 2
    finally:
        repo.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
