"""Projetos com pastas (estilo Codex): o usuario designa as pastas de cada projeto e o papel de cada uma.

  * `trabalho`: o agente trabalha nela (diretorio da sessao do Kiro). Le/altera conforme o NIVEL DE AUTONOMIA.
  * `consulta`: pode ser util; o agente so LE (no liberado/total, leituras ali dispensam pergunta). Nunca altera.
Regras que valem sempre: pastas protegidas (perfil da Forja, `.git`) e pastas PROIBIDAS da tela nao podem entrar; o explorador e
os anexos nunca mostram arquivo sensivel (.env, chaves...) nem saem das pastas do projeto (sem links, sem `..`).

Anexos: arquivo de uma pasta do projeto, ou ENVIADO pelo usuario de qualquer lugar (so aquele conteudo fica visivel, nunca a pasta).
O texto anexado e redigido (segredos mascarados), limitado e marcado como dado nao confiavel no prompt.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.indexador import IGNORAR_DIRS
from forja.observabilidade.sanitizar import redigir_segredos
from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import protegido, validar_pasta

PAPEIS = ("trabalho", "consulta")
MAX_PASTAS = 20
MAX_ANEXOS = 12
MAX_BYTES_ANEXO = 2_000_000
MAX_TEXTO_ANEXO = 20_000
MAX_LISTAGEM = 400
MAX_BUSCA = 50
IMAGENS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_BYTES_IMAGEM = 1_500_000


def _ignorar(nome: str) -> bool:
    return nome in IGNORAR_DIRS or nome.endswith(".egg-info") or nome.startswith(".") and nome not in (".github", ".kiro")


def _texto_de(dados: bytes) -> str | None:
    """Conteudo textual ou None se parecer binario."""
    if b"\x00" in dados[:8000]:
        return None
    for cod in ("utf-8", "utf-16"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1")


class ProjetosServico:
    def __init__(self, repo: RepositorioSqlite, artefatos_dir: Path, politica: Any = None, relogio: Relogio | None = None) -> None:
        self.repo, self.artefatos_dir = repo, artefatos_dir
        self.politica = politica  # () -> PoliticaPastas (preferencias): pastas proibidas valem aqui tambem
        self.relogio = relogio or RelogioSistema()

    def _agora(self) -> str:
        return iso(self.relogio.agora())

    # ------------------------------------------------------------------ pastas do projeto
    def _proibida(self, p: Path) -> bool:
        pol = self.politica() if self.politica else None
        if pol is None:
            return False
        r = p.resolve()
        return any(r == b.resolve() or b.resolve() in r.parents for b in pol.proibidas)

    def validar_pastas(self, pastas: Any) -> list[dict[str, str]]:
        if not isinstance(pastas, list) or len(pastas) > MAX_PASTAS:
            raise ValidacaoDominio(f"informe ate {MAX_PASTAS} pastas")
        saida: dict[str, dict[str, str]] = {}
        for item in pastas:
            if not isinstance(item, dict) or item.get("papel") not in PAPEIS:
                raise ValidacaoDominio("cada pasta precisa de caminho e papel (trabalho ou consulta)")
            p = validar_pasta(str(item.get("caminho", "")), "Pasta do projeto", deve_existir=True)
            if self._proibida(p):
                raise ValidacaoDominio(f"{p} esta nas pastas proibidas (Configuracoes > Privacidade)")
            atual = saida.get(str(p))
            papel = "trabalho" if "trabalho" in (item["papel"], (atual or {}).get("papel")) else "consulta"  # repetida: vale a mais ampla
            saida[str(p)] = {"caminho": str(p), "papel": papel}
        return list(saida.values())

    def obter(self, projeto_id: str) -> dict[str, Any]:
        with self.repo.leitura() as t:
            p = t.obter(T.Projeto, projeto_id)
        if p is None:
            raise NaoEncontrado(f"Projeto {projeto_id} nao encontrado.")
        return p

    def definir_pastas(self, projeto_id: str, pastas: Any, expected_version: int, ator: str = "operador") -> dict[str, Any]:
        validadas = self.validar_pastas(pastas)
        with self.repo.escrita() as t:
            p = t.obter(T.Projeto, projeto_id)
            if p is None:
                raise NaoEncontrado(f"Projeto {projeto_id} nao encontrado.")
            if p["versao"] != expected_version:
                raise ConflitoVersao(f"O projeto mudou (versao {p['versao']}); recarregue.")
            t.atualizar(T.Projeto, projeto_id, pastas=validadas, versao=p["versao"] + 1)
            t.emitir_evento("projeto.pastas_definidas", self._agora(),  # so contagens: caminhos podem ser pessoais
                            {"projeto_id": projeto_id, "trabalho": sum(x["papel"] == "trabalho" for x in validadas),
                             "consulta": sum(x["papel"] == "consulta" for x in validadas), "ator": ator[:60]})
        return self.obter(projeto_id)

    def pastas_validas(self, projeto: dict[str, Any]) -> list[dict[str, str]]:
        """Pastas do projeto que AINDA sao validas (uma pasta pode ter sido apagada ou proibida depois)."""
        boas = []
        for x in projeto.get("pastas") or []:
            p = Path(x["caminho"])
            if p.is_dir() and not protegido(p) and not self._proibida(p):
                boas.append(x)
        return boas

    def projeto_da_tarefa(self, tarefa: dict[str, Any]) -> dict[str, Any] | None:
        with self.repo.leitura() as t:
            o = t.obter(T.Objetivo, tarefa["objetivo_id"])
            return t.obter(T.Projeto, o["projeto_id"]) if o else None

    # ------------------------------------------------------------------ explorador e busca (@mencao)
    def _resolver(self, projeto: dict[str, Any], raiz_idx: int, rel: str = "") -> tuple[Path, Path]:
        pastas = self.pastas_validas(projeto)
        if not 0 <= raiz_idx < len(pastas):
            raise NaoEncontrado("pasta do projeto nao encontrada")
        base = Path(pastas[raiz_idx]["caminho"]).resolve()
        alvo = (base / (rel or "")).resolve()
        if alvo != base and base not in alvo.parents:
            raise ValidacaoDominio("caminho fora da pasta do projeto")
        partes = alvo.relative_to(base).parts
        pastas_no_caminho = partes if alvo.is_dir() else partes[:-1]  # arquivo: o nome pode comecar com '.' (ex.: .gitignore)
        if protegido(alvo) or self._proibida(alvo) or any(_ignorar(parte) for parte in pastas_no_caminho):
            raise ValidacaoDominio("caminho nao permitido")
        return base, alvo

    def listar(self, projeto_id: str, raiz_idx: int = 0, rel: str = "") -> dict[str, Any]:
        projeto = self.obter(projeto_id)
        base, alvo = self._resolver(projeto, raiz_idx, rel)
        if not alvo.is_dir():
            raise ValidacaoDominio("nao e uma pasta")
        itens = []
        with os.scandir(alvo) as it:
            for e in sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold())):
                if e.is_symlink() or _ignorar(e.name) or caminho_sensivel(e.name):
                    continue
                p = Path(e.path)
                if protegido(p) or self._proibida(p):
                    continue
                d = e.is_dir(follow_symlinks=False)
                itens.append({"nome": e.name, "rel": p.relative_to(base).as_posix(), "pasta": d,
                              "tamanho": None if d else e.stat(follow_symlinks=False).st_size})
                if len(itens) >= MAX_LISTAGEM:
                    break
        return {"raiz": raiz_idx, "rel": alvo.relative_to(base).as_posix() if alvo != base else "", "itens": itens,
                "truncado": len(itens) >= MAX_LISTAGEM}

    def buscar_arquivos(self, projeto_id: str, termo: str, limite: int = 20) -> list[dict[str, Any]]:
        """Busca por nome (para @mencao): todas as pastas do projeto, sem seguir links nem entrar em pastas ignoradas."""
        termo = (termo or "").strip().casefold()
        if not termo or len(termo) > 100:
            raise ValidacaoDominio("informe parte do nome do arquivo")
        projeto = self.obter(projeto_id)
        achados: list[dict[str, Any]] = []
        for idx, pasta in enumerate(self.pastas_validas(projeto)):
            base = Path(pasta["caminho"]).resolve()
            for atual, dirs, arquivos in os.walk(base, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not _ignorar(d) and not protegido(Path(atual) / d) and not self._proibida(Path(atual) / d))
                for nome in arquivos:
                    if termo in nome.casefold() and not caminho_sensivel(nome) and not Path(atual, nome).is_symlink():
                        rel = Path(atual, nome).relative_to(base).as_posix()
                        achados.append({"raiz": idx, "papel": pasta["papel"], "rel": rel, "nome": nome,
                                        "pontos": (nome.casefold() != termo, nome.casefold().find(termo), len(rel))})
                if len(achados) >= MAX_BUSCA * 4:
                    break
        achados.sort(key=lambda a: a["pontos"])
        return [{k: v for k, v in a.items() if k != "pontos"} for a in achados[:min(limite, MAX_BUSCA)]]

    # ------------------------------------------------------------------ anexos
    def _tarefa(self, t: Any, tarefa_id: str) -> dict[str, Any]:
        tarefa = t.obter(T.Tarefa, tarefa_id)
        if tarefa is None:
            raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
        return tarefa

    def _guardar(self, tarefa_id: str, nome: str, origem: str, caminho: str | None, dados: bytes, mime: str) -> dict[str, Any]:
        if caminho_sensivel(nome):
            raise ValidacaoDominio("arquivos de segredo/credencial (.env, chaves, tokens) nunca sao anexados")
        if len(dados) > MAX_BYTES_ANEXO:
            raise ValidacaoDominio(f"anexo acima de {MAX_BYTES_ANEXO // 1_000_000} MB")
        sufixo = Path(nome).suffix.lower()
        sha = hashlib.sha256(dados).hexdigest()
        if sufixo in IMAGENS:
            if len(dados) > MAX_BYTES_IMAGEM:
                raise ValidacaoDominio(f"imagem acima de {MAX_BYTES_IMAGEM // 1000} KB")
            mime, texto, truncado = IMAGENS[sufixo], "", False
            destino = self.artefatos_dir / "anexos" / sha
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not destino.exists():
                destino.write_bytes(dados)
        else:
            bruto = _texto_de(dados)
            if bruto is None:
                raise ValidacaoDominio("so texto (codigo, logs, csv, md...) e imagens podem ser anexados")
            texto = redigir_segredos(bruto)
            truncado = len(texto) > MAX_TEXTO_ANEXO
            texto, mime = texto[:MAX_TEXTO_ANEXO], (mime if mime.startswith("text/") else "text/plain")
        with self.repo.escrita() as t:
            self._tarefa(t, tarefa_id)
            if len(t.listar(T.Anexo, tarefa_id=tarefa_id, limite=MAX_ANEXOS + 1)) >= MAX_ANEXOS:
                raise ValidacaoDominio(f"no maximo {MAX_ANEXOS} anexos por tarefa")
            a = t.inserir(T.Anexo, id=novo_id("ANX"), tarefa_id=tarefa_id, nome=nome[:200], origem=origem, caminho=caminho,
                          mime=mime, tamanho=len(dados), sha256=sha, texto=texto, truncado=truncado, criado_em=self._agora())
            t.emitir_evento("tarefa.anexo_adicionado", self._agora(), {"anexo_id": a["id"], "origem": origem}, tarefa_id=tarefa_id)
        return self._publico(a)

    @staticmethod
    def _publico(a: dict[str, Any]) -> dict[str, Any]:
        return {k: a[k] for k in ("id", "tarefa_id", "nome", "origem", "caminho", "mime", "tamanho", "truncado", "criado_em")}

    def anexar_do_projeto(self, tarefa_id: str, raiz_idx: int, rel: str) -> dict[str, Any]:
        with self.repo.leitura() as t:
            tarefa = self._tarefa(t, tarefa_id)
        projeto = self.projeto_da_tarefa(tarefa)
        if projeto is None:
            raise NaoEncontrado("projeto da tarefa nao encontrado")
        base, alvo = self._resolver(projeto, raiz_idx, rel)
        if not alvo.is_file() or alvo.is_symlink() or caminho_sensivel(alvo.name):
            raise ValidacaoDominio("arquivo nao encontrado ou nao permitido")
        pasta = self.pastas_validas(projeto)[raiz_idx]
        return self._guardar(tarefa_id, alvo.name, "projeto", f"{Path(pasta['caminho']).name}/{alvo.relative_to(base).as_posix()}"[:500],
                             alvo.read_bytes(), "text/plain")

    def anexar_envio(self, tarefa_id: str, nome: str, conteudo_b64: str, mime: str = "") -> dict[str, Any]:
        nome = Path(str(nome or "")).name.strip()  # so o nome: o caminho de origem nunca e guardado
        if not nome:
            raise ValidacaoDominio("informe o nome do arquivo")
        try:
            dados = base64.b64decode(conteudo_b64, validate=True)
        except (ValueError, TypeError) as e:
            raise ValidacaoDominio("conteudo do anexo invalido") from e
        return self._guardar(tarefa_id, nome, "envio", None, dados, mime or "")

    def anexos(self, tarefa_id: str) -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            return [self._publico(a) for a in t.listar(T.Anexo, tarefa_id=tarefa_id, limite=MAX_ANEXOS)]

    def remover_anexo(self, tarefa_id: str, anexo_id: str) -> None:
        with self.repo.escrita() as t:
            a = t.obter(T.Anexo, anexo_id)
            if a is None or a["tarefa_id"] != tarefa_id:
                raise NaoEncontrado("anexo nao encontrado")
            t.s.delete(t.s.get(T.Anexo, anexo_id))
            t.emitir_evento("tarefa.anexo_removido", self._agora(), {"anexo_id": anexo_id}, tarefa_id=tarefa_id)

    def para_execucao(self, tarefa: dict[str, Any]) -> dict[str, Any]:
        """O que o provedor recebe: pastas validas do projeto e anexos (texto redigido; imagens em base64)."""
        projeto = self.projeto_da_tarefa(tarefa)
        pastas = self.pastas_validas(projeto) if projeto else []
        with self.repo.leitura() as t:
            anexos = t.listar(T.Anexo, tarefa_id=tarefa["id"], limite=MAX_ANEXOS)
        saida = []
        for a in anexos:
            item = {"nome": a["nome"], "origem": a["origem"], "caminho": a["caminho"], "mime": a["mime"], "texto": a["texto"], "truncado": a["truncado"]}
            if a["mime"].startswith("image/"):
                arq = self.artefatos_dir / "anexos" / a["sha256"]
                if not arq.is_file():
                    continue
                item["dados_b64"] = base64.b64encode(arq.read_bytes()).decode()
            saida.append(item)
        return {"pastas": pastas, "anexos": saida, "projeto": projeto["nome"] if projeto else None}
