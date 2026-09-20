# Cria o atalho "Vellum" na Area de Trabalho, com icone proprio.
#
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
#
# Use -NoDesktop para criar so no Menu Iniciar, ou -StartMenu para os dois.

param(
    [switch]$NoDesktop,
    [switch]$StartMenu
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$icon = Join-Path $root 'assets\vellum.ico'

# Preferimos apontar direto para o .exe do aplicativo: ele e "windowed", ou
# seja, abre a janela sem nenhum console preto atras. O .bat fica de reserva.
$exe = Join-Path $root '.venv\Scripts\vellum-app.exe'
$bat = Join-Path $root 'Vellum.bat'
$target = if (Test-Path $exe) { $exe } else { $bat }

if (-not (Test-Path $target)) { throw "Nao encontrei o aplicativo. Instale o ambiente primeiro." }
if (-not (Test-Path $icon)) { Write-Warning "Icone ausente ($icon). Rode: python scripts\make_icon.py" }

function New-VellumShortcut([string]$Path) {
    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath       = $target
    $shortcut.WorkingDirectory = $root
    $shortcut.Description      = 'Extracao local de informacao de audio e video'
    if (Test-Path $icon) { $shortcut.IconLocation = $icon }
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Output "atalho criado: $Path"
}

if (-not $NoDesktop) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-VellumShortcut (Join-Path $desktop 'Vellum.lnk')
}

if ($StartMenu) {
    $programs = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
    New-VellumShortcut (Join-Path $programs 'Vellum.lnk')
}
