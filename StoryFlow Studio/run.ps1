[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ApplicationArguments
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = $PSScriptRoot
$Python = Join-Path $AppRoot ".venv\Scripts\python.exe"
$SetupScript = Join-Path $AppRoot "setup-windows.ps1"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Error @"
StoryFlow Studio virtual environment was not found:
  $Python

Run the first-time setup:
  powershell.exe -ExecutionPolicy Bypass -File "$SetupScript"
"@
    exit 1
}

& $Python -c "import PySide6, storyflow_studio" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error @"
StoryFlow Studio dependencies are incomplete.
Run the setup script again:
  powershell.exe -ExecutionPolicy Bypass -File "$SetupScript"
"@
    exit 1
}

Push-Location $AppRoot
try {
    & $Python -m storyflow_studio @ApplicationArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
