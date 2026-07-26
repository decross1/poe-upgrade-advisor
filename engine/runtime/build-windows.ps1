[CmdletBinding()]
param(
    [string] $Prefix
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LuaJitRepository = "https://github.com/LuaJIT/LuaJIT.git"
$LuaJitRevision = "a471ab78c7b670b4f92dae111fc3c96fb824c768"
$LuaUtf8Repository = "https://github.com/starwing/luautf8.git"
$LuaUtf8Revision = "08b0fc930f5a52eff36348ed1ea39aadfc697fa6"

$EngineRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Prefix)) {
    $Prefix = Join-Path $EngineRoot ".runtime"
}
if (-not [System.IO.Path]::IsPathFullyQualified($Prefix)) {
    throw "runtime build: -Prefix must be an absolute path"
}
$RuntimePrefix = [System.IO.Path]::GetFullPath($Prefix)

foreach ($CommandName in @("cl.exe", "cmd.exe", "git.exe")) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "runtime build: missing required command: $CommandName"
    }
}

$RuntimeManifest = (
    "luajit=$LuaJitRevision`n" +
    "lua-utf8=$LuaUtf8Revision`n"
)
$ManifestPath = Join-Path $RuntimePrefix "manifest"
$LuaJitPath = Join-Path $RuntimePrefix "bin/luajit.exe"
$LuaDllPath = Join-Path $RuntimePrefix "bin/lua51.dll"
$LuaUtf8Path = Join-Path $RuntimePrefix "lib/lua/5.1/lua-utf8.dll"
if (
    (Test-Path -LiteralPath $LuaJitPath -PathType Leaf) -and
    (Test-Path -LiteralPath $LuaDllPath -PathType Leaf) -and
    (Test-Path -LiteralPath $LuaUtf8Path -PathType Leaf) -and
    (Test-Path -LiteralPath $ManifestPath -PathType Leaf) -and
    ([System.IO.File]::ReadAllText($ManifestPath) -eq $RuntimeManifest)
) {
    Write-Host "runtime build: pinned Windows runtime already present at $RuntimePrefix"
    exit 0
}

if (Test-Path -LiteralPath $RuntimePrefix) {
    throw "runtime build: refusing to overwrite unmatched path: $RuntimePrefix"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,
        [Parameter(Mandatory = $true)]
        [string[]] $ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "runtime build: $FilePath failed with exit code $LASTEXITCODE"
    }
}

function Get-PinnedRevision {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Repository,
        [Parameter(Mandatory = $true)]
        [string] $Revision,
        [Parameter(Mandatory = $true)]
        [string] $Destination
    )

    Invoke-Native "git.exe" @("init", "-q", $Destination)
    Invoke-Native "git.exe" @("-C", $Destination, "remote", "add", "origin", $Repository)
    Invoke-Native "git.exe" @(
        "-C", $Destination, "fetch", "-q", "--depth", "1", "origin", $Revision
    )
    Invoke-Native "git.exe" @("-C", $Destination, "checkout", "-q", "--detach", "FETCH_HEAD")
    $ActualRevision = (
        Invoke-Native "git.exe" @("-C", $Destination, "rev-parse", "HEAD")
    ).Trim()
    if ($ActualRevision -ne $Revision) {
        throw "runtime build: revision mismatch for $Repository"
    }
}

$RuntimeParent = Split-Path -Parent $RuntimePrefix
[System.IO.Directory]::CreateDirectory($RuntimeParent) | Out-Null
$BuildRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "pobcalc-build-$([System.Guid]::NewGuid().ToString('N'))"
$RuntimeStage = Join-Path (
    $RuntimeParent
) ".pobcalc-runtime-$([System.Guid]::NewGuid().ToString('N'))"
[System.IO.Directory]::CreateDirectory($BuildRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($RuntimeStage) | Out-Null

try {
    $LuaJitSource = Join-Path $BuildRoot "LuaJIT"
    $LuaUtf8Source = Join-Path $BuildRoot "lua-utf8"
    Get-PinnedRevision $LuaJitRepository $LuaJitRevision $LuaJitSource
    Get-PinnedRevision $LuaUtf8Repository $LuaUtf8Revision $LuaUtf8Source

    Push-Location $LuaJitSource
    try {
        Invoke-Native "cmd.exe" @("/d", "/c", "call msvcbuild.bat")
    }
    finally {
        Pop-Location
    }

    $BinDirectory = Join-Path $RuntimeStage "bin"
    $ModuleDirectory = Join-Path $RuntimeStage "lib/lua/5.1"
    [System.IO.Directory]::CreateDirectory($BinDirectory) | Out-Null
    [System.IO.Directory]::CreateDirectory($ModuleDirectory) | Out-Null
    Copy-Item -LiteralPath (Join-Path $LuaJitSource "src/luajit.exe") -Destination $BinDirectory
    Copy-Item -LiteralPath (Join-Path $LuaJitSource "src/lua51.dll") -Destination $BinDirectory

    $LuaUtf8Module = Join-Path $ModuleDirectory "lua-utf8.dll"
    Push-Location $BuildRoot
    try {
        Invoke-Native "cl.exe" @(
            "/nologo",
            "/O2",
            "/LD",
            "/DLUA_BUILD_AS_DLL",
            "/I$(Join-Path $LuaJitSource 'src')",
            (Join-Path $LuaUtf8Source "lutf8lib.c"),
            "/link",
            "/OUT:$LuaUtf8Module",
            "/LIBPATH:$(Join-Path $LuaJitSource 'src')",
            "lua51.lib"
        )
    }
    finally {
        Pop-Location
    }
    Remove-Item -LiteralPath (
        [System.IO.Path]::ChangeExtension($LuaUtf8Module, ".exp")
    ) -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (
        [System.IO.Path]::ChangeExtension($LuaUtf8Module, ".lib")
    ) -ErrorAction SilentlyContinue

    [System.IO.File]::WriteAllText(
        (Join-Path $RuntimeStage "manifest"),
        $RuntimeManifest,
        [System.Text.UTF8Encoding]::new($false)
    )

    $PreviousLuaCPath = $env:LUA_CPATH
    try {
        $env:LUA_CPATH = "$ModuleDirectory/?.dll;;"
        Invoke-Native (Join-Path $BinDirectory "luajit.exe") @(
            "-e", "require('lua-utf8')"
        )
    }
    finally {
        $env:LUA_CPATH = $PreviousLuaCPath
    }

    Move-Item -LiteralPath $RuntimeStage -Destination $RuntimePrefix
    $RuntimeStage = $null
}
finally {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
    if ($null -ne $RuntimeStage) {
        Remove-Item -LiteralPath $RuntimeStage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "runtime build: installed pinned Windows x86-64 runtime at $RuntimePrefix"
