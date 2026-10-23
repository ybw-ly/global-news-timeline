param(
    [string]$Name = "经纬 Global News Timeline"
)

$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktop = [Environment]::GetFolderPath("Desktop")
$target = Join-Path $project "launch-desktop.bat"
$icon = Join-Path $project "web\meridian.ico"

if (-not (Test-Path -LiteralPath $target)) {
    throw "Launcher not found: $target"
}

$shell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop "$Name.lnk"
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $project
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "经纬 · 全球新闻时间线"
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Output "Created: $shortcutPath"
