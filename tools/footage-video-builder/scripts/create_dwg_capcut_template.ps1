param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Target
)

$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$targetPath = [System.IO.Path]::GetFullPath($Target)

if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'draft_content.json'))) {
    throw "Source is not a CapCut draft: $sourcePath"
}
if (Test-Path -LiteralPath $targetPath) {
    throw "Target already exists: $targetPath"
}
if ([System.IO.Path]::GetDirectoryName($sourcePath) -ne [System.IO.Path]::GetDirectoryName($targetPath)) {
    throw 'Source and target must stay inside the same CapCut Drafts directory.'
}

Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse

$draftName = [System.IO.Path]::GetFileName($targetPath)
$contentPath = Join-Path $targetPath 'draft_content.json'
$content = Get-Content -LiteralPath $contentPath -Raw | ConvertFrom-Json
$content.name = $draftName
$content.path = ($targetPath -replace '\\', '/')
$content.canvas_config.width = 1920
$content.canvas_config.height = 1080
$content.canvas_config.ratio = '16:9'
$content.fps = 30.0

foreach ($textMaterial in @($content.materials.texts)) {
    if (-not $textMaterial.content) { continue }
    $payload = $textMaterial.content | ConvertFrom-Json
    foreach ($style in @($payload.styles)) {
        if ($style.fill.content.solid.color) {
            # Warm ivory remains readable without the aggressive yellow MHO look.
            $style.fill.content.solid.color = @(0.965, 0.945, 0.86)
        }
        foreach ($stroke in @($style.strokes)) {
            if ($stroke.content.solid.color) {
                $stroke.content.solid.color = @(0.055, 0.065, 0.055)
            }
            $stroke.width = 0.018
        }
        $style.size = 6.0
    }
    $textMaterial.font_size = 6.0
    $textMaterial.content = $payload | ConvertTo-Json -Depth 30 -Compress
}

foreach ($track in @($content.tracks | Where-Object { $_.type -eq 'text' })) {
    foreach ($segment in @($track.segments)) {
        # Lower-third safe zone for prayer captions.
        $segment.clip.transform.x = 0.0
        $segment.clip.transform.y = -0.70
    }
}

foreach ($effect in @($content.materials.video_effects)) {
    if ($effect.name -eq 'Flying Dust') {
        $effect.value = 0.35
        foreach ($parameter in @($effect.adjust_params)) {
            if ($parameter.name -eq 'effects_adjust_speed') {
                $parameter.value = 0.15
            }
            if ($parameter.name -eq 'effects_adjust_background_animation') {
                $parameter.value = 0.18
            }
        }
    }
}

$json = $content | ConvertTo-Json -Depth 100 -Compress
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($contentPath, $json, $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $targetPath 'draft_content.json.bak'), $json, $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $targetPath 'template-2.tmp'), $json, $utf8NoBom)

$timelineContents = Get-ChildItem -LiteralPath (Join-Path $targetPath 'Timelines') -Recurse -Filter 'draft_content.json' -File
foreach ($timelineContent in $timelineContents) {
    [System.IO.File]::WriteAllText($timelineContent.FullName, $json, $utf8NoBom)
    [System.IO.File]::WriteAllText(($timelineContent.FullName + '.bak'), $json, $utf8NoBom)
    $timelineDir = $timelineContent.DirectoryName
    [System.IO.File]::WriteAllText((Join-Path $timelineDir 'template-2.tmp'), $json, $utf8NoBom)
    [System.IO.File]::WriteAllText((Join-Path $timelineDir 'template.tmp'), $json, $utf8NoBom)
}

$metaPath = Join-Path $targetPath 'draft_meta_info.json'
$meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
$meta.draft_id = [guid]::NewGuid().ToString().ToUpperInvariant()
$meta.draft_name = $draftName
$meta.draft_fold_path = ($targetPath -replace '\\', '/')
$meta.draft_root_path = ([System.IO.Path]::GetDirectoryName($targetPath) -replace '\\', '/')
$meta.draft_cover = 'draft_cover.jpg'
$now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000
$meta.tm_draft_create = $now
$meta.tm_draft_modified = $now
[System.IO.File]::WriteAllText(
    $metaPath,
    ($meta | ConvertTo-Json -Depth 100 -Compress),
    $utf8NoBom
)

$profile = [ordered]@{
    profile = 'DWG'
    canvas = '1920x1080 @ 30fps'
    caption = 'warm ivory, subtle dark stroke, lower safe zone'
    retained_effect = 'Flying Dust at 35% intensity'
    background_music = 'Injected by Footage Video Builder from DWG_25min_music_cue_sheet.csv'
    narration = 'Replaced by Footage Video Builder'
    footage = 'Replaced by Footage Video Builder; nature-first DWG selection rules'
}
[System.IO.File]::WriteAllText(
    (Join-Path $targetPath 'DWG_TEMPLATE_PROFILE.json'),
    ($profile | ConvertTo-Json -Depth 10),
    $utf8NoBom
)

Write-Output $targetPath
