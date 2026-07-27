# =============================================================================
# ITHOS Central - instalador NATIVO para Windows (KVM 2 / Windows Server o PC)
# Sin Docker: corre con Python + tareas programadas, y Caddy para HTTPS/WSS.
# Uso (PowerShell como Administrador):
#     Set-ExecutionPolicy -Scope Process Bypass -Force
#     .\central_windows.ps1
# =============================================================================
$ErrorActionPreference = "Stop"
$RAIZ    = Split-Path (Split-Path $MyInvocation.MyCommand.Path)   # ..\ (raiz)
$CENTRAL = Join-Path $RAIZ "central"
Write-Host "==> Proyecto en: $RAIZ" -ForegroundColor Cyan

# El proyecto debe estar en disco LOCAL (uvicorn no corre bien desde \\red).
if ($RAIZ -like "\\*") {
  Write-Host "El proyecto esta en un recurso de red. Copialo a un disco local (ej. C:\ithos) y corre el instalador desde ahi." -ForegroundColor Red
  exit 1
}

# 1) Python
try { python --version | Out-Null } catch {
  Write-Host "Instalando Python 3.12..." -ForegroundColor Yellow
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
}
$py = (Get-Command python).Source
Write-Host "OK Python: $py" -ForegroundColor Green

# 2) Dependencias del central
Write-Host "==> Instalando dependencias del central..." -ForegroundColor Cyan
python -m pip install --upgrade pip | Out-Null
python -m pip install -r (Join-Path $CENTRAL "requirements.txt")
Write-Host "OK Dependencias instaladas." -ForegroundColor Green

# 2b) ffmpeg (sistema) — necesario para las NOTAS DE VOZ por WhatsApp/Telegram.
try { ffmpeg -version | Out-Null } catch {
  Write-Host "==> Instalando ffmpeg (para notas de voz)..." -ForegroundColor Cyan
  try { winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements }
  catch { Write-Host "   (no se pudo instalar ffmpeg automaticamente; instalalo a mano si vas a usar notas de voz)" -ForegroundColor Yellow }
}

# 3) clientes.json
$cli = Join-Path $CENTRAL "clientes.json"
if (-not (Test-Path $cli)) {
  $ej = Join-Path $CENTRAL "clientes.ejemplo.json"
  if (Test-Path $ej) { Copy-Item $ej $cli } else { '{"clientes": []}' | Out-File -Encoding utf8 $cli }
  Write-Host "OK clientes.json creado." -ForegroundColor Green
}

# 4) Tareas programadas: Central (8080) + Panel (8090), arrancan al iniciar Windows
function Nueva-Tarea($nombre, $arg) {
  $accion  = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory $CENTRAL
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $set     = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $trigger -Settings $set `
    -RunLevel Highest -User "SYSTEM" -Force | Out-Null
  Start-ScheduledTask -TaskName $nombre
}
Write-Host "==> Creando tareas 'ITHOS Central' y 'ITHOS Panel'..." -ForegroundColor Cyan
Nueva-Tarea "ITHOS Central" "-m uvicorn main:app --host 0.0.0.0 --port 8080"
Nueva-Tarea "ITHOS Panel"   "-m uvicorn panel:app --host 0.0.0.0 --port 8090"
Write-Host "OK Central (8080) y Panel (8090) corriendo y en autoarranque." -ForegroundColor Green

# 5) HTTPS/WSS con Caddy (opcional pero recomendado)
$dominio = Read-Host "Dominio para HTTPS/WSS (ej: ithos.tuempresa.com) [enter=solo HTTP]"
if ($dominio) {
  $caddyDir = Join-Path $CENTRAL "caddy"
  $caddyExe = Join-Path $caddyDir "caddy.exe"
  if (-not (Test-Path $caddyExe)) {
    Write-Host "==> Descargando Caddy para Windows..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force $caddyDir | Out-Null
    $url = "https://caddyserver.com/api/download?os=windows&arch=amd64"
    Invoke-WebRequest -Uri $url -OutFile $caddyExe
  }
  # Caddyfile nativo: TLS al dominio, reverse proxy al central local
  $cf = Join-Path $caddyDir "Caddyfile"
  "$dominio {`r`n    reverse_proxy 127.0.0.1:8080`r`n}" | Out-File -Encoding ascii $cf
  $accion  = New-ScheduledTaskAction -Execute $caddyExe -Argument "run --config `"$cf`"" -WorkingDirectory $caddyDir
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $set     = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "ITHOS Caddy" -Action $accion -Trigger $trigger -Settings $set `
    -RunLevel Highest -User "SYSTEM" -Force | Out-Null
  Start-ScheduledTask -TaskName "ITHOS Caddy"
  Write-Host "OK HTTPS/WSS activo. Los agentes usan: wss://$dominio/ws" -ForegroundColor Green
  Write-Host "   (abri los puertos 80 y 443 en el firewall/Hostinger)" -ForegroundColor Yellow
} else {
  Write-Host "Sin dominio: central en http://IP:8080 (podes agregar HTTPS despues)." -ForegroundColor Yellow
}

# 6) Firewall (permitir 8080/8090)
New-NetFirewallRule -DisplayName "ITHOS Central 8080" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -DisplayName "ITHOS Panel 8090"   -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8090 -ErrorAction SilentlyContinue | Out-Null

Write-Host ""
Write-Host "LISTO. Central ITHOS instalado en Windows." -ForegroundColor Green
Write-Host "  Panel:  http://localhost:8090/    (y /alta para autoservicio)"
Write-Host "  Estado: Get-ScheduledTask 'ITHOS *'"
Write-Host "  Frenar: Stop-ScheduledTask 'ITHOS Central'; Stop-ScheduledTask 'ITHOS Panel'"
