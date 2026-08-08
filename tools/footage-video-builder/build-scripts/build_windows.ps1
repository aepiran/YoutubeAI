param(
    [string]$Version = "1.0.0",
    [switch]$InstallDependencies,
    [switch]$SkipTests,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$BuildRoot = Join-Path $ProjectDir "build\windows"
$DistRoot = Join-Path $ProjectDir "dist\windows"
$ReleaseRoot = Join-Path $ProjectDir "release"
$AppName = "FootageVideoBuilder"
$SpecFile = Join-Path $ProjectDir "ft-video-builder.spec"
$WindowsArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$Archive = Join-Path $ReleaseRoot "$AppName-$Version-windows-$WindowsArch.zip"

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Command)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE." }
}

Set-Location $ProjectDir
if ($Version -notmatch '^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$') {
    throw "Version must look like 1.0.0 or 1.0.0-beta.1."
}
foreach ($RequiredPath in @(
    $SpecFile,
    (Join-Path $ProjectDir "main.py"),
    (Join-Path $ProjectDir "requirements.txt"),
    (Join-Path $ProjectDir "assets\yt-vidbuilder.ico")
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required build input is missing: $RequiredPath"
    }
}
if ($Clean) {
    if (Test-Path -LiteralPath $BuildRoot) { Remove-Item -LiteralPath $BuildRoot -Recurse -Force }
    if (Test-Path -LiteralPath $DistRoot) { Remove-Item -LiteralPath $DistRoot -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot, $ReleaseRoot | Out-Null

if ($InstallDependencies) {
    Invoke-Checked "Installing dependencies" {
        & $Python -m pip install --upgrade pip
        if ($LASTEXITCODE -eq 0) { & $Python -m pip install -r requirements.txt }
    }
}
Invoke-Checked "Checking PyInstaller" { & $Python -c "import PyInstaller" }
if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:PYTHONUTF8 = "1"
    Invoke-Checked "Running tests" { & $Python -m unittest discover -s tests -v }
}

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--distpath", $DistRoot,
    "--workpath", (Join-Path $BuildRoot "work"),
    $SpecFile
)
Invoke-Checked "Building Windows application" { & $Python @PyInstallerArgs }

$BuiltApp = Join-Path $DistRoot $AppName
if (-not (Test-Path -LiteralPath (Join-Path $BuiltApp "$AppName.exe"))) {
    throw "PyInstaller did not create $AppName.exe."
}
if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
Compress-Archive -Path $BuiltApp -DestinationPath $Archive -CompressionLevel Optimal

Write-Host ""
Write-Host "Build completed." -ForegroundColor Green
Write-Host "Application: $BuiltApp"
Write-Host "Release:     $Archive"
