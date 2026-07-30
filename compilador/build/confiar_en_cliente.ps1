<#
  Confía en el certificado de INTELLIHELP en ESTA PC (la del cliente). Correr UNA vez, como ADMIN,
  antes/después de instalar el agente. Deja de aparecer "editor desconocido" y SmartScreen no bloquea
  el instalador ITHOS (queda firmado por "INTELLIHELP S.A." y de confianza en esta máquina).

  Uso (como administrador, con ithos-publisher.cer al lado):
     powershell -ExecutionPolicy Bypass -File confiar_en_cliente.ps1

  Para una flota grande: hacé esto por GPO (Directiva de grupo -> Configuración del equipo ->
  Directivas -> Configuración de Windows -> Configuración de seguridad -> Directivas de clave pública
  -> Entidades de certificación raíz de confianza / Editores de confianza), importando el mismo .cer.
#>
param([string]$Cer = "ithos-publisher.cer")
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Cer)) { Write-Error "No encuentro $Cer (copialo al lado de este script)."; exit 1 }

# Raíz de confianza (para validar la cadena del cert self-signed) + Editores de confianza (para que
# SmartScreen/Windows lo acepten sin avisar).
Import-Certificate -FilePath $Cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
Import-Certificate -FilePath $Cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
Write-Host "OK  Certificado de INTELLIHELP instalado como CONFIABLE en esta PC (Root + Trusted Publishers)."
Write-Host "    El instalador/agente ITHOS ya no aparece como 'editor desconocido' en esta máquina."
