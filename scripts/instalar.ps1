<#
.SYNOPSIS
  Instala a Forja neste computador e a deixa no ar continuamente (Windows, sem administrador).

.DESCRIPTION
  Passo a passo, cada um idempotente (rodar de novo so completa o que falta):
  1. Confere o Python (3.12 ou mais novo).
  2. Cria o ambiente isolado .venv na pasta do projeto e instala as dependencias (requirements.txt).
  3. Diagnostica o Kiro CLI (instalado? login feito?). Sem Kiro a Forja sobe, mas as execucoes ficam bloqueadas com o motivo.
  4. Instala a tarefa agendada "Forja (orquestrador local)": sobe ao entrar no Windows, sem janela, supervisionada.
  5. Espera o servidor responder e abre http://127.0.0.1:<porta>. No primeiro acesso a tela pede para criar usuario e senha.
  Nada aqui le, mostra ou grava segredos. Os seus dados ficam fora do repositorio (%LOCALAPPDATA%\Forja).

.PARAMETER Porta
  Porta local (so 127.0.0.1). Padrao 8787.
.PARAMETER SemInicializacao
  So instala (passos 1-3); nao cria a tarefa agendada. Suba depois com scripts\iniciar_forja.ps1 -Abrir.
.PARAMETER NaoAbrir
  Nao abre o navegador no fim.
#>
param(
    [int]$Porta = 8787,
    [switch]$SemInicializacao,
    [switch]$NaoAbrir
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Passo([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

Passo "1/5 Python"
$base = Get-Command python -ErrorAction SilentlyContinue
if (-not $base) { $base = Get-Command py -ErrorAction SilentlyContinue }
if (-not $base) { throw "Python nao encontrado. Instale o Python 3.12+ (python.org ou 'winget install Python.Python.3.13') e rode de novo." }
$versao = & $base.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$versao -lt [version]"3.12") { throw "Python $versao encontrado; a Forja precisa do 3.12 ou mais novo." }
Write-Host "Python $versao ($($base.Source))"

Passo "2/5 Ambiente isolado e dependencias"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    & $base.Source -m venv (Join-Path $raiz ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel criar o ambiente .venv." }
}
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $raiz "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias (requirements.txt). Confira a conexao e rode de novo." }
& $py -c "import forja; print('Forja', forja.__version__)"

Passo "3/5 Kiro CLI"
$kiroCli = Join-Path $env:LOCALAPPDATA "Kiro-Cli"
if ((Test-Path $kiroCli) -and ($env:Path -notlike "*$kiroCli*")) { $env:Path += ";$kiroCli" }
if (Get-Command kiro-cli -ErrorAction SilentlyContinue) {
    $diag = & $py (Join-Path $raiz "scripts\diagnostico_kiro.py") 2>$null | Out-String
    try { $d = $diag | ConvertFrom-Json } catch { $d = $null }
    if ($d -and $d.autenticado -and $d.acp_handshake) { Write-Host "Kiro pronto: $($d.versao), login feito, ACP respondendo." }
    elseif ($d -and -not $d.autenticado) { Write-Warning "Kiro instalado, mas sem login. Rode 'kiro-cli login' e depois este instalador de novo." }
    else { Write-Warning "Kiro instalado, mas o diagnostico nao fechou. Veja: $py scripts\diagnostico_kiro.py" }
} else {
    Write-Warning "Kiro CLI nao encontrado. Instale (https://kiro.dev/cli) e faca 'kiro-cli login'. A Forja sobe assim mesmo; as execucoes ficam bloqueadas ate la."
}

$iniciar = Join-Path $raiz "scripts\iniciar_forja.ps1"
if ($SemInicializacao) {
    Passo "Pronto (sem tarefa agendada)"
    Write-Host "Para subir: powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 -Abrir"
    exit 0
}

Passo "4/5 Hospedagem continua (tarefa agendada da sua conta)"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $iniciar -Porta $Porta -InstalarNaInicializacao
if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel instalar a tarefa agendada." }

Passo "5/5 Esperando o servidor"
$ok = $false
for ($i = 0; $i -lt 90 -and -not $ok; $i++) {
    try { $ok = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$Porta/api/v1/saude").StatusCode -eq 200 } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { throw "O servidor nao respondeu em 90 s. Veja os logs em $env:LOCALAPPDATA\Forja (servidor.erro.log)." }
Write-Host "Forja no ar: http://127.0.0.1:$Porta" -ForegroundColor Green
Write-Host "Status: scripts\iniciar_forja.ps1 -Status | Parar: -Parar | Remover da inicializacao: -RemoverDaInicializacao"
if (-not $NaoAbrir) { Start-Process "http://127.0.0.1:$Porta" }
