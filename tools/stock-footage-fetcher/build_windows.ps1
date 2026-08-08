param(
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"
$ToolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = Split-Path -Parent $ToolRoot
$Python = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
$Entry = Join-Path $ToolRoot "stock_footage_app.py"
$Asset = Join-Path $WorkspaceRoot "footage-finder-ai\assets\icons\app_icon.png"
$DistRoot = Join-Path $ToolRoot "dist"
$WorkRoot = Join-Path $ToolRoot "build"
$SpecRoot = Join-Path $ToolRoot "build-spec"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Không tìm thấy Python virtual environment: $Python"
}
if (-not (Test-Path -LiteralPath $Entry)) {
    throw "Không tìm thấy entry point: $Entry"
}

if (-not $SkipClean) {
    foreach ($Path in @($DistRoot, $WorkRoot, $SpecRoot)) {
        if (Test-Path -LiteralPath $Path) {
            $Resolved = (Resolve-Path -LiteralPath $Path).Path
            if (-not $Resolved.StartsWith($ToolRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Từ chối xóa path ngoài tool: $Resolved"
            }
            Remove-Item -LiteralPath $Resolved -Recurse -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot, $SpecRoot | Out-Null

$Arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "DawnWithGod-FootageFinder",
    "--distpath", $DistRoot,
    "--workpath", $WorkRoot,
    "--specpath", $SpecRoot,
    "--paths", $ToolRoot,
    "--collect-data", "transformers",
    "--collect-submodules", "transformers.models.siglip",
    "--collect-submodules", "transformers.models.auto",
    "--hidden-import", "sentencepiece",
    "--hidden-import", "torch",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets"
)

if (Test-Path -LiteralPath $Asset) {
    $Arguments += @("--add-data", "$Asset;assets\icons")
}
$Arguments += $Entry

Push-Location $ToolRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller thất bại với exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$Exe = Join-Path $DistRoot "DawnWithGod-FootageFinder\DawnWithGod-FootageFinder.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Build hoàn tất nhưng không tìm thấy EXE: $Exe"
}

Write-Host "Build thành công: $Exe"
