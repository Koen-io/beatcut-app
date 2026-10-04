; Windows-installer voor BeatCut, met Inno Setup.
;
;     ISCC.exe installer\beatcut.iss
;
; Inno Setup staat op de GitHub-runners voorgeïnstalleerd; lokaal haal je hem
; van jrsoftware.org. Levert één `BeatCut-setup-<versie>.exe` op die de
; gebruiker dubbelklikt.
;
; Bewust geen MSI. Een MSI is voor uitrol via groepsbeleid; die maken we pas
; als de IT-afdeling van het werk daarom vraagt. Voor een mens die het zelf
; installeert is een setup.exe eenvoudiger en herkenbaarder.

#define Naam "BeatCut"
; Eén plek voor de versie: hou dit gelijk aan engine/cve/__init__.py
#define Versie "0.2.0"
#define Uitgever "Koen Schelvis"
#define Exe "beatcut-engine.exe"

[Setup]
AppId={{B3A7C1E2-9F41-4D8A-A6C3-BEA7C0DE0001}
AppName={#Naam}
AppVersion={#Versie}
AppVerName={#Naam} {#Versie}
AppPublisher={#Uitgever}
DefaultDirName={autopf}\{#Naam}
DefaultGroupName={#Naam}
OutputDir=uit
OutputBaseFilename={#Naam}-setup-{#Versie}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Geen beheerdersrechten nodig: installeren in de eigen gebruikersmap is
; genoeg en scheelt een UAC-venster dat mensen laat aarzelen.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#Exe}

[Languages]
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "bureaublad"; Description: "Snelkoppeling op het bureaublad"; \
  GroupDescription: "Extra:"

[Files]
; De hele ingevroren engine, inclusief studio/, styles/ en brands/.
Source: "uit\beatcut-engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Naam}"; Filename: "{app}\{#Exe}"; Parameters: "studio"
Name: "{autodesktop}\{#Naam}"; Filename: "{app}\{#Exe}"; Parameters: "studio"; \
  Tasks: bureaublad

[Run]
Filename: "{app}\{#Exe}"; Parameters: "studio"; \
  Description: "{#Naam} nu openen"; Flags: nowait postinstall skipifsilent
