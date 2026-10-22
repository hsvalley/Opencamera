param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

# 本脚本位于 OpenCamera_c/python/，仓库根目录为上级的上级
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$specPath = Join-Path $scriptDir "infrared_camera_player.spec"

Write-Host "Building onefile InfraredCameraPlayerC (C model) from $repoRoot"

Push-Location $repoRoot
try {
    & $PythonExe -m PyInstaller --noconfirm --clean $specPath
} finally {
    Pop-Location
}
