; One-click installer for TextFixer (AutoHotkey version, Ollama).
; Installs TextFixer.exe for the current user (no admin rights), installs Ollama if it is
; missing, downloads the AI model and can start TextFixer with Windows.
;
; Built by .github/workflows/ahk-installer.yml, which first compiles build\TextFixer.exe:
;   Ahk2Exe.exe /in TextFixer.ahk /out build\TextFixer.exe /base AutoHotkey64.exe
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\TextFixer.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "TextFixer"
#define OllamaUrl "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"

[Setup]
AppId={{B3F1A6D2-8C47-4E19-A0B5-2D6E9C7F1A84}
AppName={#AppName} (AutoHotkey)
AppVersion={#AppVersion}
AppPublisher=TextFixer
DefaultDirName={localappdata}\Programs\{#AppName}-AHK
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=TextFixer-AHK-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TextFixer.exe
UninstallDisplayName={#AppName} (AutoHotkey)
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start TextFixer when Windows starts"

[Files]
Source: "..\build\TextFixer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.example.ini"; DestDir: "{app}"; Flags: ignoreversion
; A new install starts with Ollama + Qwen3 4B; an existing config.ini is kept
Source: "..\config.example.ini"; DestDir: "{app}"; DestName: "config.ini"; Flags: onlyifdoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\TextFixer.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
; Same shortcut as the tray menu's "Start with Windows", so that tick stays in step
Name: "{userstartup}\TextFixer"; Filename: "{app}\TextFixer.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\TextFixer.exe"; Description: "Start TextFixer now"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\config.ini"
Type: files; Name: "{userstartup}\TextFixer.lnk"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  OllamaDownloaded: Boolean;
  NewConfig: Boolean;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);
end;

{ Where Ollama is installed, or '' if it is not }
function OllamaPath: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe');
  if not FileExists(Result) then
    Result := FileSearch('ollama.exe', GetEnv('PATH'));
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + MemoTasksInfo + NewLine + NewLine;
  Result := Result + 'Also:' + NewLine;
  if OllamaPath = '' then
    Result := Result + Space + 'Download and install Ollama (runs the AI model on this PC)' + NewLine
  else
    Result := Result + Space + 'Ollama is already installed: it will be used' + NewLine;
  Result := Result + Space + 'Download the AI model (Qwen3 4B, about 2.5 GB) if it is not there yet' + NewLine;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and (OllamaPath = '') then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#OllamaUrl}', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        OllamaDownloaded := True;
      except
        if DownloadPage.AbortedByUser then
          Log('Ollama download cancelled')
        else
          SuppressibleMsgBox('Could not download Ollama:' + #13#10 + AddPeriod(GetExceptionMessage) + #13#10#13#10 +
            'TextFixer will still be installed. Install Ollama later from https://ollama.com/download.',
            mbError, MB_OK, IDOK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

{ True once the Ollama server answers (ollama list succeeds) }
function OllamaRunning(const Exe: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(Exe, 'list', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ Start Ollama if it isn't running and wait up to 30 seconds for it }
function StartOllama(const Exe: String): Boolean;
var
  ResultCode, I: Integer;
  TrayApp: String;
begin
  Result := OllamaRunning(Exe);
  if Result then
    Exit;
  TrayApp := ExtractFilePath(Exe) + 'ollama app.exe';
  if FileExists(TrayApp) then
    Exec(TrayApp, '', '', SW_HIDE, ewNoWait, ResultCode)
  else
    Exec(Exe, 'serve', '', SW_HIDE, ewNoWait, ResultCode);
  for I := 1 to 30 do
  begin
    Sleep(1000);
    if OllamaRunning(Exe) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

{ Download the first model that works (the exact name can differ between Ollama versions).
  The console window shows Ollama's own progress bar. Returns the model name, or ''. }
function PullModel(const Exe: String): String;
var
  Models: TArrayOfString;
  ResultCode, I: Integer;
begin
  Result := '';
  SetArrayLength(Models, 3);
  Models[0] := 'qwen3:4b-instruct-2507-q4_K_M';
  Models[1] := 'qwen3:4b-instruct';
  Models[2] := 'qwen3:4b';
  for I := 0 to GetArrayLength(Models) - 1 do
  begin
    WizardForm.StatusLabel.Caption := 'Downloading the AI model (' + Models[I] + '). This can take several minutes...';
    if Exec(ExpandConstant('{cmd}'), '/c title Downloading the AI model for TextFixer && "' + Exe + '" pull ' + Models[I],
            '', SW_SHOW, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    begin
      Result := Models[I];
      Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Exe, Model: String;
begin
  if CurStep = ssInstall then
    NewConfig := not FileExists(ExpandConstant('{app}\config.ini'));
  if CurStep <> ssPostInstall then
    Exit;

  if OllamaDownloaded then
  begin
    WizardForm.StatusLabel.Caption := 'Installing Ollama...';
    if not Exec(ExpandConstant('{tmp}\OllamaSetup.exe'), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
                SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      SuppressibleMsgBox('Ollama could not be installed (code ' + IntToStr(ResultCode) + ').' + #13#10 +
        'Install it later from https://ollama.com/download.', mbError, MB_OK, IDOK);
  end;

  Exe := OllamaPath;
  Model := '';
  WizardForm.StatusLabel.Caption := 'Starting Ollama...';
  if (Exe <> '') and StartOllama(Exe) then
    Model := PullModel(Exe);
  if Model = '' then
    SuppressibleMsgBox('The AI model is not ready yet.' + #13#10 +
      'Start TextFixer: it offers to download the model, or use Settings > Download (the tray icon menu).',
      mbInformation, MB_OK, IDOK)
  else if NewConfig then
    { Use the model name that actually downloaded }
    SetIniString('Settings', 'MODEL', Model, ExpandConstant('{app}\config.ini'));
end;
