<#
  Firma de código de ITHOS — GRATIS (self-signed) para la flota controlada de INTELLIHELP.

  Crea (una vez) un certificado de firma de código self-signed de INTELLIHELP y firma el .exe / el
  instalador con TIMESTAMP (la firma sigue válida aunque venza el cert). Con esto, en las PCs de los
  clientes donde se instaló el certificado como CONFIABLE (ver build\confiar_en_cliente.ps1 / GPO),
  el agente figura como editor "INTELLIHELP S.A." y NO lo bloquea SmartScreen ni sale "editor
  desconocido". Es la vía oficial de Microsoft (New-SelfSignedCertificate + Set-AuthenticodeSignature).

  Uso:
     powershell -ExecutionPolicy Bypass -File build\firmar.ps1 -Files build\exe\ithos-agente.exe
     powershell -ExecutionPolicy Bypass -File build\firmar.ps1 -Files dist\ITHOS-Agente-Setup.exe
  (o sin -Files: firma los dos si existen)

  Nota: NO reemplaza a un cert de CA pública (para una PC cualquiera de internet igual avisaría). Para
  venta masiva fuera de la flota: cert OV/EV pago o Azure Trusted Signing (ver FALTANTES.md).
#>
param(
  [string[]]$Files = @("build\exe\ithos-agente.exe", "dist\ITHOS-Agente-Setup.exe"),
  [string]$TimestampServer = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$subject = "CN=INTELLIHELP S.A., O=INTELLIHELP S.A., C=AR"

# 1) Certificado de firma de código (se crea una sola vez y queda en el store del usuario).
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -like "*INTELLIHELP*" } | Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
  Write-Host "==> Creando certificado de firma de código de INTELLIHELP (self-signed, 5 años)..."
  $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject `
    -KeyUsage DigitalSignature -KeyExportPolicy Exportable -KeyLength 3072 `
    -HashAlgorithm SHA256 -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
  # Certificado PÚBLICO (.cer) para instalar en las PCs de los clientes (confianza).
  Export-Certificate -Cert $cert -FilePath "build\ithos-publisher.cer" | Out-Null
  Write-Host "    Certificado público -> build\ithos-publisher.cer (instalalo en las PCs de los clientes)"
  # Backup del cert + clave (.pfx) si pasás una contraseña por env ITHOS_SIGN_PASS (guardalo a salvo).
  if ($env:ITHOS_SIGN_PASS) {
    $sec = ConvertTo-SecureString $env:ITHOS_SIGN_PASS -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath "build\ithos-code.pfx" -Password $sec | Out-Null
    Write-Host "    Backup del certificado -> build\ithos-code.pfx (protegido por ITHOS_SIGN_PASS)"
  }
} else {
  Write-Host ("==> Usando certificado existente: {0} (vence {1:yyyy-MM-dd})" -f $cert.Thumbprint, $cert.NotAfter)
  if (-not (Test-Path "build\ithos-publisher.cer")) {
    Export-Certificate -Cert $cert -FilePath "build\ithos-publisher.cer" | Out-Null
  }
}

# 2) Firmar los binarios pedidos, con timestamp.
#    Nota: en ESTA PC de build el estado sale "UnknownError" porque no confía el cert self-signed (no
#    está en su Root). La firma SÍ queda incrustada (editor INTELLIHELP + timestamp); en la PC del
#    cliente, donde el instalador confía el cert, sale "Valid". Por eso contamos por SignerCertificate.
$firmados = 0
foreach ($f in $Files) {
  if (Test-Path $f) {
    $r = Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 `
           -TimestampServer $TimestampServer
    $ok = ($null -ne $r.SignerCertificate)
    Write-Host ("    {0}  ->  firma {1} (estado local: {2})" -f $f, $(if($ok){"incrustada"}else{"FALLO"}), $r.Status)
    if ($ok) { $firmados++ }
  } else {
    Write-Host ("    (omito, no existe: {0})" -f $f)
  }
}
Write-Host ("==> Firma completa. {0} archivo(s) firmado(s) (INTELLIHELP + timestamp)." -f $firmados)
