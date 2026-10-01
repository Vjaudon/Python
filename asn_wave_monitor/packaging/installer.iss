#define AppName "ASN Wave Monitor"
#define AppVersion "1.0.0"

#ifndef AppSource
  #error AppSource must be supplied by build_installer.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_installer.ps1
#endif

[Setup]
AppId={{9CB97C4A-3D24-4A3B-81C9-B7DDAF56A832}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Alcatel Submarine Networks
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\ASN Wave Monitor.exe
OutputDir={#OutputDir}
OutputBaseFilename=ASN-Wave-Monitor-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=yes
SetupLogging=yes

[Dirs]
Name: "{app}\_internal\data"

[Files]
Source: "{#AppSource}\ASN Wave Monitor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSource}\_internal\*"; DestDir: "{app}\_internal"; Excludes: "config.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#AppSource}\_internal\config.json"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\ASN Wave Monitor.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\ASN Wave Monitor.exe"; Description: "Démarrer ASN Wave Monitor"; Flags: nowait postinstall skipifsilent