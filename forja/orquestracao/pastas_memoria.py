"""Pastas do segundo cerebro (ADR-029): o usuario organiza as notas em pastas (namespaces hierarquicos), como num cofre do Obsidian.

  * Pasta = namespace (`pessoal/empresa/<id>/projetos/<projeto>`). Uma pasta vazia fica registrada em `configuracao`
    (`memoria_pastas`) ate receber notas.
  * O USUARIO cria, renomeia (migra tudo o que esta dentro, inclusive subpastas e o indice de codigo), move notas e remove pasta
    vazia. Vale em `pessoal` e em `publico`; a base da Forja (`publico/forja-base`) continua somente leitura.
  * O AGENTE so PROPOE (`propor`): a proposta vira uma sugestao na fila de Revisao e so e aplicada quando o usuario aceita.
  * Mover nao muda o conteudo: guarda uma versao (motivo + ator), reindexa a busca e recalcula o escopo das ligacoes (a ligacao
    fica no escopo mais privado das duas pontas, como em `GrafoServico.ligar`).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text, update

from forja.adapters.sqlite import memoria_fts as fts
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.modelo import (
    RAIZES_NS,
    AcessoNegado,
    Principal,
    eh_base,
    namespace_dentro_de,
    sensibilidade_de,
    validar_namespace,
)

log = logging.getLogger("forja.pastas")
CHAVE = "memoria_pastas"
MAX_MOVER = 500
INATIVOS = ("revogado", "substituido")
ACOES_PROPOSTA = ("criar", "mover", "renomear")


def _trocar_prefixo(ns: str, origem: str, destino: str) -> str:
    return destino + ns[len(origem):]


def _escopo_ligacao(a: str, b: str) -> str:
    """Mesmo criterio de GrafoServico.ligar: a ligacao fica no namespace mais privado das pontas."""
    return b if a == "publico" or a.startswith("publico/") else a


class PastasMemoria:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()

    def _ts(self) -> str:
        return iso(self.relogio.agora())

    # ------------------------------------------------------------------ registro das pastas declaradas
    def _declaradas(self, t: Any) -> dict[str, dict[str, Any]]:
        linha = t.obter(T.Configuracao, CHAVE)
        return dict(((linha or {}).get("valor") or {}).get("pastas") or {})

    def _gravar(self, t: Any, pastas: dict[str, dict[str, Any]]) -> None:
        linha = t.obter(T.Configuracao, CHAVE)
        valor = {"pastas": dict(sorted(pastas.items()))}
        if linha is None:
            t.inserir(T.Configuracao, id=CHAVE, valor=valor, versao=1, atualizado_em=self._ts())
        else:
            t.atualizar(T.Configuracao, CHAVE, valor=valor, versao=linha["versao"] + 1, atualizado_em=self._ts())

    @staticmethod
    def _validar_destino(p: Principal, ns: str) -> str:
        validar_namespace(ns)
        p.exigir(ns)
        if eh_base(ns):
            raise AcessoNegado("A base da Forja (publico/forja-base) e somente leitura.")
        return ns

    # ------------------------------------------------------------------ leitura
    def arvore(self, p: Principal) -> dict[str, Any]:
        """Pastas visiveis com quantas notas (ativas) e arquivos de codigo indexados ha em cada uma e no total da subarvore."""
        with self.repo.leitura() as t:
            notas = dict(t.s.execute(select(T.Memoria.namespace, func.count()).where(T.Memoria.estado.not_in(INATIVOS))
                                     .group_by(T.Memoria.namespace)).all())
            arquivos = dict(t.s.execute(select(T.ArquivoIndexado.namespace, func.count()).where(T.ArquivoIndexado.estado == "ativo")
                                        .group_by(T.ArquivoIndexado.namespace)).all())
            declaradas = self._declaradas(t)
        nomes: set[str] = set()
        for ns in [*notas, *arquivos, *declaradas]:
            if not p.pode(ns):
                continue
            partes = ns.split("/")
            nomes.update("/".join(partes[:i]) for i in range(1, len(partes) + 1))
        nomes = {n for n in nomes if p.pode(n) or n in RAIZES_NS}
        saida = []
        for ns in sorted(nomes):
            dentro = [k for k in notas if namespace_dentro_de(k, ns) and p.pode(k)]
            saida.append({"namespace": ns, "nome": ns.rsplit("/", 1)[-1], "nivel": ns.count("/"),
                          "notas": int(notas.get(ns, 0)), "total": int(sum(notas[k] for k in dentro)),
                          "arquivos": int(sum(v for k, v in arquivos.items() if namespace_dentro_de(k, ns) and p.pode(k))),
                          "declarada": ns in declaradas, "descricao": (declaradas.get(ns) or {}).get("descricao", ""),
                          "somente_leitura": eh_base(ns) or ns in RAIZES_NS})
        return {"pastas": saida}

    def notas(self, p: Principal, namespace: str, subpastas: bool = False, limite: int = 500) -> dict[str, Any]:
        """Notas ativas de UMA pasta (ou da subarvore), so com o necessario para listar e escolher o que mover."""
        validar_namespace(namespace)
        p.exigir(namespace)
        filtro = T.Memoria.namespace == namespace
        if subpastas:
            filtro = filtro | T.Memoria.namespace.startswith(namespace + "/")
        with self.repo.leitura() as t:
            linhas = t.s.execute(select(T.Memoria.id, T.Memoria.titulo, T.Memoria.tipo, T.Memoria.estado, T.Memoria.namespace,
                                        T.Memoria.tags, T.Memoria.atualizado_em)
                                 .where(filtro, T.Memoria.estado.not_in(INATIVOS)).order_by(T.Memoria.titulo).limit(limite)).all()
        return {"namespace": namespace, "notas": [dict(r._mapping) for r in linhas if p.pode(r.namespace)]}

    # ------------------------------------------------------------------ operacoes do usuario
    def criar(self, p: Principal, namespace: str, descricao: str = "", ator: str = "operador") -> dict[str, Any]:
        ns = self._validar_destino(p, namespace)
        if ns in RAIZES_NS:
            raise ValidacaoDominio("Essa raiz ja existe; crie uma subpasta (ex.: pessoal/empresa/minha-empresa).")
        with self.repo.escrita() as t:
            pastas = self._declaradas(t)
            pastas[ns] = {"descricao": (descricao or "").strip()[:300], "criada_em": self._ts(), "criada_por": ator[:100]}
            self._gravar(t, pastas)
            t.emitir_evento("memoria.pasta_criada", self._ts(), {"nivel": ns.count("/"), "ator": ator[:60]})
        return {"namespace": ns, **pastas[ns]}

    def remover(self, p: Principal, namespace: str) -> None:
        ns = self._validar_destino(p, namespace)
        with self.repo.escrita() as t:
            ocupada = t.s.execute(select(func.count()).select_from(T.Memoria).where(
                (T.Memoria.namespace == ns) | T.Memoria.namespace.startswith(ns + "/"), T.Memoria.estado.not_in(INATIVOS))).scalar()
            if ocupada:
                raise Conflito(f"A pasta tem {ocupada} nota(s): mova ou renomeie antes de remover.")
            pastas = self._declaradas(t)
            if ns not in pastas:
                raise NaoEncontrado("Pasta nao encontrada.")
            pastas.pop(ns)
            self._gravar(t, pastas)

    def _mover_nota(self, t: Any, p: Principal, m: dict[str, Any], destino: str, ator: str, motivo: str) -> bool:
        if m["namespace"] == destino:
            return False
        t.inserir(T.MemoriaVersao, memoria_id=m["id"], versao=m["versao"], titulo=m["titulo"], resumo=m["resumo"],
                  conteudo=m["conteudo"], estado=m["estado"], motivo=f"movida de {m['namespace']} para {destino}. {motivo}"[:1000],
                  ator=ator[:100], criado_em=self._ts())
        t.s.execute(update(T.Memoria).where(T.Memoria.id == m["id"]).values(
            namespace=destino, sensibilidade=sensibilidade_de(destino), versao=m["versao"] + 1, atualizado_em=self._ts()))
        nova = t.obter(T.Memoria, m["id"])
        fts.memoria_indexar(t, nova)
        for lg in [*t.listar(T.LigacaoGrafo, origem=m["id"], limite=2000), *t.listar(T.LigacaoGrafo, destino=m["id"], limite=2000)]:
            outra = lg["destino"] if lg["origem"] == m["id"] else lg["origem"]
            o = t.obter(T.Memoria, outra) or t.obter(T.NoConhecimento, outra)
            ns_outra = o["namespace"] if o else destino
            novo = _escopo_ligacao(destino, ns_outra) if lg["origem"] == m["id"] else _escopo_ligacao(ns_outra, destino)
            if novo != lg["namespace"]:
                t.atualizar(T.LigacaoGrafo, lg["id"], namespace=novo)
        return True

    def mover(self, p: Principal, ids: list[str], destino: str, ator: str = "operador", motivo: str = "") -> dict[str, Any]:
        """Move notas para a pasta `destino` (cria o registro da pasta se preciso). Base da Forja nunca e movida."""
        destino = self._validar_destino(p, destino)
        if not ids or len(ids) > MAX_MOVER:
            raise ValidacaoDominio(f"informe de 1 a {MAX_MOVER} notas")
        movidas, puladas = 0, []
        with self.repo.escrita() as t:
            for mid in dict.fromkeys(ids):
                m = t.obter(T.Memoria, mid)
                if m is None or not p.pode(m["namespace"]):
                    puladas.append({"id": mid, "motivo": "nao encontrada"})
                    continue
                if eh_base(m["namespace"]):
                    puladas.append({"id": mid, "motivo": "base da Forja e somente leitura"})
                    continue
                movidas += self._mover_nota(t, p, m, destino, ator, motivo)
            t.emitir_evento("memoria.notas_movidas", self._ts(), {"movidas": movidas, "puladas": len(puladas), "ator": ator[:60]})
        return {"destino": destino, "movidas": movidas, "puladas": puladas}

    def renomear(self, p: Principal, origem: str, destino: str, ator: str = "operador") -> dict[str, Any]:
        """Migra a pasta inteira (subpastas, notas, indice de codigo e pastas declaradas) para outro caminho."""
        origem = self._validar_destino(p, origem)
        destino = self._validar_destino(p, destino)
        if origem in RAIZES_NS:
            raise ValidacaoDominio("As raizes (publico, pessoal, terceiros) nao podem ser renomeadas.")
        if namespace_dentro_de(destino, origem):
            raise ValidacaoDominio("O destino nao pode ficar dentro da propria pasta.")
        res = {"origem": origem, "destino": destino, "notas": 0, "arquivos": 0, "pastas": 0}
        with self.repo.escrita() as t:
            dentro = (T.Memoria.namespace == origem) | T.Memoria.namespace.startswith(origem + "/")
            for m in [dict(r._mapping) for r in t.s.execute(select(T.Memoria.__table__).where(dentro)).all()]:
                novo = _trocar_prefixo(m["namespace"], origem, destino)
                validar_namespace(novo)  # profundidade maxima
                res["notas"] += self._mover_nota(t, p, m, novo, ator, f"pasta renomeada ({origem} -> {destino})")
            arqs = t.s.execute(select(T.ArquivoIndexado.namespace).where(
                (T.ArquivoIndexado.namespace == origem) | T.ArquivoIndexado.namespace.startswith(origem + "/")).distinct()).scalars().all()
            for ns in arqs:
                novo = _trocar_prefixo(ns, origem, destino)
                n = t.s.execute(update(T.ArquivoIndexado).where(T.ArquivoIndexado.namespace == ns).values(namespace=novo)).rowcount
                t.s.execute(text("UPDATE codigo_fts SET namespace = :n WHERE namespace = :v"), {"n": novo, "v": ns})
                res["arquivos"] += int(n or 0)
            pastas = self._declaradas(t)
            for ns in [k for k in pastas if namespace_dentro_de(k, origem)]:
                pastas[_trocar_prefixo(ns, origem, destino)] = pastas.pop(ns)
                res["pastas"] += 1
            if destino not in pastas:
                pastas[destino] = {"descricao": "", "criada_em": self._ts(), "criada_por": ator[:100]}
            self._gravar(t, pastas)
            t.emitir_evento("memoria.pasta_renomeada", self._ts(), {k: v for k, v in res.items() if isinstance(v, int)})
        return res

    # ------------------------------------------------------------------ agentes: so propoem (fila de revisao)
    def propor(self, p: Principal, acao: str, dados: dict[str, Any], motivo: str, ator: str = "agente") -> dict[str, Any]:
        """O agente pede para criar/renomear pasta ou mover notas. Vira sugestao 'pasta' pendente; nada muda sem o usuario."""
        if acao not in ACOES_PROPOSTA:
            raise ValidacaoDominio(f"acao deve ser uma de {ACOES_PROPOSTA}")
        destino = self._validar_destino(p, str(dados.get("destino") or ""))
        ids: list[str] = [str(i)[:64] for i in (dados.get("ids") or [])][:MAX_MOVER]
        origem = str(dados.get("origem") or "")
        if acao == "mover" and not ids:
            raise ValidacaoDominio("mover exige 'ids' das notas")
        if acao == "renomear":
            self._validar_destino(p, origem)
        with self.repo.leitura() as t:
            visiveis = [i for i in ids if (m := t.obter(T.Memoria, i)) and p.pode(m["namespace"]) and not eh_base(m["namespace"])]
        if acao == "mover" and not visiveis:
            raise NaoEncontrado("Nenhuma das notas foi encontrada.")
        chave = f"pasta:{acao}:{origem}:{destino}:{','.join(sorted(visiveis))}"[:200]
        with self.repo.escrita() as t:
            ja = t.listar(T.SugestaoMemoria, chave=chave, limite=1)  # chave unica: a mesma proposta nao volta depois de decidida
            if ja:
                return {"criada": False, "sugestao_id": ja[0]["id"], "estado": ja[0]["estado"]}
            s = t.inserir(T.SugestaoMemoria, id=novo_id("SUG"), tipo="pasta", memorias=visiveis, namespace=destino,
                          motivo=(motivo or f"{acao} pasta")[:500], chave=chave, estado="pendente", criado_em=self._ts(),
                          dados={"acao": acao, "destino": destino, "origem": origem, "ids": visiveis,
                                 "descricao": str(dados.get("descricao") or "")[:300], "proposto_por": ator[:100]})
            t.emitir_evento("memoria.pasta_proposta", self._ts(), {"sugestao_id": s["id"], "acao": acao})
        return {"criada": True, "sugestao_id": s["id"]}

    def aplicar(self, p: Principal, s: dict[str, Any], ator: str) -> dict[str, Any]:
        d = s["dados"] or {}
        if d.get("acao") == "criar":
            return self.criar(p, d["destino"], d.get("descricao", ""), ator)
        if d.get("acao") == "renomear":
            return self.renomear(p, d["origem"], d["destino"], ator)
        if d.get("acao") == "mover":
            return self.mover(p, list(d.get("ids") or s["memorias"]), d["destino"], ator, f"proposta de {d.get('proposto_por', 'agente')}")
        raise ValidacaoDominio("proposta de pasta invalida")
