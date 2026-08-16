[CmdletBinding()]
param(
    [switch]$CheckPython
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = $PSScriptRoot
$VenvRoot = Join-Path $AppRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"

function Test-StoryFlowPython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    # Windows PowerShell 5 can promote stderr from a native command to a
    # terminating NativeCommandError when ErrorActionPreference is Stop.
    # Missing py.exe runtimes are expected while probing, so suppress the
    # native output and inspect only the process exit code.
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & $Executable @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

function Find-StoryFlowPython {
    $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        foreach ($Version in @("3.12", "3.11", "3.10", "3")) {
            $VersionArgument = "-$Version"
            if (Test-StoryFlowPython $PyLauncher.Source @($VersionArgument)) {
                return [pscustomobject]@{
                    Executable = $PyLauncher.Source
                    VersionArgument = $VersionArgument
                }
            }
        }
    }

    $Python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $Python) {
        if (Test-StoryFlowPython $Python.Source) {
            return [pscustomobject]@{
                Executable = $Python.Source
                VersionArgument = $null
            }
        }
    }
    throw "StoryFlow Studio requires Python 3.10 or newer. Install Python from python.org, then run this script again."
}

Write-Host "StoryFlow Studio - Windows setup" -ForegroundColor Cyan
Write-Host "Application folder: $AppRoot"

if ($CheckPython) {
    $DetectedPython = Find-StoryFlowPython
    $DetectedCommand = $DetectedPython.Executable
    if ($null -ne $DetectedPython.VersionArgument) {
        $DetectedCommand += " " + $DetectedPython.VersionArgument
    }
    Write-Host "Compatible Python found: $DetectedCommand" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    $PythonCommand = Find-StoryFlowPython
    $PythonExecutable = $PythonCommand.Executable
    Write-Host "Creating virtual environment at $VenvRoot ..."
    if ($null -ne $PythonCommand.VersionArgument) {
        $PythonVersionArgument = $PythonCommand.VersionArgument
        & $PythonExecutable $PythonVersionArgument -m venv $VenvRoot
    }
    else {
        & $PythonExecutable -m venv $VenvRoot
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the StoryFlow Studio virtual environment."
    }
}

Write-Host "Installing StoryFlow Studio and dependencies ..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip in the virtual environment."
}
& $VenvPython -m pip install --editable $AppRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not install StoryFlow Studio dependencies."
}

& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "The StoryFlow Studio environment has missing or incompatible dependencies."
}

& $VenvPython -c "import PySide6, storyflow_studio; from codex_cli_bin import bundled_codex_path, bundled_package_dir; bundled_package_dir(); print('StoryFlow Studio environment is ready. Codex CLI: ' + str(bundled_codex_path()))"
if ($LASTEXITCODE -ne 0) {
    throw "Installation completed but the application or bundled Codex CLI check failed."
}

Write-Host "Setup completed. Start the application with run.bat." -ForegroundColor Green
