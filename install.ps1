Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
$deck = Join-Path $root "deck.py"
$requirements = Join-Path $root "requirements.txt"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "ADeck.lnk"
$logDir = Join-Path $env:LOCALAPPDATA "ADeck"
$stdoutLog = Join-Path $logDir "runtime.stdout.log"
$stderrLog = Join-Path $logDir "runtime.stderr.log"
$healthUrl = "http://127.0.0.1:8765/api/status"
$serviceName = "ADeck"
$runtimeStarted = $false
$shortcutCreated = $false

Set-Location $root

function Invoke-Stage {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$Action
  )

  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  & $Action
}

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [Parameter(Mandatory = $true)][string]$FailureMessage
  )

  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    $exitCode = if ($null -eq $LASTEXITCODE) { "unknown" } else { [string]$LASTEXITCODE }
    throw "$FailureMessage (exit code $exitCode)."
  }
}

function Test-VenvPython {
  if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    return $false
  }

  & $python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" 2>$null
  return $LASTEXITCODE -eq 0
}

function Get-BasePython {
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    return @{
      FilePath = $launcher.Source
      Prefix = @("-3")
    }
  }

  $executable = Get-Command python -ErrorAction SilentlyContinue
  if ($executable) {
    return @{
      FilePath = $executable.Source
      Prefix = @()
    }
  }

  throw "Python 3 is required. Install it from python.org and run this installer again."
}

function Get-ADeckHealth {
  try {
    return Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
  } catch {
    return $null
  }
}

function Test-ADeckBackendHealthy {
  param($Status)
  return (
    $null -ne $Status -and
    $Status.ok -eq $true -and
    $Status.service -eq $serviceName -and
    $null -ne $Status.bridge_version
  )
}

function Get-ProcessExitCodeText {
  param($Process)
  if ($null -eq $Process) {
    return "unknown"
  }
  try {
    $Process.Refresh()
  } catch {
    # Ignore refresh failures; fall through to best-effort ExitCode.
  }
  if (-not $Process.HasExited) {
    return "still-running"
  }
  if ($null -eq $Process.ExitCode) {
    return "unknown"
  }
  return [string]$Process.ExitCode
}

function Get-RuntimeLogSnippet {
  param([string]$Path, [int]$Tail = 8)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    return ""
  }
  try {
    $lines = Get-Content -LiteralPath $Path -Tail $Tail -ErrorAction Stop
    return (($lines | ForEach-Object { $_.TrimEnd() }) -join "`n").Trim()
  } catch {
    return ""
  }
}

function Test-AlreadyRunningMessage {
  param([string]$Text)
  return ($Text -match "ADeck service is already running")
}

function Wait-ADeckBackendHealthy {
  param([int]$TimeoutSeconds = 30)
  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  $lastStatus = $null
  while ([DateTime]::UtcNow -lt $deadline) {
    $lastStatus = Get-ADeckHealth
    if (Test-ADeckBackendHealthy $lastStatus) {
      return $lastStatus
    }
    Start-Sleep -Milliseconds 500
  }
  return $lastStatus
}

function Start-ADeckBackendProcess {
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
  # Truncate prior launch logs so this attempt's exit reason is unambiguous.
  Set-Content -LiteralPath $stdoutLog -Value "" -Encoding utf8
  Set-Content -LiteralPath $stderrLog -Value "" -Encoding utf8

  $process = Start-Process `
    -FilePath $pythonw `
    -ArgumentList @($deck) `
    -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  if ($null -eq $process) {
    throw "ADeck backend failed to launch (no process object). See $stderrLog"
  }

  $script:runtimeStarted = $true
  $pidText = if ($null -ne $process.Id) { [string]$process.Id } else { "unknown" }
  Write-Host "Started ADeck backend process PID $pidText."

  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  $lastStatus = $null
  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      $process.Refresh()
    } catch {
      # Process object may become invalid after exit.
    }

    $lastStatus = Get-ADeckHealth
    if (Test-ADeckBackendHealthy $lastStatus) {
      Write-Host "Backend health check passed."
      return $lastStatus
    }

    if ($process.HasExited) {
      $exitText = Get-ProcessExitCodeText -Process $process
      $stdoutText = Get-RuntimeLogSnippet -Path $stdoutLog
      $stderrText = Get-RuntimeLogSnippet -Path $stderrLog
      $combined = "$stdoutText`n$stderrText"

      # Single-instance exit: another owner may already be healthy — reuse it.
      if (Test-AlreadyRunningMessage $combined) {
        Start-Sleep -Milliseconds 400
        $recheck = Get-ADeckHealth
        if (Test-ADeckBackendHealthy $recheck) {
          Write-Host "Detected existing healthy ADeck backend; reusing it."
          $script:runtimeStarted = $false
          return $recheck
        }
        throw (
          "ADeck runtime lock is held but http://127.0.0.1:8765/api/status is not healthy. " +
          "Run ADeck-Control.bat → Install / Repair (or Stop, then Start). " +
          "Launcher exit code: $exitText. See $stdoutLog"
        )
      }

      $detail = if ($stderrText) { $stderrText } elseif ($stdoutText) { $stdoutText } else { "no log output" }
      throw "ADeck backend exited with code $exitText. $detail See $stderrLog"
    }

    Start-Sleep -Milliseconds 500
  }

  if (Test-ADeckBackendHealthy $lastStatus) {
    return $lastStatus
  }

  $exitText = Get-ProcessExitCodeText -Process $process
  throw (
    "ADeck backend did not become healthy within 30 seconds " +
    "(PID $pidText, exit code $exitText). See $stderrLog"
  )
}

try {
  Invoke-Stage "Disable existing autostart" {
    if (Test-Path -LiteralPath $shortcutPath) {
      Remove-Item -LiteralPath $shortcutPath -Force
      Write-Host "Removed the existing ADeck startup shortcut."
    } else {
      Write-Host "No existing ADeck startup shortcut was present."
    }
  }

  Invoke-Stage "Prepare Python environment" {
    if (-not (Test-VenvPython)) {
      if (Test-Path -LiteralPath $venv) {
        Remove-Item -LiteralPath $venv -Recurse -Force
      }
      $basePython = Get-BasePython
      $arguments = @($basePython.Prefix) + @("-m", "venv", $venv)
      Invoke-Checked `
        -FilePath $basePython.FilePath `
        -Arguments $arguments `
        -FailureMessage "Could not create the Python environment"
    } else {
      Write-Host "Reusing the existing Python environment."
    }

    if (-not (Test-VenvPython) -or -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
      throw "The Python environment is incomplete after setup."
    }
  }

  Invoke-Stage "Install pinned dependencies" {
    Invoke-Checked `
      -FilePath $python `
      -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements) `
      -FailureMessage "Python dependency installation failed"
  }

  Invoke-Stage "Install and verify firmware" {
    # --if-needed skips reflash when ADECK_PONG already succeeds.
    Invoke-Checked `
      -FilePath $python `
      -Arguments @((Join-Path $root "install_firmware.py"), "--if-needed") `
      -FailureMessage "Firmware installation failed"
  }

  Invoke-Stage "Start ADeck backend" {
    $existing = Get-ADeckHealth
    if (Test-ADeckBackendHealthy $existing) {
      Write-Host "Reusing healthy ADeck backend already running on :8765."
      if ($existing.connected -ne $true) {
        $offline = if ($existing.error) { $existing.error } else { "not connected" }
        Write-Host "Hardware currently offline ($offline); continuing to verification."
      }
    } else {
      Start-ADeckBackendProcess | Out-Null
    }
  }

  Invoke-Stage "Verify backend and hardware" {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $lastStatus = $null
    while ([DateTime]::UtcNow -lt $deadline) {
      $lastStatus = Get-ADeckHealth
      if (
        (Test-ADeckBackendHealthy $lastStatus) -and
        $lastStatus.connected -eq $true
      ) {
        break
      }
      # Backend healthy but hardware still offline: keep waiting for USB.
      Start-Sleep -Milliseconds 500
    }

    if (-not (Test-ADeckBackendHealthy $lastStatus)) {
      throw "ADeck backend did not become healthy. See $stderrLog"
    }
    if ($lastStatus.connected -ne $true) {
      $detail = if ($lastStatus.error) { " $($lastStatus.error)" } else { "" }
      throw "ADeck backend is healthy, but hardware did not connect within 45 seconds.$detail Reconnect USB, then run Check System."
    }
    Write-Host "Backend is healthy and ADeck is connected on $($lastStatus.port)."
  }

  Invoke-Stage "Create autostart" {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$deck`""
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "ADeck local service"
    $shortcut.Save()
    $shortcutCreated = $true
  }

  Invoke-Stage "Create desktop app entry" {
    # Desktop/Start Menu icon + adeck:// handler. Not fatal: ADeck still runs
    # from Start ADeck.bat and the browser if this step cannot complete.
    & $python (Join-Path $root "adeck_control.py") shortcuts
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Could not create the desktop icon. Use the System page in ADeck to retry." -ForegroundColor Yellow
    }
    & $python (Join-Path $root "adeck_control.py") protocol
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Could not register the adeck:// handler (optional)." -ForegroundColor Yellow
    }
    $global:LASTEXITCODE = 0
  }

  Invoke-Stage "Open ADeck" {
    Write-Host "Opening ADeck in its own app window ..."
    & $python (Join-Path $root "adeck_control.py") app
    if ($LASTEXITCODE -ne 0) {
      Start-Process "http://127.0.0.1:8765/"
    }
    $global:LASTEXITCODE = 0
  }

  $finalStatus = Get-ADeckHealth
  $webState = if (Test-ADeckBackendHealthy $finalStatus) { "healthy on :8765" } else { "not ready" }
  $hardwareState = if ($finalStatus -and $finalStatus.connected -eq $true) {
    "connected on $($finalStatus.port)"
  } else {
    "offline"
  }

  Write-Host ""
  Write-Host "ADeck is ready." -ForegroundColor Green
  Write-Host "  Web:      $webState"
  Write-Host "  Hardware: $hardwareState"
  Write-Host ""
  Write-Host "ADeck will start automatically with Windows."
  Write-Host "Daily use: the ADeck icon on your desktop or Start Menu."
  Write-Host "Inside the app: System page (status, restart, repair, firmware, logs)."
  Write-Host "Fallback tools: Start ADeck.bat   |   ADeck-Control.bat"
  exit 0
} catch {
  Write-Host ""
  Write-Host "ADeck installation failed: $($_.Exception.Message)" -ForegroundColor Red

  if ($shortcutCreated -and (Test-Path -LiteralPath $shortcutPath)) {
    Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
  }
  if ($runtimeStarted -and (Test-Path -LiteralPath $python)) {
    & $python $deck --stop *> $null
  }

  Write-Host "No ADeck autostart shortcut was left behind."
  Write-Host "Runtime logs: $logDir"
  Write-Host "Tip: ADeck-Control.bat -> Check System or Install / Repair"
  exit 1
}
