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
SetupIconFile=colloquia.ico
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
Type: filesandordirs; Name: "{localappdata}\Colloquia\cuda"; Check: not WantsGpu

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\Colloquia\cuda"

[Registry]
Root: HKCU; Subkey: "Software\Colloquia"; ValueType: dword; ValueName: "GpuSupport"; ValueData: "{code:GpuSupport}"; Flags: uninsdeletekey

[Files]
Source: "..\dist\Colloquia\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Colloquia"; Filename: "{app}\Colloquia.exe"
Name: "{autodesktop}\Colloquia"; Filename: "{app}\Colloquia.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Colloquia.exe"; Description: "{cm:LaunchProgram,Colloquia}"; Flags: nowait postinstall skipifsilent

[Code]
var
  GpuPage: TInputOptionWizardPage;

function HasNvidia: Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\nvcuda.dll'));
end;

function HasCuda: Boolean;
var
  F: TFindRec;
begin
  Result := FindFirst(ExpandConstant('{localappdata}\Colloquia\cuda\nvidia\cudnn\bin\cudnn64_*.dll'), F);
  if Result then
    FindClose(F);
end;

function WantsGpu: Boolean;
begin
  Result := HasNvidia and (HasCuda or GpuPage.Values[0]);
end;

function GpuSupport(Param: String): String;
begin
  if WantsGpu then
    Result := '1'
  else
    Result := '0';
end;

procedure InitializeWizard;
begin
  GpuPage := CreateInputOptionPage(wpSelectTasks,
    'Aceleración con tu tarjeta gráfica NVIDIA',
    'Hemos detectado una GPU NVIDIA en este equipo.',
    'Colloquia puede usarla para transcribir las sesiones mucho más rápido:' + #13#10#13#10 +
    '  •  Una sesión de una hora se procesa en unos 5–10 minutos, en lugar de 30–60 con el procesador.' + #13#10 +
    '  •  El ordenador no se queda bloqueado ni se calienta tanto mientras transcribe.' + #13#10 +
    '  •  Puedes usar el modelo más preciso sin esperas largas.' + #13#10#13#10 +
    'Requiere descargar unos 1,3 GB la primera vez que abras Colloquia. Se descarga en segundo plano y, mientras tanto, la aplicación funciona con normalidad.',
    False, False);
  GpuPage.Add('Descargar el soporte para GPU NVIDIA (recomendado)');
  GpuPage.Values[0] := GetPreviousData('GpuSupport', '1') = '1';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = GpuPage.ID) and (not HasNvidia or HasCuda);
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'GpuSupport', GpuSupport(''));
end;
