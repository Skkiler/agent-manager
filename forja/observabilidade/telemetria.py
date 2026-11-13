"""Telemetria no padrao OpenTelemetry (convencoes semanticas gen_ai), sem dependencias externas.

Ao terminar uma execucao, os EVENTOS ja gravados dela viram um rastro OTLP/JSON:
- `invoke_agent forja` (raiz): agente, provedor, modelo pedido, tokens, estado final;
- `chat <modelo>`: um span por configuracao de modelo aplicada (turnos de planejamento/execucao);
- `execute_tool <tipo>`: chamadas de ferramenta do agente e os testes rodados pela Forja.
So metadados: nunca prompt, resposta, comandos completos ou segredos (os eventos ja sao sanitizados e aqui se usa so o
necessario). Destinos: arquivo JSONL na pasta de logs e/ou um coletor OTLP/HTTP em LOOPBACK (validado). Melhor esforco:
falhar aqui nunca altera a execucao.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.erros import ValidacaoDominio

log = logging.getLogger("forja.telemetria")
MODOS = ("desligada", "arquivo", "otlp_local")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_FIM = {"execucao.concluida", "execucao.falhou", "execucao.cancelada", "execucao.expirada", "execucao.bloqueada", "execucao.pausada"}


def validar_endpoint(url: str) -> str:
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or (p.hostname or "") not in _LOOPBACK:
        raise ValidacaoDominio("APP_OTEL_ENDPOINT deve apontar para o proprio computador (127.0.0.1, localhost ou ::1)")
    return url


def _nanos(ts: str) -> str:
    try:
        return str(int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1_000_000_000))
    except (ValueError, AttributeError):
        return "0"


def _attr(chave: str, valor: Any) -> dict[str, Any]:
    if isinstance(valor, bool):
        return {"key": chave, "value": {"boolValue": valor}}
    if isinstance(valor, int):
        return {"key": chave, "value": {"intValue": str(valor)}}
    if isinstance(valor, float):
        return {"key": chave, "value": {"doubleValue": valor}}
    return {"key": chave, "value": {"stringValue": str(valor)[:200]}}


def _span(trace: str, nome: str, ini: str, fim: str, attrs: dict[str, Any], pai: str = "", erro: bool = False, kind: int = 1) -> dict[str, Any]:
    s = {"traceId": trace, "spanId": secrets.token_hex(8), "name": nome[:120], "kind": kind,
         "startTimeUnixNano": _nanos(ini), "endTimeUnixNano": _nanos(fim),
         "attributes": [_attr(k, v) for k, v in attrs.items() if v is not None and v != ""],
         "status": {"code": 2 if erro else 1}}
    if pai:
        s["parentSpanId"] = pai
    return s


def montar_rastro(execucao: dict[str, Any], eventos: list[dict[str, Any]], servico: str = "forja") -> dict[str, Any]:
    """Execucao + eventos -> documento OTLP/JSON (ExportTraceServiceRequest)."""
    trace = hashlib.sha256(execucao["id"].encode()).hexdigest()[:32]
    if not eventos:
        eventos = [{"tipo": "execucao", "ts": execucao.get("criado_em") or "", "payload": {}}]
    ini, fim = eventos[0]["ts"], eventos[-1]["ts"]
    res = execucao.get("resultado") or {}
    consumo = res.get("consumo") or {}
    rota = next((e["payload"] for e in eventos if e["tipo"] == "kiro.rota"), {}) or {}
    configs = [e for e in eventos if e["tipo"] == "kiro.configuracao"]
    modelos = [((c["payload"] or {}).get("aplicados") or {}).get("modelo") for c in configs]
    raiz = _span(trace, "invoke_agent forja", ini, fim, {
        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": execucao.get("agente_id", ""), "gen_ai.agent.id": execucao["id"],
        "gen_ai.provider.name": "mock" if res.get("mock") else "kiro", "gen_ai.request.model": next((m for m in modelos if m), "padrao"),
        "gen_ai.usage.input_tokens": consumo.get("tokens_input"), "gen_ai.usage.output_tokens": consumo.get("tokens_output"),
        "forja.tarefa.id": execucao.get("tarefa_id", ""), "forja.execucao.estado": execucao.get("estado", ""),
        "forja.rota.nivel": rota.get("nivel"), "forja.chamadas_modelo": consumo.get("chamadas_modelo"),
    }, erro=execucao.get("estado") in ("falhou", "expirada"), kind=3)
    spans = [raiz]
    for i, c in enumerate(configs):
        p = c["payload"] or {}
        modelo = (p.get("aplicados") or {}).get("modelo") or "padrao"
        ate = configs[i + 1]["ts"] if i + 1 < len(configs) else fim
        spans.append(_span(trace, f"chat {modelo}", c["ts"], ate, {"gen_ai.operation.name": "chat", "gen_ai.request.model": modelo,
                                                                   "forja.parte": p.get("parte"), "gen_ai.request.effort": (p.get("aplicados") or {}).get("esforco")},
                           pai=raiz["spanId"], kind=3))
    abertas: dict[str, str] = {}
    for e in eventos:
        p = e["payload"] or {}
        if e["tipo"] == "kiro.ferramenta":
            chave = f"{p.get('tipo')}|{p.get('titulo')}"
            if p.get("status") in ("completed", "failed"):
                spans.append(_span(trace, f"execute_tool {p.get('tipo') or 'ferramenta'}", abertas.pop(chave, e["ts"]), e["ts"],
                                   {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": str(p.get("titulo") or "")[:80],
                                    "gen_ai.tool.type": p.get("tipo")}, pai=raiz["spanId"], erro=p.get("status") == "failed"))
            else:
                abertas.setdefault(chave, e["ts"])
        elif e["tipo"] == "kiro.testes_forja":
            spans.append(_span(trace, "execute_tool forja.testes", e["ts"], e["ts"], {
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "forja.testes", "forja.testes.ok": bool(p.get("ok")),
                "forja.testes.segundos": float(p.get("segundos") or 0)}, pai=raiz["spanId"], erro=not p.get("ok")))
    return {"resourceSpans": [{"resource": {"attributes": [_attr("service.name", servico), _attr("telemetry.sdk.name", "forja")]},
                               "scopeSpans": [{"scope": {"name": "forja.orquestrador"}, "spans": spans}]}]}


def _post(url: str, corpo: bytes, timeout: float = 3.0) -> None:
    req = urllib.request.Request(url, data=corpo, method="POST", headers={"Content-Type": "application/json"})  # noqa: S310 - loopback validado
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        r.read(0)


class Telemetria:
    def __init__(self, repo: RepositorioSqlite, dir_logs: Path, endpoint: str, enviar: Callable[[str, bytes], None] | None = None) -> None:
        self.repo = repo
        self.dir = dir_logs / "telemetria"
        self.endpoint = endpoint
        self.modo = "desligada"
        self._enviar = enviar or _post

    def definir_modo(self, modo: Any) -> None:
        self.modo = str(modo) if str(modo) in MODOS else "desligada"

    def ao_finalizar(self, execucao_id: str, _res: Any = None) -> None:
        if self.modo == "desligada":
            return
        try:
            with self.repo.leitura() as t:
                ex = t.obter(T.Execucao, execucao_id)
                eventos = t.eventos_da_execucao(execucao_id)
            if ex is None:
                return
            doc = montar_rastro(ex, eventos)
            linha = json.dumps(doc, ensure_ascii=False)
            self.dir.mkdir(parents=True, exist_ok=True)
            with (self.dir / f"rastros-{(ex.get('criado_em') or '')[:10] or 'sem-data'}.jsonl").open("a", encoding="utf-8") as f:
                f.write(linha + "\n")
            if self.modo == "otlp_local":
                url = validar_endpoint(self.endpoint)
                threading.Thread(target=self._enviar_seguro, args=(url, linha.encode("utf-8")), daemon=True, name="forja-otlp").start()
        except Exception as e:  # noqa: BLE001 - telemetria nunca derruba nada
            log.warning("telemetria falhou: %s", type(e).__name__)

    def _enviar_seguro(self, url: str, corpo: bytes) -> None:
        try:
            self._enviar(url, corpo)
        except Exception as e:  # noqa: BLE001 - coletor fora do ar nao e erro da Forja
            log.info("coletor OTLP indisponivel: %s", type(e).__name__)
