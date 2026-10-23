; One-click installer for TextFixer (Python, Ollama).
; Installs TextFixer for the current user (no admin rights), installs Ollama if it is missing,
; downloads the AI model (TextFixerCLI.exe setup) and can start TextFixer with Windows.
;
; Built by .github/workflows/installer.yml. By hand, after build_exe.bat:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\TextFixer.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "TextFixer"
#define OllamaUrl "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"

[Setup]
AppId={{6E2B7C4A-3F1D-4B8E-9A52-7C0D1E4F8A93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=TextFixer
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=TextFixer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TextFixer.exe
UninstallDisplayName={#AppName}
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start TextFixer when Windows starts"

[Files]
Source: "..\dist\TextFixer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\TextFixer.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TextFixer"; \
  ValueData: """{app}\TextFixer.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\TextFixer.exe"; Description: "Start TextFixer now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\config.ini"
Type: files; Name: "{app}\textfixer.log"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  OllamaDownloaded: Boolean;

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

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
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

  { Starts Ollama if needed, downloads the model with a progress display and writes config.ini }
  WizardForm.StatusLabel.Caption := 'Downloading the AI model. This can take several minutes...';
  if not Exec(ExpandConstant('{app}\TextFixerCLI.exe'), 'setup --pause', ExpandConstant('{app}'),
              SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    SuppressibleMsgBox('The AI model is not ready yet.' + #13#10 +
      'Start TextFixer, then use Settings > Download model (the tray icon menu).', mbInformation, MB_OK, IDOK);
end;
