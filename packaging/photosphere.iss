; Inno Setup script for PhotoSphere AI.
; Build (after PyInstaller has produced dist\PhotoSphere\):
;   iscc /DAppVersion=2.0.0 packaging\photosphere.iss
; Produces packaging\Output\PhotoSphere-Setup-<version>.exe
;
; The version is passed in by CI from utils/version.py so it is stated once.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=PhotoSphere AI
AppVersion={#AppVersion}
AppPublisher=PhotoSphere
DefaultDirName={autopf}\PhotoSphere AI
DefaultGroupName=PhotoSphere AI
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=PhotoSphere-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user data (thumbnails, DB config) lives in %LOCALAPPDATA%\PhotoSphere,
; so the app never needs to write under Program Files.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The entire PyInstaller one-dir output.
Source: "..\dist\PhotoSphere\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PhotoSphere AI"; Filename: "{app}\PhotoSphere.exe"
Name: "{group}\Uninstall PhotoSphere AI"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PhotoSphere AI"; Filename: "{app}\PhotoSphere.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PhotoSphere.exe"; Description: "Launch PhotoSphere AI"; Flags: nowait postinstall skipifsilent
