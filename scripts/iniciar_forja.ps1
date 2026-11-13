<#
.SYNOPSIS
  Sobe a Forja REAL neste computador: seus dados (fora do Git), Kiro de verdade via ACP, login por usuario e senha, so loopback.

.DESCRIPTION
  1. Faz backup consistente do banco antes de subir (as migracoes podem alterar o esquema); guarda os 5 mais recentes.
  2. Liga o Kiro real (APP_KIRO_ACP_ENABLED=true) e acha o kiro-cli (PATH ou %LOCALAPPDATA%\Kiro-Cli).
  3. Sobe em http://127.0.0.1:<porta> (padrao 8787) e, com -Abrir, abre o navegador quando estiver pronto.
  Nada aqui le, mostra ou grava segredos. Para parar: Ctrl+C na janela (ou -Parar, se estiver hospedada em segundo plano).

  Hospedagem continua (-InstalarNaInicializacao): tarefa agendada do Windows, SO da sua conta e sem administrador, que sobe a
  Forja ao entrar no Windows, sem janela, com supervisao (se o servidor cair, sobe de novo com espera crescente; no maximo
  10 reinicios por hora). Saida em %LOCALAPPDATA%\Forja\ (servidor.log, servidor.erro.log e supervisao.log; a execucao
  anterior fica em *.1). Os logs estruturados da propria Forja continuam no perfil do usuario.

.PARAMETER Porta
  Porta local (so 127.0.0.1). Padrao 8787.
.PARAMETER Abrir
  Abre o painel no navegador quando o servidor responder.
.PARAMETER SemBackup
  Pula o backup (nao recomendado).
.PARAMETER Supervisionar
  Reinicia o servidor se ele cair (usado pela tarefa agendada).
.PARAMETER InstalarNaInicializacao
  Cria (ou atualiza) a tarefa agendada e a inicia agora.
.PARAMETER RemoverDaInicializacao
  Para e remove a tarefa agendada.
.PARAMETER Parar
  Para a Forja hospedada (a tarefa continua instalada e volta no proximo login).
.PARAMETER Status
  Mostra se a tarefa existe, se esta rodando e se o servidor responde.
#>
param(
    [int]$Porta = 8787,
    [switch]$Abrir,
    [switch]$SemBackup,
    [switch]$Supervisionar,
    [switch]$InstalarNaInicializacao,
    [switch]$RemoverDaInicializacao,
    [switch]$Parar,
    [switch]$Status
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$tarefa = "Forja (orquestrador local)"
$pastaLog = Join-Path $env:LOCALAPPDATA "Forja"
$log = Join-Path $pastaLog "servidor.log"

function Responde([int]$p) {
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$p/api/v1/saude").StatusCode -eq 200 } catch { $false }
}

if ($Status) {
    $t = Get-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue
    $estado = if ($t) { $t.State } else { "nao instalada" }
    Write-Host "Tarefa agendada: $estado"
    Write-Host ("Servidor em http://127.0.0.1:{0}: {1}" -f $Porta, $(if (Responde $Porta) { "respondendo" } else { "sem resposta" }))
    Write-Host "Logs: $pastaLog (servidor.log, servidor.erro.log, supervisao.log)"
    exit 0
}
if ($Parar -or $RemoverDaInicializacao) {
    Stop-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue
    # o servidor e filho do PowerShell da tarefa: encerra so o python da Forja que escuta nesta porta
    $dono = (Get-NetTCPConnection -State Listen -LocalPort $Porta -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
    if ($dono) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$dono"
        if ($proc.CommandLine -match "-m forja") {
            & taskkill.exe /PID $dono /T /F | Out-Null  # /T: leva junto os agentes (kiro-cli) que ele abriu
            Write-Host "Servidor da Forja parado (porta $Porta)."
        }
        else { Write-Host "A porta $Porta e de outro programa; nada foi parado." }
    }
    if ($RemoverDaInicializacao) {
        Unregister-ScheduledTask -TaskName $tarefa -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Tarefa '$tarefa' removida (se existia)."
    }
    exit 0
}
if ($InstalarNaInicializacao) {
    $acao = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $raiz `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Porta $Porta -Supervisionar"
    $gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
    $quem = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $tarefa -Action $acao -Trigger $gatilho -Settings $config -Principal $quem `
        -Description "Sobe a Forja em 127.0.0.1:$Porta ao entrar (supervisionada, sem janela)" -Force | Out-Null
    if (-not (Responde $Porta)) { Start-ScheduledTask -TaskName $tarefa }
    Write-Host "Tarefa '$tarefa' instalada e iniciada: a Forja fica no ar enquanto voce estiver conectado no Windows."
    Write-Host "Painel: http://127.0.0.1:$Porta   Status: -Status   Parar: -Parar   Remover: -RemoverDaInicializacao"
    exit 0
}

Set-Location $raiz
# Variaveis de teste/demo nao podem vazar para o servidor real
Get-ChildItem Env: | Where-Object { $_.Name -like 'APP_*' -or $_.Name -like 'FORJA_INT_DEMO*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$py = if (Test-Path "$raiz\.venv\Scripts\python.exe") { "$raiz\.venv\Scripts\python.exe" } else { "python" }
$kiroCli = Join-Path $env:LOCALAPPDATA "Kiro-Cli"
if ((Test-Path $kiroCli) -and ($env:Path -notlike "*$kiroCli*")) { $env:Path += ";$kiroCli" }

$ocupada = Get-NetTCPConnection -State Listen -LocalPort $Porta -ErrorAction SilentlyContinue
if ($ocupada) {
    if ($Supervisionar -and (Responde $Porta)) { exit 0 }  # ja hospedada (outra instancia): nada a fazer
    throw "A porta $Porta ja esta em uso. Use -Porta <outra> ou feche o que esta nela."
}

if (-not $SemBackup) {
    & $py "$raiz\scripts\backup_banco.py" --manter 5
    if ($LASTEXITCODE -ne 0) { throw "Backup falhou; nada foi alterado. Rode de novo ou use -SemBackup por sua conta." }
}

$env:APP_KIRO_ACP_ENABLED = "true"
$env:APP_PORT = "$Porta"
$env:APP_BIND_HOST = "127.0.0.1"
$args_forja = @("-m", "forja")
if ($Abrir) { $args_forja += "--abrir" }

if (-not $Supervisionar) {
    Write-Host "Forja em http://127.0.0.1:$Porta  (Kiro real; Ctrl+C para parar)"
    & $py @args_forja
    exit $LASTEXITCODE
}

# Supervisao: reinicia se cair, com espera crescente; desiste depois de 10 quedas na mesma hora (algo esta errado: veja o log).
New-Item -ItemType Directory -Force -Path $pastaLog | Out-Null
$ErrorActionPreference = "Continue"  # uma queda do servidor nao pode derrubar a supervisao
$supervisao = Join-Path $pastaLog "supervisao.log"
$erros = Join-Path $pastaLog "servidor.erro.log"
$quedas = New-Object System.Collections.Generic.List[datetime]
$espera = 5
while ($true) {
    foreach ($f in @($log, $erros)) { if (Test-Path $f) { Move-Item -Force $f "$f.1" } }  # guarda a saida da execucao anterior
    Add-Content -Path $supervisao -Value ("[{0:s}] iniciando a Forja em 127.0.0.1:{1}" -f (Get-Date), $Porta)
    $inicio = Get-Date
    $p = Start-Process -FilePath $py -ArgumentList $args_forja -WorkingDirectory $raiz -NoNewWindow -PassThru -Wait `
        -RedirectStandardOutput $log -RedirectStandardError $erros
    $codigo = $p.ExitCode
    Add-Content -Path $supervisao -Value ("[{0:s}] servidor saiu (codigo {1})" -f (Get-Date), $codigo)
    if ($codigo -eq 0) { break }  # parada pedida (Ctrl+C/encerramento limpo)
    if (((Get-Date) - $inicio).TotalMinutes -gt 10) { $espera = 5 }  # rodou bem por um tempo: volta a espera curta
    $quedas.Add((Get-Date))
    $recentes = @($quedas | Where-Object { ((Get-Date) - $_).TotalMinutes -lt 60 })
    if ($recentes.Count -ge 10) {
        Add-Content -Path $supervisao -Value "[$(Get-Date -Format s)] 10 quedas em 1 hora: supervisao desistiu. Veja $erros."
        exit 1
    }
    Start-Sleep -Seconds $espera
    $espera = [Math]::Min($espera * 2, 300)
}
