param(
    [string]$CC = "clang"
)

$ErrorActionPreference = "Stop"

# 本脚本位于 OpenCamera_c/c_bridge/，仓库根目录为上级的上级
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$cModel = Join-Path $repoRoot "c_model"
$outDll = Join-Path $scriptDir "c_model_bridge.dll"

Write-Host "Building $outDll from $cModel"

& $CC -O2 -Wall -std=c99 -shared `
    -I $cModel `
    -o $outDll `
    (Join-Path $cModel "config.c") `
    (Join-Path $cModel "sampling.c") `
    (Join-Path $cModel "gaussian.c") `
    (Join-Path $cModel "clip.c") `
    (Join-Path $cModel "compress.c") `
    (Join-Path $cModel "hist_eq.c") `
    (Join-Path $cModel "color.c") `
    (Join-Path $scriptDir "bridge.c")

if ($LASTEXITCODE -ne 0) {
    Write-Error "clang 编译失败，退出码 $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Done: $outDll"
