# TASK-209 lane C (issue #75): Windows x86-64 zip variant of the MVP v0
# distributable — the Windows counterpart of scripts/package_mvp.sh.
#
# Product decision on #75 (2026-07-26): WINDOWS-ONLY. run.bat is THE
# entrypoint; macOS packaging no longer exists anywhere; the Linux tarball
# from package_mvp.sh remains a dev/CI-only artifact.
#
# Layout mirrors the tarball: web bundle + local API + real PoB calc engine
# + launcher. Output: dist/poe-upgrade-advisor-v0-<sha>-windows-x64.zip.
#
# ENGINE RUNTIME: the pinned Windows Lua runtime (lane A:
# engine/runtime/build-windows.ps1, CI job windows-runtime-build) ships
# PREBUILT — testers need no compiler. Pass its directory via -RuntimeDir
# (must contain bin/luajit.exe, bin/lua51.dll, lib/lua/5.1/lua-utf8.dll,
# manifest). Without -RuntimeDir the zip gets an explicit STUB runtime dir:
# the launcher then stops with the honest "engine cannot start" message
# (doctrine I5) instead of guessing or failing mysteriously.
#
# Packaging-machine prerequisites (NOT tester prerequisites): npm, git.
# Testers need only Python 3.10+ (py launcher preferred, python3 fallback).
#
# OVERLAY: pass TASK-215-S1's packaged Windows app directory via -OverlayDir.
# Without it, the zip gets an explicit overlay stub and the launcher reports
# that the web app remains available instead of failing mysteriously.
#
# Usage: scripts/package_mvp_windows.ps1 [-SkipWebBuild] [-RuntimeDir PATH] [-OverlayDir PATH]
[CmdletBinding()]
param(
    [switch] $SkipWebBuild,
    [string] $RuntimeDir,
    [string] $OverlayDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)] [string] $FilePath,
        [Parameter(Mandatory = $true)] [string[]] $ArgumentList
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "package_mvp_windows: $FilePath $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# --- Web bundle -------------------------------------------------------------
if (-not $SkipWebBuild) {
    Write-Host "== building web bundle (npm ci && npm run build)"
    Push-Location (Join-Path $Root "web")
    try {
        Invoke-Native "npm.cmd" @("ci", "--no-audit", "--no-fund")
        Invoke-Native "npm.cmd" @("run", "build")
    }
    finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "web/dist/index.html") -PathType Leaf)) {
    throw "error: web/dist missing; run without -SkipWebBuild"
}

# --- Vendored PathOfBuilding (packaging machine only) ------------------------
$Vendor = Join-Path $Root "engine/vendor/PathOfBuilding"
if (-not (Test-Path -LiteralPath (Join-Path $Vendor "src/HeadlessWrapper.lua") -PathType Leaf)) {
    Write-Host "== initializing vendored PathOfBuilding submodule"
    Invoke-Native "git.exe" @("submodule", "update", "--init", "engine/vendor/PathOfBuilding")
}

# --- Runtime: lane A artifact or explicit stub -------------------------------
$RuntimeBin = $null
$RuntimeLib = $null
$RuntimeManifest = $null
$StubRuntime = $false
if (-not [string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $RuntimeSource = [System.IO.Path]::GetFullPath($RuntimeDir)
    $RuntimeBin = Join-Path $RuntimeSource "bin"
    $RuntimeLib = Join-Path $RuntimeSource "lib"
    $RuntimeManifest = Join-Path $RuntimeSource "manifest"
    $required = @(
        (Join-Path $RuntimeBin "luajit.exe"),
        (Join-Path $RuntimeBin "lua51.dll"),
        (Join-Path $RuntimeLib "lua/5.1/lua-utf8.dll"),
        $RuntimeManifest
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "error: -RuntimeDir is not a lane A Windows runtime: missing $path"
        }
    }
    Write-Host "== wiring pinned Windows engine runtime from $RuntimeSource"
}
else {
    $StubRuntime = $true
    Write-Host "== no -RuntimeDir given: engine runtime ships as an explicit STUB"
    Write-Host "   (honest 'engine cannot start' failure until lane A's artifact is wired)"
}

# --- Overlay: TASK-215-S1 packaged app or explicit stub --------------------
$OverlaySource = $null
$StubOverlay = $false
if (-not [string]::IsNullOrWhiteSpace($OverlayDir)) {
    $OverlaySource = [System.IO.Path]::GetFullPath($OverlayDir)
    $OverlayExe = Join-Path $OverlaySource "PoEUpgradeAdvisorOverlay.exe"
    if (-not (Test-Path -LiteralPath $OverlayExe -PathType Leaf)) {
        throw "error: -OverlayDir is not the packaged Windows overlay: missing $OverlayExe"
    }
    Write-Host "== wiring packaged Windows overlay from $OverlaySource"
}
else {
    $StubOverlay = $true
    Write-Host "== no -OverlayDir given: overlay ships as an explicit STUB"
    Write-Host "   (launcher honestly reports no overlay; the web app remains available)"
}

$Name = "poe-upgrade-advisor-v0"
$Stage = Join-Path $Root "dist/$Name"
$Sha = (& git.exe rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "package_mvp_windows: git rev-parse failed" }

Write-Host "== staging $Stage"
if (Test-Path -LiteralPath $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $Stage "web") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "engine/vendor/PathOfBuilding") | Out-Null

# API + data (runtime dep: pyyaml only; see packaging/run.bat).
Copy-Item -LiteralPath (Join-Path $Root "server") -Destination $Stage -Recurse
Copy-Item -LiteralPath (Join-Path $Root "assumptions") -Destination $Stage -Recurse

# Real engine: worker entrypoint, Lua adapter, preset/timeless helpers the
# server imports and the worker shells out to.
$engineStage = Join-Path $Stage "engine"
foreach ($file in @("pobcalc", "pobcalc.lua", "preset_config.py", "timeless_cache.py")) {
    Copy-Item -LiteralPath (Join-Path $Root "engine/$file") -Destination $engineStage
}

# Pinned Lua runtime, PREBUILT — or the explicit stub (see header).
$runtimeStage = Join-Path $engineStage ".runtime"
New-Item -ItemType Directory -Path $runtimeStage -Force | Out-Null
if ($StubRuntime) {
    New-Item -ItemType Directory -Path (Join-Path $runtimeStage "bin") -Force | Out-Null
    $stubText = @"
PoE Upgrade Advisor v0 — ENGINE RUNTIME STUB (TASK-209 lane C / issue #75)

This directory is where the pinned Windows x86-64 Lua runtime belongs:
  bin/luajit.exe, bin/lua51.dll, lib/lua/5.1/lua-utf8.dll, manifest
It is a stub because this zip was packaged without lane A's runtime
artifact (CI job 'windows-runtime-build', artifact
pobcalc-runtime-windows-x64-luajit-<rev>-luautf8-<rev>).

Deliberate, not broken (doctrine I5): with no runtime, the launcher stops
with an honest 'engine cannot start' message instead of guessing verdicts.
Repackage with: scripts/package_mvp_windows.ps1 -RuntimeDir <artifact dir>
"@
    [System.IO.File]::WriteAllText(
        (Join-Path $runtimeStage "bin/RUNTIME-STUB.txt"),
        $stubText,
        [System.Text.UTF8Encoding]::new($false))
}
else {
    Copy-Item -LiteralPath $RuntimeBin -Destination $runtimeStage -Recurse
    Copy-Item -LiteralPath $RuntimeLib -Destination $runtimeStage -Recurse
    Copy-Item -LiteralPath $RuntimeManifest -Destination $runtimeStage
}

# Packaged Electron app, including its DLLs/resources, or an explicit stub.
# packaging/launch.py resolves the executable at overlay/PoEUpgradeAdvisorOverlay.exe.
$overlayStage = Join-Path $Stage "overlay"
New-Item -ItemType Directory -Path $overlayStage -Force | Out-Null
if ($StubOverlay) {
    $overlayStubText = @"
PoE Upgrade Advisor v0 — OVERLAY STUB (TASK-215-S3)

This directory is where TASK-215-S1's packaged Windows overlay belongs:
  PoEUpgradeAdvisorOverlay.exe and the rest of its packaged app folder
It is a stub because this zip was packaged without -OverlayDir. The launcher
will report that no overlay is included and the web app remains available.
Repackage with: scripts/package_mvp_windows.ps1 -OverlayDir <overlay/dist-win/PoEUpgradeAdvisorOverlay-win32-x64>
"@
    [System.IO.File]::WriteAllText(
        (Join-Path $overlayStage "OVERLAY-STUB.txt"),
        $overlayStubText,
        [System.Text.UTF8Encoding]::new($false))
}
else {
    Get-ChildItem -LiteralPath $OverlaySource -Force |
        Copy-Item -Destination $overlayStage -Recurse -Force
}

# Vendored PoB: headless calc needs src/ and runtime/lua only. TreeData GUI
# sprites (*.png/*.jpg/*.webp, ~400M) are excluded — HeadlessWrapper stubs
# image handles and PoB skips missing sprites without any network fetch
# (main.allowTreeDownload is disabled upstream). All tree.lua / sprites.lua /
# Assets.lua data files for EVERY tree version ship so any tester build
# imports. runtime/{*.dll, SimpleGraphic} is the Windows GUI host — not used
# headless.
$spriteExtensions = @(".png", ".jpg", ".webp")
$srcRoot = Join-Path $Vendor "src"
$srcStage = Join-Path $Stage "engine/vendor/PathOfBuilding/src"
Get-ChildItem -LiteralPath $srcRoot -Recurse -File | ForEach-Object {
    # Normalize separators so the TreeData filter is platform-safe.
    $relative = $_.FullName.Substring($srcRoot.Length).TrimStart('\', '/') -replace '/', '\'
    $isTreeDataSprite = $relative.StartsWith("TreeData\") -and
        ($spriteExtensions -contains $_.Extension.ToLowerInvariant())
    if (-not $isTreeDataSprite) {
        $destination = Join-Path $srcStage $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
}
Copy-Item -LiteralPath (Join-Path $Vendor "runtime/lua") `
    -Destination (Join-Path $Stage "engine/vendor/PathOfBuilding/runtime/lua") -Recurse
Copy-Item -LiteralPath (Join-Path $Vendor "LICENSE.md") `
    -Destination (Join-Path $Stage "engine/vendor/PathOfBuilding")

# Prebuilt web bundle — testers never touch npm.
Copy-Item -Path (Join-Path $Root "web/dist/*") -Destination (Join-Path $Stage "web") -Recurse -Force

# Launcher + tester docs. WINDOWS-ONLY (issue #75): run.bat is THE
# entrypoint; no unix entrypoints are staged into this zip.
New-Item -ItemType Directory -Path (Join-Path $Stage "packaging") | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "packaging/launch.py") -Destination (Join-Path $Stage "packaging")
Copy-Item -LiteralPath (Join-Path $Root "packaging/run.bat") -Destination (Join-Path $Stage "packaging")
Copy-Item -LiteralPath (Join-Path $Root "packaging/run.bat") -Destination $Stage
Copy-Item -LiteralPath (Join-Path $Root "packaging/README.txt") -Destination $Stage

# Never ship caches or a previous bootstrap venv.
@(Get-ChildItem -LiteralPath $Stage -Recurse -Directory -Force |
    Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq ".venv" }) |
    Remove-Item -Recurse -Force

$Zip = Join-Path $Root "dist/$Name-$Sha-windows-x64.zip"
if (Test-Path -LiteralPath $Zip) {
    Remove-Item -LiteralPath $Zip -Force
}
# ZipFile.CreateFromDirectory, not Compress-Archive: it includes dot-prefixed
# entries (engine/.runtime) on every platform — Compress-Archive silently
# drops "hidden" ones where the filesystem marks them so. The base directory
# is included, mirroring the tarball layout.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $Stage, $Zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
$size = "{0:N1} MB" -f ((Get-Item -LiteralPath $Zip).Length / 1MB)
Write-Host "== wrote $Zip ($size)"
Write-Host "   clean-room check: extract elsewhere, run.bat, open http://127.0.0.1:47791/"
if ($StubRuntime) {
    Write-Host "   NOTE: STUB runtime — engine honestly refuses to start until lane A's artifact is wired"
}
if ($StubOverlay) {
    Write-Host "   NOTE: STUB overlay — launcher reports no overlay; web app remains available"
}
