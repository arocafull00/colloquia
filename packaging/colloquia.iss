#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef OutputName
  #define OutputName "Colloquia-" + AppVersion + "-windows-setup"
#endif

[Setup]
AppId={{2736072A-B37D-442F-A290-ED644DDDC9D2}
AppName=Colloquia
AppVersion={#AppVersion}
AppPublisher=Colloquia
DefaultDirName={autopf}\Colloquia
DefaultGroupName=Colloquia
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=ColloquiaSingleInstance
UninstallDisplayIcon={app}\Colloquia.exe
OutputDir=..\dist
OutputBaseFilename={#OutputName}
Compression=lzma2
WizardStyle=modern

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Colloquia\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Colloquia"; Filename: "{app}\Colloquia.exe"
Name: "{autodesktop}\Colloquia"; Filename: "{app}\Colloquia.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Colloquia.exe"; Description: "{cm:LaunchProgram,Colloquia}"; Flags: nowait postinstall skipifsilent
