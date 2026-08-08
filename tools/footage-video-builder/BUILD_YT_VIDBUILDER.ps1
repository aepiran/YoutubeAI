param(
    [string]$Version = "1.0.0",
    [switch]$InstallDependencies,
    [switch]$SkipTests,
    [switch]$Clean
)

$BuildScript = Join-Path $PSScriptRoot "build-scripts\build_windows.ps1"
& $BuildScript `
    -Version $Version `
    -InstallDependencies:$InstallDependencies `
    -SkipTests:$SkipTests `
    -Clean:$Clean
exit $LASTEXITCODE
