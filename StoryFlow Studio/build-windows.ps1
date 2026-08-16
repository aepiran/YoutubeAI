[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Clean,
    [switch]$NoArchive,
    [switch]$StopRunningApp
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = $PSScriptRoot
$Python = Join-Path $AppRoot ".venv\Scripts\python.exe"
$SpecFile = Join-Path $AppRoot "storyflow-studio.spec"
$BuildRoot = Join-Path $AppRoot "build\windows"
$DistRoot = Join-Path $AppRoot "dist\windows"
$ReleaseRoot = Join-Path $AppRoot "release"
$AppName = "StoryFlowStudio"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Test-PythonImport {
    param([Parameter(Mandatory = $true)][string]$ModuleName)
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & $Python -c "import $ModuleName" *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

function Remove-BuildDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $ResolvedRoot = [System.IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
    $ResolvedTarget = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $ResolvedTarget.StartsWith($ResolvedRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a build path outside StoryFlow Studio: $ResolvedTarget"
    }
    if (-not (Test-Path -LiteralPath $ResolvedTarget)) {
        return
    }
    for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
        try {
            Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
            return
        }
        catch {
            if ($Attempt -eq 5) {
                throw "Could not clear build directory '$ResolvedTarget'. Close StoryFlowStudio and any Explorer window using this folder, then retry. Original error: $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds 750
        }
    }
}

function Stop-BuiltApplicationIfNeeded {
    $BuiltExecutable = [System.IO.Path]::GetFullPath(
        (Join-Path $DistRoot "$AppName\$AppName.exe")
    )
    $RunningApplications = @(
        Get-Process -Name $AppName -ErrorAction SilentlyContinue | Where-Object {
            try {
                $_.Path -and (
                    [System.IO.Path]::GetFullPath($_.Path) -eq $BuiltExecutable
                )
            }
            catch {
                $false
            }
        }
    )
    if ($RunningApplications.Count -eq 0) {
        return
    }
    $ProcessIds = ($RunningApplications.Id -join ", ")
    if (-not $StopRunningApp) {
        throw "The built StoryFlowStudio is still running (PID: $ProcessIds) and is locking the output folder. Close it, or rerun with -StopRunningApp."
    }
    Write-Host "==> Stopping built StoryFlowStudio (PID: $ProcessIds)" -ForegroundColor Yellow
    $RunningApplications | Stop-Process -Force
    foreach ($Process in $RunningApplications) {
        try {
            Wait-Process -Id $Process.Id -Timeout 10 -ErrorAction Stop
        }
        catch {
            if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) {
                throw "StoryFlowStudio PID $($Process.Id) did not stop. Close it manually before building."
            }
        }
    }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing .venv. Run setup-windows.bat before building."
}
foreach ($RequiredPath in @(
    $SpecFile,
    (Join-Path $AppRoot "storyflow_launcher.py"),
    (Join-Path $AppRoot "build-scripts\runtime_windows.py")
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required build input is missing: $RequiredPath"
    }
}
foreach ($MediaTool in @("ffmpeg.exe", "ffprobe.exe")) {
    if ($null -eq (Get-Command $MediaTool -ErrorAction SilentlyContinue)) {
        throw "$MediaTool was not found on PATH. Install FFmpeg before building."
    }
}

Push-Location $AppRoot
try {
    if (-not (Test-PythonImport "PyInstaller")) {
        Invoke-Checked "Installing PyInstaller" {
            & $Python -m pip install "pyinstaller>=6.11,<7"
        }
    }

    if (-not $SkipTests) {
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:PYTHONUTF8 = "1"
        Invoke-Checked "Running StoryFlow tests" {
            & $Python -m unittest discover -s tests -v
        }
    }

    Stop-BuiltApplicationIfNeeded
    if ($Clean) {
        Remove-BuildDirectory $BuildRoot
        Remove-BuildDirectory $DistRoot
    }
    else {
        # PyInstaller also removes this onedir output when --noconfirm is used.
        # Removing it here gives Windows locks a retry window and a clear error.
        Remove-BuildDirectory (Join-Path $DistRoot $AppName)
    }
    New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot | Out-Null

    $PyInstallerArguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", $DistRoot,
        "--workpath", (Join-Path $BuildRoot "work"),
        $SpecFile
    )
    Invoke-Checked "Building StoryFlowStudio.exe" {
        & $Python @PyInstallerArguments
    }

    $BuiltApplication = Join-Path $DistRoot $AppName
    $Executable = Join-Path $BuiltApplication "$AppName.exe"
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "PyInstaller did not create the expected executable: $Executable"
    }
    Write-Host "==> Verifying bundled Codex CLI" -ForegroundColor Cyan
    $BundleCheck = Start-Process -FilePath $Executable -ArgumentList "--verify-bundle" -Wait -PassThru
    if ($BundleCheck.ExitCode -ne 0) {
        throw "Bundled Codex CLI verification failed with exit code $($BundleCheck.ExitCode)."
    }

    $Version = (& $Python -c "from storyflow_studio.core.version import application_version; print(application_version())").Trim()
    $Architecture = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
    if (-not $NoArchive) {
        New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
        $Archive = Join-Path $ReleaseRoot "$AppName-$Version-windows-$Architecture.zip"
        if (Test-Path -LiteralPath $Archive) {
            Remove-Item -LiteralPath $Archive -Force
        }
        Compress-Archive -Path $BuiltApplication -DestinationPath $Archive -CompressionLevel Optimal
        Write-Host "Release:     $Archive" -ForegroundColor Green
    }

    Write-Host "Build completed." -ForegroundColor Green
    Write-Host "Executable:  $Executable"
}
finally {
    Pop-Location
}
