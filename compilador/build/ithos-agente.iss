; ============================================================================
;  Instalador del AGENTE ITHOS (Inno Setup 6/7) — personalizado (icono + banner ITHOS).
;  Empaqueta el ejecutable (APP con interfaz gráfica) en un instalador con menú Inicio,
;  arranque al iniciar sesión (portero) y desinstalador. Compilar:
;     "C:\Users\bsierra\AppData\Local\Programs\Inno Setup 7\ISCC.exe" build\ithos-agente.iss
;  Salida: dist\ITHOS-Agente-Setup.exe   (en dist\ queda SOLO el instalador)
;  Requisito previo: build\construir_agente.bat (deja build\exe\ithos-agente.exe + build\ithos.ico)
; ============================================================================
#define MyAppName "ITHOS Agente"
#define MyAppVersion "1.1.29"
#define MyAppPublisher "INTELLIHELP S.A."
#define MyAppExeName "ithos-agente.exe"

[Setup]
AppId={{6E7B2C10-2F5A-4B8C-9D3E-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ITHOS
DefaultGroupName=ITHOS
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=ITHOS-Agente-Setup
SetupIconFile=ithos.ico
WizardImageFile=ithos_wizard.bmp
WizardSmallImageFile=ithos_wizard_small.bmp
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
; Al ACTUALIZAR, el agente está corriendo (headless --run + bootloader + hijo). Forzamos el cierre sin
; preguntar (además del taskkill del árbol en [Code] PrepareToInstall) y NO lo reiniciamos por Restart
; Manager: se relanza solo con el postinstall / la tarea ONLOGON. Así la actualización nunca se traba.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "startup"; Description: "Arrancar ITHOS al iniciar sesión (necesario para el PORTERO por voz)"; GroupDescription: "Inicio automático:"

[Files]
Source: "exe\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Certificado público de INTELLIHELP: el instalador lo instala como CONFIABLE (abajo) para que la firma
; del agente sea válida en esta PC SIN que el cliente corra ningún comando. Si no existe (build sin
; firmar), no pasa nada. (external + skipifsourcedoesntexist: no rompe si falta.)
Source: "ithos-publisher.cer"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Nombres SIN caracteres ilegales (/ \ : * ? " < > |) — si no, IPersistFile::Save falla.
Name: "{group}\ITHOS Agente"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar ITHOS Agente"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ITHOS Agente"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; CONFIAR el certificado de INTELLIHELP en ESTA PC (el instalador corre como admin) -> la firma del
; agente queda VÁLIDA acá, sin que el cliente ejecute ningún comando. Raíz de confianza + Editores de
; confianza. Si el .cer no está (build sin firmar), certutil falla silencioso (Check no rompe).
Filename: "{sys}\certutil.exe"; Parameters: "-addstore -f Root ""{app}\ithos-publisher.cer"""; \
  Flags: runhidden skipifdoesntexist; Check: FileExists(ExpandConstant('{app}\ithos-publisher.cer'))
Filename: "{sys}\certutil.exe"; Parameters: "-addstore -f TrustedPublisher ""{app}\ithos-publisher.cer"""; \
  Flags: runhidden skipifdoesntexist; Check: FileExists(ExpandConstant('{app}\ithos-publisher.cer'))
; Arranque al iniciar sesión (HEADLESS con --run, para el portero con audio). Solo si el usuario lo pidió.
Filename: "{sys}\schtasks.exe"; \
  Parameters: "/Create /F /RL HIGHEST /SC ONLOGON /TN ""ITHOS Agente"" /TR ""\""{app}\{#MyAppExeName}\"" --run"""; \
  Flags: runhidden; Tasks: startup
; Al terminar, abre la APP para configurar (api_key + contraseña de la empresa).
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir ITHOS Agente para configurarlo"; \
  Flags: postinstall nowait skipifsilent

[UninstallRun]
; Frenar el agente si está corriendo (para poder borrar sus datos sin bloqueos).
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM {#MyAppExeName}"; \
  Flags: runhidden; RunOnceId: "KillIthosAgent"
; Al desinstalar, quita la tarea de arranque (no deja nada colgado).
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""ITHOS Agente"" /F"; \
  Flags: runhidden; RunOnceId: "DelIthosTask"
; Borrar los datos del agente de TODOS los perfiles de usuario (config + caché por cliente). El
; instalador corre como admin, así que {localappdata} sería la del admin, NO la del usuario real: por
; eso barremos %SystemDrive%\Users\*\AppData\Local\ITHOS. Así NO deja rastro. CRÍTICO: SOLO borra la
; carpeta del AGENTE; jamás toca GLPI/tickets ni la base de fichadas del cliente (viven en sus servidores).
Filename: "{cmd}"; \
  Parameters: "/C for /d %U in (""{sd}\Users\*"") do @rd /s /q ""%U\AppData\Local\ITHOS"" >nul 2>&1"; \
  Flags: runhidden; RunOnceId: "DelIthosUserData"
; Y saca el certificado de INTELLIHELP de las tiendas de confianza (no deja rastro).
Filename: "{sys}\certutil.exe"; Parameters: "-delstore Root ""INTELLIHELP S.A."""; \
  Flags: runhidden; RunOnceId: "DelIthosCertRoot"
Filename: "{sys}\certutil.exe"; Parameters: "-delstore TrustedPublisher ""INTELLIHELP S.A."""; \
  Flags: runhidden; RunOnceId: "DelIthosCertPub"

[UninstallDelete]
; La carpeta de INSTALACIÓN (Program Files\ITHOS). Los DATOS por usuario los borra el [UninstallRun] de
; arriba (barre todos los perfiles), porque con instalación de admin {localappdata} apuntaría al admin.
; CRÍTICO: NO se toca NADA del cliente (GLPI/tickets, base de fichadas IVMS, ni el trabajo hecho) — esos
; viven en los servidores del cliente y el agente solo los consulta/lee, nunca los borra.
Type: filesandordirs; Name: "{app}"

[Code]
// Versión de ITHOS ya instalada en esta PC (clave de desinstalación de Inno). Busca en las dos vistas
// del registro (32/64 bits) para no fallar según cómo corra el instalador.
function VersionInstalada(): String;
var V: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{6E7B2C10-2F5A-4B8C-9D3E-1A2B3C4D5E6F}_is1', 'DisplayVersion', V) then
    Result := V
  else if RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{6E7B2C10-2F5A-4B8C-9D3E-1A2B3C4D5E6F}_is1', 'DisplayVersion', V) then
    Result := V;
end;

// Al arrancar el instalador: si ya hay una versión instalada y es DISTINTA, avisamos que se ACTUALIZA
// (de X a Y) en vez de "instalar por arriba" en silencio. Nivel profesional.
function InitializeSetup(): Boolean;
var Prev: String;
begin
  Result := True;
  Prev := VersionInstalada();
  if (Prev <> '') and (Prev <> '{#MyAppVersion}') then
    MsgBox('Se detectó ITHOS Agente v' + Prev + ' en este equipo.' + #13#10#13#10 +
           'Se actualizará a la versión {#MyAppVersion}. Tus credenciales y tu configuración se '
           + 'conservan; el agente se cierra y se vuelve a abrir solo.', mbInformation, MB_OK);
end;

// Antes de instalar/actualizar, MATAMOS todas las instancias del agente (GUI + headless --run +
// bootloader de PyInstaller + proceso Python hijo) para que ningún archivo quede en uso y la
// actualización nunca se trabe. /F fuerza, /T mata TODO el árbol de procesos. Se reintenta por si
// el mutex/proceso tarda en soltar. NO toca nada del cliente: solo el proceso del agente.
procedure MatarAgente;
var
  Code, i: Integer;
begin
  for i := 1 to 3 do
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM ithos-agente.exe',
         '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(700);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  MatarAgente;          // matar TODO antes de reemplazar los archivos
  Result := '';         // '' = seguir con la instalación
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    MatarAgente;        // también al DESINSTALAR: liberar los archivos para borrarlos sin rastro
end;
