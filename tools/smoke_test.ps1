<#
.SYNOPSIS
    Launch the packaged app, confirm the UI starts, then close it.

.DESCRIPTION
    Used by CI (and runnable locally) after PyInstaller. A crashing windowed
    PyInstaller app shows an error dialog instead of exiting, so success is
    detected from the app log: "local_ai_manager.ui: Settings:" is logged
    only after the whole UI has been built. Settings and logs go to a
    throw-away directory, never to %APPDATA%.

.EXAMPLE
    .\tools\smoke_test.ps1
#>
param(
    [string] $Exe = "dist\LocalAIManager\LocalAIManager.exe",
    [int] $TimeoutSeconds = 60
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Exe)) { throw "Executable not found: $Exe (build it first)" }
$cfgDir = Join-Path ([IO.Path]::GetTempPath()) ("lam-smoke-" + [guid]::NewGuid())
$env:LOCAL_AI_MANAGER_CONFIG_DIR = $cfgDir
$log = Join-Path $cfgDir "logs\app.log"

function Test-LogContains([string] $Pattern) {
    (Test-Path $log) -and [bool](Select-String -Path $log -Pattern $Pattern -Quiet)
}

$proc = Start-Process -FilePath $Exe -PassThru
$started = $false
try {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if ($proc.HasExited) { throw "App exited during startup (exit code $($proc.ExitCode))." }
        if (Test-LogContains "local_ai_manager\.ui: Settings:") { $started = $true; break }
    }
    if (-not $started) { throw "UI did not finish starting within $TimeoutSeconds s." }

    Start-Sleep -Seconds 3   # let the monitor thread run a few polls
    if ($proc.HasExited) { throw "App exited after startup (exit code $($proc.ExitCode))." }

    $proc.Refresh()
    if ($proc.MainWindowHandle -ne 0) {
        [void]$proc.CloseMainWindow()
        if (-not $proc.WaitForExit(15000)) { throw "App did not exit within 15 s of WM_CLOSE." }
        if (-not (Test-LogContains "Local AI Manager exited\.")) { throw "App closed without a clean shutdown log entry." }
        Write-Host "Closed cleanly via WM_CLOSE."
    } else {
        Write-Warning "No main window handle (non-interactive desktop?); stopping the process instead."
        Stop-Process -Id $proc.Id -Force
    }
    if (Test-LogContains "Traceback|\bERROR\b") { throw "Errors found in the app log." }
    Write-Host "Smoke test passed."
}
finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    if (Test-Path $log) { Write-Host "----- app.log -----"; Get-Content $log }
    Remove-Item -Recurse -Force $cfgDir -ErrorAction SilentlyContinue
}
