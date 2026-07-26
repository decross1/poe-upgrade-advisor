# TASK-209 lane C (issue #75): clean-room test of the PACKAGED Windows zip —
# the exact artifact a tester would download, extracted into a fresh
# directory, launched through run.bat exactly like a tester double-click.
#
#   run.bat up -> POST /api/v0/build with the golden corpus PoB code
#   -> POST /api/v0/diff with the golden item -> assert a REAL build
#   summary AND a REAL verdict from the engine (issue #75 acceptance).
#
# Until lane A's pinned Windows runtime artifact is wired into the zip, the
# bundle ships an explicit stub runtime and the honest "engine cannot start"
# failure (doctrine I5) is what this script asserts instead — pass
# -ExpectStubRuntime. Both modes are hard assertions; nothing is skipped.
#
# Golden inputs come from the repo on the HOST side only — the app under
# test sees them as an ordinary HTTP request body, exactly like a tester
# pasting their own PoB code. run.bat's --open may spawn a browser on the
# runner; harmless, it is the real tester path.
#
# Usage: scripts/cleanroom_windows_check.ps1 [-Zip PATH] [-ExpectStubRuntime]
# Exit 0 = every check passed. Transcript goes to stdout.
[CmdletBinding()]
param(
    [string] $Zip,
    [switch] $ExpectStubRuntime,
    [string] $GoldenBuild = "engine/corpus/seed/ninja/12-elementalist-ci-cold-snap.json",
    [string] $GoldenItem = "engine/tests/fixtures/item.txt",
    [int] $Port = 47791,
    [int] $ReadyTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($Zip)) {
    $newest = Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Filter "*-windows-x64.zip" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $newest) {
        Write-Host "FAIL: no zip found (run scripts/package_mvp_windows.ps1 first)"
        exit 1
    }
    $Zip = $newest.FullName
}
$Zip = [System.IO.Path]::GetFullPath($Zip)

$script:Pass = 0
$script:Fail = 0
function Ok($Message)  { $script:Pass += 1; Write-Host "PASS: $Message" }
function Bad($Message) { $script:Fail += 1; Write-Host "FAIL: $Message" }

function Test-PortListening([int] $PortNumber) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $PortNumber, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne(1000)) {
            $client.EndConnect($async)
            return $true
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

$Work = Join-Path ([System.IO.Path]::GetTempPath()) "poe-mvp-cleanroom-$([System.Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $Work | Out-Null
$Process = $null

try {
    Write-Host "== clean-room Windows check (TASK-209 lane C / issue #75)"
    Write-Host "repo HEAD:        $((& git.exe rev-parse HEAD).Trim())"
    Write-Host "zip:              $Zip"
    $hash = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "zip sha256:       $hash"
    Write-Host ("zip size:         {0:N1} MB" -f ((Get-Item -LiteralPath $Zip).Length / 1MB))
    Write-Host "extract dir:      $Work (fresh)"
    Write-Host "mode:             $(if ($ExpectStubRuntime) { 'STUB runtime -> assert honest engine failure' } else { 'real runtime -> assert real build summary' })"
    Write-Host "date:             $(Get-Date -AsUTC -Format 'yyyy-MM-ddTHH:mm:ssZ')"

    # --- 1. Extract exactly like a tester -----------------------------------
    Expand-Archive -LiteralPath $Zip -DestinationPath $Work
    $App = Join-Path $Work "poe-upgrade-advisor-v0"

    # --- 2. Provenance: real engine in, fixture path out, Windows-only ------
    if ((Test-Path -LiteralPath (Join-Path $App "run.bat") -PathType Leaf)) {
        Ok "run.bat present (THE entrypoint)"
    } else { Bad "run.bat missing" }
    if (-not (Test-Path -LiteralPath (Join-Path $App "run.command")) -and
        -not (Test-Path -LiteralPath (Join-Path $App "run.sh"))) {
        Ok "no run.command / run.sh — Windows-only zip (issue #75 decision)"
    } else { Bad "unix entrypoints leaked into the Windows zip" }

    $runtimeRoot = Join-Path $App "engine/.runtime"
    if ($ExpectStubRuntime) {
        if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot "bin/luajit.exe")) -and
            (Test-Path -LiteralPath (Join-Path $runtimeRoot "bin/RUNTIME-STUB.txt") -PathType Leaf)) {
            Ok "engine runtime is the explicit STUB (honest failure by design, I5)"
        } else { Bad "expected stub runtime; found luajit.exe or missing RUNTIME-STUB.txt" }
    }
    else {
        $runtimeOk = (Test-Path -LiteralPath (Join-Path $runtimeRoot "bin/luajit.exe") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $runtimeRoot "bin/lua51.dll") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $runtimeRoot "lib/lua/5.1/lua-utf8.dll") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $runtimeRoot "manifest") -PathType Leaf)
        if ($runtimeOk) {
            Ok "prebuilt pinned Windows Lua runtime ships (testers need no compiler)"
        } else { Bad "engine/.runtime incomplete (luajit.exe/lua51.dll/lua-utf8.dll/manifest)" }
    }

    if (Test-Path -LiteralPath (Join-Path $App "engine/vendor/PathOfBuilding/src/HeadlessWrapper.lua") -PathType Leaf) {
        Ok "vendored PathOfBuilding src ships"
    } else { Bad "vendored PoB src missing" }
    $treeCount = @(Get-ChildItem -LiteralPath (Join-Path $App "engine/vendor/PathOfBuilding/src/TreeData") -Filter "tree.lua" -Recurse -ErrorAction SilentlyContinue).Count
    if ($treeCount -ge 39) {
        Ok "all $treeCount passive-tree data files ship (any league's build imports)"
    } else { Bad "only $treeCount tree.lua files shipped" }
    $sprites = @(Get-ChildItem -LiteralPath (Join-Path $App "engine/vendor/PathOfBuilding/src/TreeData") -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { @(".png", ".jpg", ".webp") -contains $_.Extension.ToLowerInvariant() }).Count
    if ($sprites -eq 0) {
        Ok "0 GUI sprites shipped (headless stub; no network-fetch path)"
    } else { Bad "$sprites GUI sprites leaked into the bundle" }
    if (-not (Test-Path -LiteralPath (Join-Path $App "contracts"))) {
        Ok "contracts/fixtures ABSENT from the artifact — fixture verdicts are impossible"
    } else { Bad "contracts/ present in artifact (fixture path reachable?)" }
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot "timeless-data"))) {
        Ok "timeless-data cache not shipped (regenerates from vendored zips on first run)"
    } else { Bad "timeless-data cache shipped (double payload)" }

    # --- 3. Launch the entrypoint as a tester (fresh dir, run.bat) ----------
    $outLog = Join-Path $Work "server.out.log"
    $errLog = Join-Path $Work "server.err.log"
    $Process = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "run.bat" `
        -WorkingDirectory $App -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-Host "== entrypoint launched (fresh extract dir, cmd.exe /c run.bat), pid $($Process.Id)"

    if ($ExpectStubRuntime) {
        # The launcher must stop on its own with the honest failure (I5).
        $exited = $Process.WaitForExit(120 * 1000)
        # launch.py's sys.exit(message) writes the honest failure to STDERR,
        # so the validated log must combine BOTH captured streams — the
        # stdout capture alone is empty on this path (review round 1).
        $log = ""
        if (Test-Path -LiteralPath $outLog) { $log = [System.IO.File]::ReadAllText($outLog) }
        if (Test-Path -LiteralPath $errLog) { $log += "`n" + [System.IO.File]::ReadAllText($errLog) }
        if ($exited -and $Process.ExitCode -ne 0) {
            Ok "launcher stopped on its own with a nonzero exit ($($Process.ExitCode)) — no guessing"
        } elseif ($exited) {
            Bad "launcher exited 0 despite the stub runtime — a missing engine must never look like success"
        } else {
            Bad "launcher still running after 120s with a stub runtime"
        }
        if ($log -match "engine could not start") {
            Ok "honest failure message printed: $(($log -split "`n" | Select-String 'engine could not start' | Select-Object -First 1).Line.Trim())"
        } elseif ($log -match "engine cannot start") {
            # run.bat's runtime gate (lane A, #78) stops a stub zip before
            # launch.py runs, with its own honest phrasing — same I5 contract.
            Ok "honest failure message printed: $(($log -split "`n" | Select-String 'engine cannot start' | Select-Object -First 1).Line.Trim())"
        } else {
            Bad "honest 'engine could not start' message missing; server log follows"
            Write-Host $log
        }
    }
    else {
        $ready = $false
        $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if ($Process.HasExited) {
                Write-Host "FAIL: entrypoint died during startup; server log follows"
                if (Test-Path -LiteralPath $outLog) { Write-Host ([System.IO.File]::ReadAllText($outLog)) }
                if (Test-Path -LiteralPath $errLog) { Write-Host ([System.IO.File]::ReadAllText($errLog)) }
                exit 1
            }
            if (Test-PortListening $Port) { $ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if ($ready) {
            Ok "entrypoint up on http://127.0.0.1:$Port/ (first run incl. venv bootstrap + engine boot + timeless-cache build)"
        } else {
            Bad "entrypoint never listened on $Port"
            if (Test-Path -LiteralPath $outLog) { Write-Host ([System.IO.File]::ReadAllText($outLog)) }
            exit 1
        }

        # --- 4. Exercise the full slice over HTTP (host = tester's browser) -
        $client = New-Object System.Net.Http.HttpClient
        $client.Timeout = [TimeSpan]::FromSeconds(60)
        try {
            $index = $client.GetAsync("http://127.0.0.1:$Port/").Result
            if ($index.IsSuccessStatusCode -and
                $index.Content.Headers.ContentType.MediaType -eq "text/html") {
                Ok "GET / -> 200 text/html (the whole app)"
            } else { Bad "GET / -> $($index.StatusCode)" }

            $golden = Get-Content -LiteralPath (Join-Path $Root $GoldenBuild) -Raw | ConvertFrom-Json
            $body = @{ pob_code = $golden.pathOfBuildingExport } | ConvertTo-Json -Compress
            $response = $client.PostAsync(
                "http://127.0.0.1:$Port/api/v0/build",
                (New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, "application/json"))
            ).Result
            $payload = $response.Content.ReadAsStringAsync().Result
            if ($response.IsSuccessStatusCode) {
                Ok "POST /api/v0/build (golden corpus PoB code) -> 200"
            } else { Bad "POST /api/v0/build -> $($response.StatusCode): $payload" }
            Write-Host "   build readback: $payload"
            $build = $payload | ConvertFrom-Json
            if ($build.main_skill.name -eq "Vaal Cold Snap") {
                Ok "main skill readback is the real engine's (Vaal Cold Snap) — real build summary, not a fixture"
            } else { Bad "main skill readback was '$($build.main_skill.name)', expected 'Vaal Cold Snap'" }
            if ([string]::IsNullOrWhiteSpace($build.build_id)) {
                Bad "build_id missing from the build summary"
            } else { Ok "build_id present ($($build.build_id))" }

            $itemText = [System.IO.File]::ReadAllText((Join-Path $Root $GoldenItem))
            $diffBody = @{ item_text = $itemText } | ConvertTo-Json -Compress
            $diffResponse = $client.PostAsync(
                "http://127.0.0.1:$Port/api/v0/diff",
                (New-Object System.Net.Http.StringContent($diffBody, [System.Text.Encoding]::UTF8, "application/json"))
            ).Result
            $diffPayload = $diffResponse.Content.ReadAsStringAsync().Result
            if ($diffResponse.IsSuccessStatusCode) {
                Ok "POST /api/v0/diff (golden item) -> 200"
            } else { Bad "POST /api/v0/diff -> $([int] $diffResponse.StatusCode): $diffPayload" }
            Write-Host "   verdict: $diffPayload"
            $verdict = $diffPayload | ConvertFrom-Json
            if (@("UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE") -contains $verdict.verdict) {
                Ok "verdict word is contract-valid ($($verdict.verdict))"
            } else { Bad "verdict word '$($verdict.verdict)' not in the contract enum" }
            if (-not ($verdict.verdict -eq "UPGRADE" -and $verdict.offense_delta_pct -eq 12.4 -and $verdict.defense_delta_pct -eq -1.8)) {
                Ok "NOT the retired fixture signature (+12.4/-1.8 UPGRADE)"
            } else { Bad "fixture signature verdict — the fixture path answered" }
            # Independently recorded real-engine E2E on PR #72 for this exact
            # build+item+preset: SIDEGRADE +15.4 / -11.8, deterministic engine.
            # Lane A proved the Windows runtime byte-identical to Linux
            # (runtime-parity-cross-platform), so the same numbers must hold.
            if ($verdict.verdict -eq "SIDEGRADE" -and $verdict.offense_delta_pct -eq 15.4 -and $verdict.defense_delta_pct -eq -11.8) {
                Ok "matches the real-engine E2E numbers from PR #72 (SIDEGRADE +15.4/-11.8)"
            } else { Bad "verdict $($verdict.verdict) +$($verdict.offense_delta_pct)/$($verdict.defense_delta_pct) != real-engine E2E (SIDEGRADE +15.4/-11.8)" }
            if (@($verdict.assumptions).Count -ge 1) {
                Ok "assumption chips present (I3)"
            } else { Bad "no assumption chips on the verdict (I3)" }
            if ($verdict.sentence.Length -le 140) {
                Ok "sentence within 140-char cap (I2)"
            } else { Bad "verdict sentence over the 140-char cap (I2)" }

            $flipBody = @{
                item_text = $itemText
                overrides  = @(@{ assumption_id = "config.flasks_up"; value = $false })
            } | ConvertTo-Json -Compress -Depth 5
            $flipResponse = $client.PostAsync(
                "http://127.0.0.1:$Port/api/v0/diff",
                (New-Object System.Net.Http.StringContent($flipBody, [System.Text.Encoding]::UTF8, "application/json"))
            ).Result
            $flipPayload = $flipResponse.Content.ReadAsStringAsync().Result
            if ($flipResponse.IsSuccessStatusCode) {
                Ok "I3 override round-trip -> 200"
            } else { Bad "I3 override round-trip -> $([int] $flipResponse.StatusCode): $flipPayload" }
            Write-Host "   overridden verdict: $flipPayload"
            $flipped = $flipPayload | ConvertFrom-Json
            $chips = @{}
            foreach ($a in @($flipped.assumptions)) { $chips[$a.id] = $a.value }
            if ($chips.ContainsKey("config.flasks_up") -and $chips["config.flasks_up"] -eq $false) {
                Ok "flasks_up chip flipped true->false on override (I3)"
            } else { Bad "flasks_up chip did not flip on override (I3)" }

            $junkBody = @{ item_text = "Rarity: RARE`nnot a real item`n" } | ConvertTo-Json -Compress
            $junkResponse = $client.PostAsync(
                "http://127.0.0.1:$Port/api/v0/diff",
                (New-Object System.Net.Http.StringContent($junkBody, [System.Text.Encoding]::UTF8, "application/json"))
            ).Result
            if ([int] $junkResponse.StatusCode -eq 422) {
                Ok "unparseable item -> honest 422 (I5)"
            } else { Bad "unparseable item -> $([int] $junkResponse.StatusCode), expected honest 422 (I5)" }
        }
        finally {
            $client.Dispose()
        }
    }

    # --- 5. Clean stop -------------------------------------------------------
    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
        $Process.WaitForExit()
    }
    if ($ExpectStubRuntime -or -not (Test-PortListening $Port)) {
        Ok "server stopped, port $Port released"
    } else { Bad "port $Port still bound after stop" }

    Write-Host "== clean-room result: $script:Pass passed, $script:Fail failed"
    exit ($(if ($script:Fail -eq 0) { 0 } else { 1 }))
}
finally {
    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}
