"""Isolamento (melhor esforco) dos testes que a Forja roda no projeto.

Rodar testes executa codigo do projeto. Alem do ambiente limpo (sem segredos), aqui se limita o ESTRAGO possivel:
- arvore de processos inteira presa a um grupo: no Windows um Job Object (fecha = mata todos, teto de memoria e de
  processos); no Linux/macOS um grupo de processos proprio (tempo esgotado mata o grupo) e teto de memoria (Linux);
- pasta temporaria propria (TMP/TEMP), apagada no fim;
- modo 'estrito': tambem HOME/USERPROFILE/APPDATA apontam para a caixa de areia e a rede via proxy e cortada (proxy
  inexistente em 127.0.0.1:9). Pacotes instalados no usuario continuam visiveis (PYTHONUSERBASE preservado).
NAO e uma sandbox de seguranca contra codigo malicioso (sem contêiner/VM): e protecao contra efeitos colaterais comuns
(testes que escrevem no HOME, abrem rede, criam processos orfaos ou estouram memoria).
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import site
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("forja.sandbox")
MODOS = ("basico", "estrito")
PROXY_MORTO = "http://127.0.0.1:9"


@dataclass(frozen=True)
class Limites:
    memoria_mb: int = 6144
    max_processos: int = 128


@dataclass
class Saida:
    texto: str
    codigo: int | None
    esgotado: bool
    isolamento: dict


def preparar_ambiente(env: dict[str, str], modo: str, caixa: Path) -> dict[str, str]:
    """Ambiente do processo de testes dentro da caixa de areia. Nao altera `env` de entrada."""
    novo = dict(env)
    tmp = caixa / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for k in ("TMP", "TEMP", "TMPDIR"):
        novo[k] = str(tmp)
    if modo == "estrito":
        casa = caixa / "home"
        for sub in ("", "AppData/Roaming", "AppData/Local", ".config", ".cache"):
            (casa / sub).mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):  # site pode estar desligado (python -S)
            novo.setdefault("PYTHONUSERBASE", site.getuserbase())  # o projeto continua achando pacotes instalados no usuario
        novo.update({"HOME": str(casa), "USERPROFILE": str(casa), "APPDATA": str(casa / "AppData/Roaming"),
                     "LOCALAPPDATA": str(casa / "AppData/Local"), "XDG_CONFIG_HOME": str(casa / ".config"),
                     "XDG_CACHE_HOME": str(casa / ".cache")})
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            novo[k] = PROXY_MORTO
        for k in ("NO_PROXY", "no_proxy"):
            novo.pop(k, None)
        novo["PIP_NO_INDEX"] = "1"
    return novo


# ------------------------------------------------------------------ Windows: Job Object
class _JobWindows:
    def __init__(self, limites: Limites) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32 = k32

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Basica(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Estendida(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basica), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.h = k32.CreateJobObjectW(None, None)
        if not self.h:
            raise OSError("CreateJobObjectW falhou")
        info = Estendida()
        # KILL_ON_JOB_CLOSE (0x2000) | JOB_MEMORY (0x200) | ACTIVE_PROCESS (0x8)
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x200 | 0x8
        info.BasicLimitInformation.ActiveProcessLimit = limites.max_processos
        info.JobMemoryLimit = limites.memoria_mb * 1024 * 1024
        if not k32.SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.fechar()
            raise OSError("SetInformationJobObject falhou")

    def anexar(self, proc: subprocess.Popen) -> None:
        if not self.k32.AssignProcessToJobObject(self.h, int(proc._handle)):  # type: ignore[attr-defined]
            raise OSError("AssignProcessToJobObject falhou")

    def matar(self) -> None:
        if self.h:
            self.k32.TerminateJobObject(self.h, 1)

    def fechar(self) -> None:
        if self.h:
            self.k32.CloseHandle(self.h)  # KILL_ON_JOB_CLOSE: nenhum processo do teste sobrevive
            self.h = None


def _limitar_memoria_linux(pid: int, limites: Limites) -> bool:
    try:
        import resource

        teto = limites.memoria_mb * 1024 * 1024
        resource.prlimit(pid, resource.RLIMIT_AS, (teto, teto))  # type: ignore[attr-defined]
        return True
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def executar(args: list[str], cwd: Path, env: dict[str, str], timeout: float, modo: str = "basico",
             limites: Limites | None = None) -> Saida:
    """Roda `args` (lista, sem shell) isolado. Sempre limpa a caixa de areia; tempo esgotado mata a arvore inteira."""
    limites = limites or Limites()
    modo = modo if modo in MODOS else "basico"
    caixa = Path(tempfile.mkdtemp(prefix="forja-caixa-"))
    info: dict = {"modo": modo, "grupo": False, "teto_memoria": False}
    job = None
    try:
        env2 = preparar_ambiente(env, modo, caixa)
        extra: dict = {}
        if os.name == "nt":
            extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            extra["start_new_session"] = True  # grupo proprio: o tempo esgotado mata netos tambem
        proc = subprocess.Popen(args, cwd=str(cwd), env=env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # noqa: S603 - lista fixa
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **extra)
        if os.name == "nt":
            try:
                job = _JobWindows(limites)
                job.anexar(proc)
                info.update(grupo=True, teto_memoria=True)
            except Exception as e:  # noqa: BLE001 - sem Job Object segue sem o teto (registrado)
                log.warning("job object indisponivel: %s", type(e).__name__)
                if job is not None:
                    job.fechar()
                job = None
        else:
            info["grupo"] = True
            info["teto_memoria"] = _limitar_memoria_linux(proc.pid, limites)
        try:
            texto, _ = proc.communicate(timeout=timeout)
            return Saida(texto or "", proc.returncode, False, info)
        except subprocess.TimeoutExpired:
            _matar_arvore(proc, job)
            try:
                texto, _ = proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, ValueError):
                texto = ""
            return Saida((texto or "") + "\n[tempo esgotado]", None, True, info)
    finally:
        if job is not None:
            job.fechar()
        shutil.rmtree(caixa, ignore_errors=True)


def _matar_arvore(proc: subprocess.Popen, job: _JobWindows | None) -> None:
    if job is not None:
        job.matar()
    elif os.name != "nt":
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()
