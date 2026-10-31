; IDM 2.0.0 installer
; Compile with Inno Setup 6.3+ or 7.x:
;   ISCC.exe installer\IDM_Setup.iss
;
; The installer never writes to the application data directory.  User data
; lives in %APPDATA%\IDM Download Manager (database, logs, settings and
; downloads) and is preserved across upgrades.  The uninstaller removes it
; only when the user explicitly chooses to, or when /REMOVEDATA is passed.
; The folder name is distinct from the commercial IDM's %APPDATA%\IDM folder.
;
; The installation includes IDM_Updater.exe, which IDM copies to a temporary
; folder and runs outside {app} to verify and install future updates.  That
; keeps the updater from locking files while the installer replaces them.
;
; IDM_NativeHost.exe is registered per user (HKCU) for each detected browser
; only when the matching optional task is selected.  Browser extensions are
; shipped as ZIP packages in {app}\browser-extensions and are never installed
; automatically; the user loads them from the browser's extension page or a
; store.

#define MyAppName "IDM"
#define MyAppVersion "2.0.0"
#define MyAppVerName "IDM 2.0.0"
#define MyAppPublisher "IDM"
#define MyAppExeName "IDM.exe"
#define NativeHostExeName "IDM_NativeHost.exe"
#define NativeHostName "com.idm.native"
#define ChromeExtensionId "ljckgbgnolmopacdgmmgaijleadcmpgn"
#define FirefoxExtensionId "idm-browser-integration@idm.local"
#define MyAppId "{{A52627A1-E4C9-456C-A397-BB6D9FD48F1B}"
#define MyAppDataDir "{userappdata}\IDM Download Manager"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppVerName}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) 2026 IDM
VersionInfoVersion=2.0.0.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=IDM Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoOriginalFileName=IDM_Setup.exe

DefaultDirName={autopf}\IDM
DefaultGroupName=IDM
DisableProgramGroupPage=yes
DisableWelcomePage=no
AllowNoIcons=no

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\dist-installer
OutputBaseFilename=IDM_Setup
SetupIconFile=..\assets\logo\idm.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Uninstallable=yes

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardImageFile=assets\wizard-large.bmp
WizardSmallImageFile=assets\wizard-small.bmp
WizardResizable=no

UsePreviousAppDir=yes
UsePreviousTasks=yes
UsePreviousSetupType=yes
UsePreviousLanguage=yes
; Automatic updates must not move an existing per-user install to Program
; Files (or the reverse); reuse the privilege scope of the previous install.
UsePreviousPrivileges=yes

CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no
ChangesEnvironment=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start IDM automatically when Windows starts"; GroupDescription: "Windows integration"; Flags: unchecked
Name: "chrome"; Description: "Integrate with Google Chrome"; GroupDescription: "Browser integration:"; Flags: checkedonce; Check: IsChromeInstalled
Name: "edge"; Description: "Integrate with Microsoft Edge"; GroupDescription: "Browser integration:"; Flags: checkedonce; Check: IsEdgeInstalled
Name: "firefox"; Description: "Integrate with Mozilla Firefox"; GroupDescription: "Browser integration:"; Flags: checkedonce; Check: IsFirefoxInstalled

[Files]
Source: "..\dist\IDM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-extensions\*.zip"; DestDir: "{app}\browser-extensions"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
Name: "{app}\browser-integration"

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.chrome.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: ChromeTaskSelected
#if PREPROCVER >= EncodeVer(7,0,0)
Root: HKCU32; Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.chrome.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: ChromeTaskSelected
#else
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.chrome.json"; Flags: uninsdeletevalue uninsdeletekeyifempty 32bit; Check: ChromeTaskSelected
#endif
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.edge.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: EdgeTaskSelected
#if PREPROCVER >= EncodeVer(7,0,0)
Root: HKCU32; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.edge.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: EdgeTaskSelected
#else
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.edge.json"; Flags: uninsdeletevalue uninsdeletekeyifempty 32bit; Check: EdgeTaskSelected
#endif
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.firefox.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: FirefoxTaskSelected
#if PREPROCVER >= EncodeVer(7,0,0)
Root: HKCU32; Subkey: "Software\Mozilla\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.firefox.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: FirefoxTaskSelected
#else
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.firefox.json"; Flags: uninsdeletevalue uninsdeletekeyifempty 32bit; Check: FirefoxTaskSelected
#endif

[Icons]
Name: "{group}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "IDM Internet Download Manager"
Name: "{autodesktop}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "IDM Internet Download Manager"; Tasks: desktopicon
Name: "{userstartup}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Start IDM with Windows"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,IDM}"; Flags: nowait postinstall skipifsilent

[Code]
function IsChromeInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Google\Chrome\Application\chrome.exe')) or
    FileExists(ExpandConstant('{pf32}\Google\Chrome\Application\chrome.exe')) or
    FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe'));
end;

function IsEdgeInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Microsoft\Edge\Application\msedge.exe')) or
    FileExists(ExpandConstant('{pf32}\Microsoft\Edge\Application\msedge.exe')) or
    FileExists(ExpandConstant('{localappdata}\Microsoft\Edge\Application\msedge.exe'));
end;

function IsFirefoxInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Mozilla Firefox\firefox.exe')) or
    FileExists(ExpandConstant('{pf32}\Mozilla Firefox\firefox.exe'));
end;

function ChromeTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('chrome');
end;

function EdgeTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('edge');
end;

function FirefoxTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('firefox');
end;

function NativeHostRegistryPath(Browser: String): String;
begin
  if Browser = 'chrome' then
    Result := 'Software\Google\Chrome\NativeMessagingHosts\{#NativeHostName}'
  else if Browser = 'edge' then
    Result := 'Software\Microsoft\Edge\NativeMessagingHosts\{#NativeHostName}'
  else
    Result := 'Software\Mozilla\NativeMessagingHosts\{#NativeHostName}';
end;

function ManifestPath(Browser: String): String;
begin
  Result := ExpandConstant(
    '{app}\browser-integration\{#NativeHostName}.' + Browser + '.json');
end;

function EscapeJson(Value: String): String;
var
  I: Integer;
  Ch: String;
begin
  Result := '';
  for I := 1 to Length(Value) do
  begin
    Ch := Copy(Value, I, 1);
    if Ch = '\' then
      Result := Result + '\\'
    else if Ch = '"' then
      Result := Result + '\"'
    else
      Result := Result + Ch;
  end;
end;

function ManifestJson(Browser: String): String;
var
  HostPath: String;
begin
  HostPath := EscapeJson(ExpandConstant('{app}\{#NativeHostExeName}'));
  if Browser = 'firefox' then
    Result :=
      '{"name":"{#NativeHostName}","description":"IDM browser integration",' +
      '"path":"' + HostPath + '","type":"stdio","allowed_extensions":["{#FirefoxExtensionId}"]}'
  else
    Result :=
      '{"name":"{#NativeHostName}","description":"IDM browser integration",' +
      '"path":"' + HostPath + '","type":"stdio","allowed_origins":["chrome-extension://{#ChromeExtensionId}/"]}';
end;

function WriteManifest(Browser: String): Boolean;
var
  Path: String;
begin
  ForceDirectories(ExpandConstant('{app}\browser-integration'));
  Path := ManifestPath(Browser);
  Result := SaveStringToFile(Path, ManifestJson(Browser), False);
  if not Result then
    MsgBox('IDM could not write the browser integration manifest:' + #13#10 +
           Path, mbError, MB_OK);
end;

function RegisterBrowser(Browser: String): Boolean;
var
  SubKey: String;
  Value: String;
begin
  Result := WriteManifest(Browser);
  if not Result then
    Exit;
  SubKey := NativeHostRegistryPath(Browser);
  if not (RegQueryStringValue(HKCU, SubKey, '', Value) or
          RegQueryStringValue(HKCU32, SubKey, '', Value)) then
  begin
    Result := False;
    MsgBox('IDM could not register its browser integration for ' + Browser + '.' +
           Chr(13) + Chr(10) + Chr(13) + Chr(10) +
           'You can register it later from a command prompt with:' +
           Chr(13) + Chr(10) +
           'scripts\register_native_host.py install', mbError, MB_OK);
  end;
end;

procedure UnregisterBrowser(Browser: String);
var
  SubKey: String;
  Manifest: String;
  Value: String;
begin
  SubKey := NativeHostRegistryPath(Browser);
  Manifest := ManifestPath(Browser);
  if RegQueryStringValue(HKCU, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0) then
    RegDeleteValue(HKCU, SubKey, '');
  if RegQueryStringValue(HKCU32, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0) then
    RegDeleteValue(HKCU32, SubKey, '');
  DeleteFile(Manifest);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if ChromeTaskSelected() and IsChromeInstalled() then
      RegisterBrowser('chrome')
    else
      UnregisterBrowser('chrome');

    if EdgeTaskSelected() and IsEdgeInstalled() then
      RegisterBrowser('edge')
    else
      UnregisterBrowser('edge');

    if FirefoxTaskSelected() and IsFirefoxInstalled() then
      RegisterBrowser('firefox')
    else
      UnregisterBrowser('firefox');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    UnregisterBrowser('chrome');
    UnregisterBrowser('edge');
    UnregisterBrowser('firefox');
  end;
end;

function HasRemoveDataSwitch(): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
    if CompareText(ParamStr(Index), '/REMOVEDATA') = 0 then
      Result := True;
end;

function RemoveAppData(): Boolean;
var
  DataDir: String;
begin
  DataDir := ExpandConstant('{#MyAppDataDir}');
  if not DirExists(DataDir) then
  begin
    Result := True;
    Exit;
  end;
  Result := DelTree(DataDir, True, True, True);
end;

function InitializeUninstall(): Boolean;
var
  Choice: Integer;
  DataDir: String;
begin
  Result := True;
  DataDir := ExpandConstant('{#MyAppDataDir}');

  if HasRemoveDataSwitch() then
  begin
    if not RemoveAppData() then
      MsgBox('Some IDM user data could not be removed from:' + #13#10 +
             DataDir + #13#10#13#10 +
             'Close IDM and any program using those files, then remove the folder manually.',
             mbError, MB_OK);
    Exit;
  end;

  if (not UninstallSilent) and DirExists(DataDir) then
  begin
    Choice := MsgBox(
      'Also remove your IDM user data?' + #13#10#13#10 +
      'This permanently deletes the database, settings, logs and any downloaded files stored in:' + #13#10 +
      DataDir + #13#10#13#10 +
      'Files you saved outside this folder are not touched.' + #13#10#13#10 +
      'Choose No to keep your settings and download history for a future reinstall.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
    if Choice = IDYES then
    begin
      if not RemoveAppData() then
        MsgBox('Some IDM user data could not be removed from:' + #13#10 +
               DataDir + #13#10#13#10 +
               'Close IDM and any program using those files, then remove the folder manually.',
               mbError, MB_OK);
    end;
  end;
end;
