param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$specPath = Join-Path $PSScriptRoot "infrared_camera_player.spec"

Write-Host "Building InfraredCameraPlayer from $repoRoot"

Push-Location $repoRoot
try {
    & $PythonExe -m PyInstaller --noconfirm --clean $specPath
} finally {
    Pop-Location
}
