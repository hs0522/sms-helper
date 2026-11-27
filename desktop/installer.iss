; 마래푸 문자 도우미 — 윈도우 미니 위젯 Inno Setup 스크립트
; 빌드: ISCC.exe desktop\installer.iss
;   (PyInstaller 가 만든 dist\MaraepuSmsHelper 폴더를 그대로 묶는다)

#define AppName "마래푸 문자 도우미"
#define AppExe "MaraepuSmsHelper.exe"

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef SourceDir
  #define SourceDir "..\dist\MaraepuSmsHelper"
#endif

[Setup]
AppId={{D4F28904-81F8-4A15-8973-1E3385239EC0}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=마래푸중앙부동산
DefaultDirName={autopf}\MaraepuSmsHelper
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=MaraepuSmsHelper-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
DisableWelcomePage=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 설치를 마치면 exe 안의 새 아이콘이 바탕화면·작업표시줄에 바로 보이도록 윈도우 아이콘 캐시를 새로고친다.
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden nowait skipifdoesntexist
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  Msg: String;
begin
  Result := True;
  if not (DirExists(ExpandConstant('{commonpf}\Microsoft\EdgeWebView\Application')) or
          DirExists(ExpandConstant('{commonpf32}\Microsoft\EdgeWebView\Application'))) then
  begin
    Msg := '이 프로그램은 Microsoft Edge WebView2 런타임을 사용합니다.' + #13#10 +
           '윈도우 11에는 기본으로 들어 있어 따로 설치할 것이 없습니다.' + #13#10 + #13#10 +
           '설치는 그대로 진행됩니다. 설치 후 앱 창이 비어 있으면 아래 주소에서' + #13#10 +
           'WebView2 런타임을 설치해 주세요.' + #13#10 +
           'https://developer.microsoft.com/microsoft-edge/webview2/';
    MsgBox(Msg, mbInformation, MB_OK);
  end;
end;
