; Inno Setup installer script for NitroMaster Pro Control Center
; Build: iscc installer\nitromaster.iss   (after build.bat produced dist\NitroMasterPro.exe)

#define MyAppName "NitroMaster Pro Control Center"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "NitroMaster"
#define MyAppExeName "NitroMasterPro.exe"

[Setup]
AppId={{7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NitroMasterPro
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer\Output
OutputBaseFilename=NitroMasterPro-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start NitroMaster at login (restores fan/keyboard state)"; GroupDescription: "Startup:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "NitroMasterPro"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent
