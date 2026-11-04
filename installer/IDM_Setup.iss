; IDM 3.6.3 installer
; Compile with Inno Setup 6.3+ or 7.x:
;   ISCC.exe installer\IDM_Setup.iss
;
; Upgrades from 1.0.0, 2.0.0 and 2.0.1 reuse the same AppId and previous
; installation directory, so user data, settings, history and the download
; queue remain in place.  The installer never writes to the application data
; directory.  User data lives in %APPDATA%\IDM Download Manager (database,
; logs, settings and downloads) and is preserved across upgrades.  The
; uninstaller removes it only when the user explicitly chooses to, or when
; /REMOVEDATA is passed.  The folder name is distinct from the commercial
; IDM's %APPDATA%\IDM folder.
;
; The installation includes IDM_Updater.exe, which IDM copies to a temporary
; folder and runs outside {app} to verify and install future updates.  That
; keeps the updater from locking files while the installer replaces them.
;
; IDM_NativeHost.exe is registered per user (HKCU) for each detected browser
; only when the matching optional task is selected.  Browser extensions are
; shipped as ZIP packages in {app}\browser-extensions and as the unpacked
; IDM Video Assistant in {app}\BrowserExtension\IDMVideoAssistant; they are
; never installed automatically.  The user loads them from the browser's
; extension page or a store.

#define MyAppName "IDM"
#define MyAppVersion "3.6.3"
#define MyAppVerName "IDM 3.6.3"
#define MyAppPublisher "IDM"
#define MyAppExeName "IDM.exe"
#define NativeHostExeName "IDM_NativeHost.exe"
#define NativeHostName "com.idm.native"
#define ChromeExtensionId "ljckgbgnolmopacdgmmgaijleadcmpgn"
#define FirefoxExtensionId "idm-browser-integration@idm.local"
#define MyAppId "{{A52627A1-E4C9-456C-A397-BB6D9FD48F1B}"
#define MyAppDataDir "{userappdata}\IDM Download Manager"

; Optional bootstrap of the Python runtime that the project brief lists as a
; prerequisite (Python 3.11+ and the packages listed in requirements.txt).
; The packaged IDM.exe is self-contained, so this is only needed to run IDM,
; its scripts or its tests from source.  The pinned installer is verified with
; Windows Authenticode (Python Software Foundation) and the SHA-256 below.
#define PythonInstallerUrl "https://www.python.org/ftp/python/3.13.12/python-3.13.12-amd64.exe"
#define PythonInstallerSha256 "96159FCB523AE404B707186A75B4104EE23851E476A5E838E14584CF1E03F981"
#define PythonDepsScript "assets\Install-PythonDeps.ps1"
#define PythonDepsLog "IDM-PythonDeps-" + MyAppVersion + ".log"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppVerName}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) 2026 IDM
VersionInfoVersion=3.6.3.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=IDM Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoOriginalFileName=IDM-Setup-{#MyAppVersion}.exe

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
OutputBaseFilename=IDM-Setup-{#MyAppVersion}
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
Name: "brave"; Description: "Integrate with Brave"; GroupDescription: "Browser integration:"; Flags: checkedonce; Check: IsBraveInstalled
Name: "opera"; Description: "Integrate with Opera"; GroupDescription: "Browser integration:"; Flags: checkedonce; Check: IsOperaInstalled
Name: "pydeps"; Description: "Download and install Python 3.11+ and the packages listed in requirements.txt (only needed to run IDM from source)"; GroupDescription: "Additional components:"; Check: PythonRuntimeMissing

[Files]
Source: "..\dist\IDM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-extensions\*.zip"; DestDir: "{app}\browser-extensions"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\BrowserExtension\IDMVideoAssistant\*"; DestDir: "{app}\BrowserExtension\IDMVideoAssistant"; Flags: ignoreversion recursesubdirs createallsubdirs
; Shipped so the Python runtime bootstrap can be re-run after installation.
Source: "{#PythonDepsScript}"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\tools"; Flags: ignoreversion

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
Root: HKCU; Subkey: "Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.brave.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: BraveTaskSelected
#if PREPROCVER >= EncodeVer(7,0,0)
Root: HKCU32; Subkey: "Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.brave.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: BraveTaskSelected
#else
Root: HKCU; Subkey: "Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.brave.json"; Flags: uninsdeletevalue uninsdeletekeyifempty 32bit; Check: BraveTaskSelected
#endif
Root: HKCU; Subkey: "Software\Opera Software\Opera Stable\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.opera.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: OperaTaskSelected
#if PREPROCVER >= EncodeVer(7,0,0)
Root: HKCU32; Subkey: "Software\Opera Software\Opera Stable\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.opera.json"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: OperaTaskSelected
#else
Root: HKCU; Subkey: "Software\Opera Software\Opera Stable\NativeMessagingHosts\{#NativeHostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\browser-integration\{#NativeHostName}.opera.json"; Flags: uninsdeletevalue uninsdeletekeyifempty 32bit; Check: OperaTaskSelected
#endif

[Icons]
Name: "{group}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "IDM Internet Download Manager"
Name: "{autodesktop}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "IDM Internet Download Manager"; Tasks: desktopicon
Name: "{userstartup}\IDM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Start IDM with Windows"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,IDM}"; Flags: nowait postinstall skipifsilent

[Code]
{ ---------------------------------------------------------------------------
  Python prerequisite detection: interpreter 3.11+ plus requirements.txt.
  --------------------------------------------------------------------------- }

var
  PythonRuntimeChecked: Boolean;
  PythonRuntimeFound: Boolean;

function HasSwitch(Name: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
    if CompareText(ParamStr(Index), Name) = 0 then
      Result := True;
end;

function TrimTrailingSlashes(Value: String): String;
begin
  Result := Value;
  while (Length(Result) > 1) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
end;

procedure AppendPythonPath(Paths: TStrings; Exe: String);
var
  Index: Integer;
begin
  if (Exe = '') or not FileExists(Exe) then
    Exit;
  { The Microsoft Store alias is a stub that opens the Store instead of
    running Python, so it is never a usable interpreter. }
  if Pos('\WindowsApps\', Exe) > 0 then
    Exit;
  for Index := 0 to Paths.Count - 1 do
    if CompareText(Paths[Index], Exe) = 0 then
      Exit;
  Paths.Add(Exe);
end;

procedure CollectRegistryPythons(Paths: TStrings);
var
  Base: String;
  Roots: array[0..3] of Integer;
  R, J: Integer;
  SubKey, Value: String;
  Names: TArrayOfString;
begin
  Base := 'Software\Python\PythonCore';
  Roots[0] := HKLM;
  Roots[1] := HKCU;
  Roots[2] := HKLM32;
  Roots[3] := HKCU32;
  for R := 0 to 3 do
  begin
    if RegGetSubkeyNames(Roots[R], Base, Names) then
      for J := 0 to GetArrayLength(Names) - 1 do
      begin
        SubKey := Base + '\' + Names[J] + '\InstallPath';
        if RegQueryStringValue(Roots[R], SubKey, '', Value) or
           RegQueryStringValue(Roots[R], SubKey, 'Path', Value) then
          AppendPythonPath(Paths, TrimTrailingSlashes(Value) + '\python.exe');
      end;
  end;
end;

{ Standard CPython directory layouts: Python3xx and the 32-bit suffix used by
  the Windows installer. Detected through DirExists rather than a directory
  scan so the same code compiles under Inno Setup 6 and 7. }
procedure CollectFolderPythons(Base: String; Paths: TStrings);
var
  Minor: Integer;
  Name: String;
begin
  Base := TrimTrailingSlashes(Base);
  for Minor := 11 to 20 do
  begin
    Name := Base + '\Python3' + IntToStr(Minor);
    if DirExists(Name) then
      AppendPythonPath(Paths, Name + '\python.exe');
    Name := Name + '-32';
    if DirExists(Name) then
      AppendPythonPath(Paths, Name + '\python.exe');
  end;
end;

procedure CollectPythonPaths(Paths: TStrings);
begin
  CollectRegistryPythons(Paths);
  CollectFolderPythons(ExpandConstant('{localappdata}\Programs\Python'), Paths);
  CollectFolderPythons(ExpandConstant('{localappdata}\Python'), Paths);
  CollectFolderPythons(ExpandConstant('{pf}'), Paths);
  CollectFolderPythons(ExpandConstant('{pf32}'), Paths);
  CollectFolderPythons(ExpandConstant('{sd}'), Paths);
  { The newer Python install manager exposes the interpreter as bin\python.exe. }
  AppendPythonPath(Paths, ExpandConstant('{localappdata}\Python\bin\python.exe'));
end;

function PythonRuntimeComplete(Exe: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec(Exe, '-c "import sys,PySide6,requests,cryptography;' +
                'sys.exit(0 if sys.version_info[:2]>=(3,11) else 41)"', '',
          SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode = 0);
end;

function DetectPythonRuntime: Boolean;
var
  Paths: TStrings;
  Index: Integer;
begin
  Result := False;
  Paths := TStringList.Create;
  try
    CollectPythonPaths(Paths);
    for Index := 0 to Paths.Count - 1 do
      if PythonRuntimeComplete(Paths[Index]) then
      begin
        Log('IDM: usable Python runtime found at ' + Paths[Index]);
        Result := True;
        Exit;
      end;
    Log('IDM: no Python 3.11+ runtime providing requirements.txt was found.');
  finally
    Paths.Free;
  end;
end;

{ Check function for the pydeps task: the option is only offered when the
  runtime listed in the project brief is actually missing. }
function PythonRuntimeMissing(): Boolean;
begin
  if not PythonRuntimeChecked then
  begin
    PythonRuntimeFound := DetectPythonRuntime();
    PythonRuntimeChecked := True;
  end;
  Result := (not PythonRuntimeFound) and (not HasSwitch('/NOPYDEPS'));
end;

function ShouldInstallPythonDeps(): Boolean;
begin
  Result := WizardIsTaskSelected('pydeps') or
            (HasSwitch('/PYDEPS') and not HasSwitch('/NOPYDEPS'));
end;

function PowerShellExe(): String;
begin
  Result := ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

procedure InstallPythonDeps;
var
  Script, Requirements, LogPath, Params, StartedText: String;
  ResultCode: Integer;
  Started: Boolean;
begin
  Script := ExpandConstant('{app}\tools\Install-PythonDeps.ps1');
  Requirements := ExpandConstant('{app}\tools\requirements.txt');
  LogPath := ExpandConstant('{%TEMP}');
  if LogPath = '' then
    LogPath := ExpandConstant('{tmp}');
  LogPath := TrimTrailingSlashes(LogPath) + '\{#PythonDepsLog}';

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '"' +
            ' -RequirementsFile "' + Requirements + '"' +
            ' -LogPath "' + LogPath + '"' +
            ' -InstallerUrl "{#PythonInstallerUrl}"' +
            ' -ExpectedSha256 "{#PythonInstallerSha256}"';
  Log('IDM: starting the Python runtime bootstrap; log: ' + LogPath);
  { The console is shown so that the download and the pip install report
    progress; a silent install keeps it hidden. }
  if WizardSilent then
    Started := Exec(PowerShellExe(), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
  else
    Started := Exec(PowerShellExe(), Params, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  if Started then
    StartedText := 'Yes'
  else
    StartedText := 'No';

  if (not Started) or ((ResultCode <> 0) and (ResultCode <> 10)) then
  begin
    Log('IDM: the Python runtime bootstrap failed (PowerShell started=' +
        StartedText + ', exit code ' + IntToStr(ResultCode) + ').');
    if not WizardSilent then
      MsgBox('IDM was installed, but the Python runtime and its packages could not be '
             + 'set up automatically (exit code ' + IntToStr(ResultCode) + ').'
             + Chr(13) + Chr(10) + Chr(13) + Chr(10)
             + 'Check ' + LogPath + ' for details. To retry manually, run:'
             + Chr(13) + Chr(10)
             + 'powershell -ExecutionPolicy Bypass -File "' + Script + '"'
             + Chr(13) + Chr(10) + Chr(13) + Chr(10)
             + 'IDM.exe itself does not need Python; it runs from the bundled runtime.',
             mbInformation, MB_OK);
  end else
    Log('IDM: the Python runtime bootstrap finished (exit code '
        + IntToStr(ResultCode) + ').');
end;

{ Compile with /DPyDepsProbe to test interpreter detection without installing
  anything: the setup writes a report to %TEMP%\idm-pydeps-probe.txt and aborts. }
#ifdef PyDepsProbe
function InitializeSetup(): Boolean;
var
  Paths: TStrings;
  Index: Integer;
  Report, State: String;
begin
  Paths := TStringList.Create;
  try
    CollectPythonPaths(Paths);
    Report := 'candidates=' + IntToStr(Paths.Count) + #13#10;
    for Index := 0 to Paths.Count - 1 do
    begin
      if PythonRuntimeComplete(Paths[Index]) then
        State := 'usable'
      else
        State := 'missing packages or too old';
      Report := Report + State + ' - ' + Paths[Index] + #13#10;
    end;
    if PythonRuntimeMissing() then
      Report := Report + 'RESULT: prerequisite task would be offered'
    else
      Report := Report + 'RESULT: runtime complete, task hidden';
    SaveStringToFile(ExpandConstant('{%TEMP}\idm-pydeps-probe.txt'), Report, False);
  finally
    Paths.Free;
  end;
  Result := False;
end;
#endif

{ ---------------------------------------------------------------------------
  Browser integration
  --------------------------------------------------------------------------- }

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

function IsBraveInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\BraveSoftware\Brave-Browser\Application\brave.exe')) or
    FileExists(ExpandConstant('{pf32}\BraveSoftware\Brave-Browser\Application\brave.exe')) or
    FileExists(ExpandConstant('{localappdata}\BraveSoftware\Brave-Browser\Application\brave.exe'));
end;

{ Opera's mainline browser lives under "Programs\Opera" for a per-user install
  and under "Opera\Opera" for the older system-wide layout. }
function IsOperaInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{localappdata}\Programs\Opera\opera.exe')) or
    FileExists(ExpandConstant('{localappdata}\Programs\Opera\launcher.exe')) or
    FileExists(ExpandConstant('{pf}\Opera\Opera\opera.exe')) or
    FileExists(ExpandConstant('{pf32}\Opera\Opera\opera.exe'));
end;

function BraveTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('brave');
end;

function OperaTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('opera');
end;

function NativeHostRegistryPath(Browser: String): String;
begin
  if Browser = 'chrome' then
    Result := 'Software\Google\Chrome\NativeMessagingHosts\{#NativeHostName}'
  else if Browser = 'edge' then
    Result := 'Software\Microsoft\Edge\NativeMessagingHosts\{#NativeHostName}'
  else if Browser = 'brave' then
    Result := 'Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{#NativeHostName}'
  else if Browser = 'opera' then
    Result := 'Software\Opera Software\Opera Stable\NativeMessagingHosts\{#NativeHostName}'
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

function BrowserTaskSelected(Browser: String): Boolean;
begin
  if Browser = 'chrome' then
    Result := ChromeTaskSelected()
  else if Browser = 'edge' then
    Result := EdgeTaskSelected()
  else if Browser = 'brave' then
    Result := BraveTaskSelected()
  else if Browser = 'opera' then
    Result := OperaTaskSelected()
  else
    Result := FirefoxTaskSelected();
end;

function BrowserInstalled(Browser: String): Boolean;
begin
  if Browser = 'chrome' then
    Result := IsChromeInstalled()
  else if Browser = 'edge' then
    Result := IsEdgeInstalled()
  else if Browser = 'brave' then
    Result := IsBraveInstalled()
  else if Browser = 'opera' then
    Result := IsOperaInstalled()
  else
    Result := IsFirefoxInstalled();
end;

function HasOwnRegistration(Browser: String): Boolean;
var
  SubKey: String;
  Manifest: String;
  Value: String;
begin
  SubKey := NativeHostRegistryPath(Browser);
  Manifest := ManifestPath(Browser);
  Result :=
    (RegQueryStringValue(HKCU, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0)) or
    (RegQueryStringValue(HKCU32, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0));
end;

{ A silent install is an update, not a fresh setup: it must never remove an
  existing registration just because /TASKS was not passed.  In that case the
  registration is kept and repaired when it already points at this install. }
function ShouldRegister(Browser: String): Boolean;
begin
  Result := BrowserInstalled(Browser) and
    (BrowserTaskSelected(Browser) or
     (WizardSilent and HasOwnRegistration(Browser)));
end;

function RegisterBrowser(Browser: String): Boolean;
var
  SubKey: String;
  Manifest: String;
  Value: String;
begin
  Result := WriteManifest(Browser);
  if not Result then
    Exit;
  SubKey := NativeHostRegistryPath(Browser);
  Manifest := ManifestPath(Browser);
  RegWriteStringValue(HKCU, SubKey, '', Manifest);
  RegWriteStringValue(HKCU32, SubKey, '', Manifest);
  if not ((RegQueryStringValue(HKCU, SubKey, '', Value) and
           (CompareText(Value, Manifest) = 0)) or
          (RegQueryStringValue(HKCU32, SubKey, '', Value) and
           (CompareText(Value, Manifest) = 0))) then
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
  Owned: Boolean;
begin
  SubKey := NativeHostRegistryPath(Browser);
  Manifest := ManifestPath(Browser);
  Owned := False;
  if RegQueryStringValue(HKCU, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0) then
  begin
    RegDeleteValue(HKCU, SubKey, '');
    Owned := True;
  end;
  if RegQueryStringValue(HKCU32, SubKey, '', Value) and
     (CompareText(Value, Manifest) = 0) then
  begin
    RegDeleteValue(HKCU32, SubKey, '');
    Owned := True;
  end;
  { Never delete a manifest that the registry does not point at: another
    registration (for example one written by scripts\register_native_host.py)
    may still be using its own copy. }
  if Owned then
    DeleteFile(Manifest);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if ShouldRegister('chrome') then
      RegisterBrowser('chrome')
    else if not WizardSilent then
      UnregisterBrowser('chrome');

    if ShouldRegister('edge') then
      RegisterBrowser('edge')
    else if not WizardSilent then
      UnregisterBrowser('edge');

    if ShouldRegister('firefox') then
      RegisterBrowser('firefox')
    else if not WizardSilent then
      UnregisterBrowser('firefox');

    if ShouldRegister('brave') then
      RegisterBrowser('brave')
    else if not WizardSilent then
      UnregisterBrowser('brave');

    if ShouldRegister('opera') then
      RegisterBrowser('opera')
    else if not WizardSilent then
      UnregisterBrowser('opera');

    if (not WizardSilent) and
       ((BrowserTaskSelected('chrome') and IsChromeInstalled()) or
        (BrowserTaskSelected('edge') and IsEdgeInstalled()) or
        (BrowserTaskSelected('brave') and IsBraveInstalled()) or
        (BrowserTaskSelected('opera') and IsOperaInstalled())) then
      MsgBox(
        'The IDM native host is registered, but the IDM Video Assistant is not installed automatically.' + #13#10 + #13#10 +
        'To finish browser integration:' + #13#10 +
        '1. Open chrome://extensions, edge://extensions, brave://extensions or opera://extensions.' + #13#10 +
        '2. Turn on Developer mode.' + #13#10 +
        '3. Choose Load unpacked and select:' + #13#10 +
        ExpandConstant('{app}') + '\BrowserExtension\IDMVideoAssistant' + #13#10 + #13#10 +
        'See BrowserExtension\IDMVideoAssistant\InstallationGuide.md for details. IDM never installs browser extensions silently.',
        mbInformation, MB_OK);

    { Last, because it can take a few minutes and must not delay or undo the
      installation of IDM itself. }
    if ShouldInstallPythonDeps() then
      InstallPythonDeps;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    UnregisterBrowser('chrome');
    UnregisterBrowser('edge');
    UnregisterBrowser('firefox');
    UnregisterBrowser('brave');
    UnregisterBrowser('opera');
  end;
end;

function HasRemoveDataSwitch(): Boolean;
begin
  Result := HasSwitch('/REMOVEDATA');
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
