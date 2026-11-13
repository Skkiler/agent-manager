<#
.SYNOPSIS
  Sobe a Forja REAL neste computador: seus dados (fora do Git), Kiro de verdade via ACP, login por usuario e senha, so loopback.

.DESCRIPTION
  1. Faz backup consistente do banco antes de subir (as migracoes podem alterar o esquema); guarda os 5 mais recentes.
  2. Liga o Kiro real (APP_KIRO_ACP_ENABLED=true) e acha o kiro-cli (PATH ou %LOCALAPPDATA%\Kiro-Cli).
  3. Sobe em http://127.0.0.1:<porta> (padrao 8787) e, com -Abrir, abre o navegador quando estiver pronto.
  Nada aqui le, mostra ou grava segredos. Para parar: Ctrl+C na janela (ou feche-a).

.PARAMETER Porta
  Porta local (so 127.0.0.1). Padrao 8787.
.PARAMETER Abrir
  Abre o painel no navegador quando o servidor responder.
.PARAMETER SemBackup
  Pula o backup (nao recomendado).
.PARAMETER InstalarNaInicializacao
  Cria uma tarefa agendada do Windows que sobe a Forja ao entrar na sua conta (so a sua sessao, sem privilegio de administrador).
.PARAMETER RemoverDaInicializacao
  Remove essa tarefa agendada.
#>
param(
    [int]$Porta = 8787,
    [switch]$Abrir,
    [switch]$SemBackup,
    [switch]$InstalarNaInicializacao,
    [switch]$RemoverDaInicializacao
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$tarefa = "Forja (orquestrador local)"

if ($RemoverDaInicializacao) {
    Unregister-ScheduledTask -TaskName $tarefa -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa '$tarefa' removida (se existia)."
    exit 0
}
if ($InstalarNaInicializacao) {
    $acao = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $raiz `
        -Argument "-NoProfile -WindowStyle Minimized -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Porta $Porta"
    $gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $tarefa -Action $acao -Trigger $gatilho -Settings $config -Description "Sobe a Forja em 127.0.0.1:$Porta ao entrar" -Force | Out-Null
    Write-Host "Tarefa '$tarefa' criada: a Forja sobe sozinha quando voce entrar no Windows. Remova com -RemoverDaInicializacao."
    exit 0
}

Set-Location $raiz
# Variaveis de teste/demo nao podem vazar para o servidor real
Get-ChildItem Env: | Where-Object { $_.Name -like 'APP_*' -or $_.Name -like 'FORJA_INT_DEMO*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$py = if (Test-Path "$raiz\.venv\Scripts\python.exe") { "$raiz\.venv\Scripts\python.exe" } else { "python" }

$ocupada = Get-NetTCPConnection -State Listen -LocalPort $Porta -ErrorAction SilentlyContinue
if ($ocupada) { throw "A porta $Porta ja esta em uso. Use -Porta <outra> ou feche o que esta nela." }

if (-not $SemBackup) {
    & $py "$raiz\scripts\backup_banco.py" --manter 5
    if ($LASTEXITCODE -ne 0) { throw "Backup falhou; nada foi alterado. Rode de novo ou use -SemBackup por sua conta." }
}

$env:APP_KIRO_ACP_ENABLED = "true"
$env:APP_PORT = "$Porta"
$env:APP_BIND_HOST = "127.0.0.1"
$args_forja = @("-m", "forja")
if ($Abrir) { $args_forja += "--abrir" }
Write-Host "Forja em http://127.0.0.1:$Porta  (Kiro real; Ctrl+C para parar)"
& $py @args_forja
