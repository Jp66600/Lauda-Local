; Instalador do Vellum (Inno Setup 6).
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
; Instala por usuário (sem pedir administrador), cria atalhos e um
; desinstalador. A pasta de trabalho do usuário — modelos, preferências,
; checkpoints e logs — fica em %USERPROFILE%\.vellum e NÃO é apagada na
; desinstalação sem confirmação: é dado dele, não do programa.

#define AppName        "Vellum"
#define AppVersion     "0.9.0-beta"
#define AppPublisher   "Vellum"
#define AppExe         "Vellum.exe"
#define RaizProjeto    ".."

[Setup]
; AppId novo porque o produto mudou de nome. Para o testador não ficar com dois
; programas na lista, o [Code] abaixo desinstala o MediaIntel Local em silêncio
; antes de copiar os arquivos. As escolhas dele são preservadas pelo próprio
; aplicativo, que copia ~/.mediaintel para ~/.vellum na primeira abertura.
AppId={{3F94D2C7-5A18-4E63-B0D9-6C25A7E14B02}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir={#RaizProjeto}\dist
OutputBaseFilename=Vellum-{#AppVersion}-setup
SetupIconFile={#RaizProjeto}\assets\vellum.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile={#RaizProjeto}\packaging\LICENCAS.txt
InfoBeforeFile={#RaizProjeto}\packaging\ANTES-DE-INSTALAR.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Sem exigir administrador: instala na pasta do usuário e evita o segundo
; pop-up de permissão, que é onde muita gente desiste.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#RaizProjeto}\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RaizProjeto}\packaging\LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Só o que o instalador criou. Modelos e preferências ficam.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ O produto se chamava MediaIntel Local. Sem isto, quem já testou ficaria com
  dois programas instalados, dois atalhos e nenhuma pista de qual é o novo. }
const
  IdAntigo = '{8E6C1F1A-2B7D-4F5E-9C31-7A0D4E2B5C88}_is1';

function DesinstaladorAntigo(): String;
var
  Chave: String;
  Valor: String;
begin
  Result := '';
  Chave := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + IdAntigo;
  if RegQueryStringValue(HKCU, Chave, 'UninstallString', Valor) then
    Result := RemoveQuotes(Valor)
  else if RegQueryStringValue(HKLM, Chave, 'UninstallString', Valor) then
    Result := RemoveQuotes(Valor);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Desinstalador: String;
  Codigo: Integer;
begin
  Result := '';
  Desinstalador := DesinstaladorAntigo();
  if Desinstalador = '' then
    Exit;

  { /VERYSILENT: a pessoa já disse sim uma vez, nesta tela. }
  if not Exec(Desinstalador, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
              '', SW_HIDE, ewWaitUntilTerminated, Codigo) then
    { Falhar aqui não impede a instalação: o pior caso é sobrar o programa
      antigo na lista, e isso o usuário resolve sozinho. }
    Log('Não consegui remover a versão MediaIntel Local: ' + SysErrorMessage(Codigo));
end;
