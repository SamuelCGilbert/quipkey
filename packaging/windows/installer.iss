; Per-user installer (no admin rights). Built by scripts/build.py, which passes the /D defines
; below from src/<package>/meta.py, so the app's name lives in one place.

#ifndef AppName
  #error Build this with scripts/build.py
#endif

[Setup]
AppId={#AppId}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
AppPublisher={#AppDisplayName} contributors
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppName}.exe
UninstallDisplayName={#AppDisplayName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#RootDir}\LICENSE
CloseApplications=no

[Tasks]
Name: "startup"; Description: "Start {#AppDisplayName} when I sign in to Windows"

[InstallDelete]
; drop the previous version's libraries so upgrades don't mix files
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#RootDir}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppDisplayName}"; Filename: "{app}\{#AppName}.exe"; AppUserModelID: "{#AppId}"
Name: "{userstartup}\{#AppDisplayName}"; Filename: "{app}\{#AppName}.exe"; Tasks: startup

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Start {#AppDisplayName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppName}.exe"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
procedure StopRunningApp();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppName}.exe', '', SW_HIDE,
       ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if UninstallSilent then
      Exit;
    if MsgBox('Also delete your {#AppDisplayName} settings and the downloaded speech model?' + #13#10#13#10 +
              ExpandConstant('{userappdata}\{#AppName}') + #13#10 +
              ExpandConstant('{localappdata}\{#AppName}'),
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\{#AppName}'), True, True, True);
    end;
  end;
end;
