# Run this INSIDE the Windows 11 Parallels VM, in a normal (non-admin) PowerShell window.
# It copies your Samsung Notes local data (read-only copy, nothing on the source is touched)
# into a zip on your Desktop that you can then move to the Mac side.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File collect_samsung_notes.ps1

$ErrorActionPreference = "Stop"

Write-Host "Looking for the Samsung Notes package folder..."

$packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
$pkg = Get-ChildItem -Path $packagesRoot -Directory -Filter "SAMSUNGELECTRONICSCoLtd.SamsungNotes_*" -ErrorAction SilentlyContinue |
       Select-Object -First 1

if (-not $pkg) {
    Write-Host "Could not find a SamsungNotes package folder under:"
    Write-Host "  $packagesRoot"
    Write-Host "Make sure Samsung Notes for Windows is installed and has been opened at least once."
    Write-Host "You can also search manually: dir /s /b `"$packagesRoot\SamsungNotes*`""
    exit 1
}

Write-Host "Found: $($pkg.FullName)"

$localState = Join-Path $pkg.FullName "LocalState"
if (-not (Test-Path $localState)) {
    Write-Host "No LocalState folder found at: $localState"
    exit 1
}

$stage = Join-Path $env:TEMP "sn_export_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

$toCopy = @("sdoc", "wdoc")
foreach ($folder in $toCopy) {
    $src = Join-Path $localState $folder
    if (Test-Path $src) {
        Write-Host "Copying $folder ..."
        Copy-Item -Path $src -Destination (Join-Path $stage $folder) -Recurse -Force
    } else {
        Write-Host "(no $folder folder found, skipping)"
    }
}

# Dump a plain listing too, in case any files have unusual extensions/attributes
Get-ChildItem -Path $localState -Recurse -File |
    Select-Object FullName, Length, LastWriteTime |
    Export-Csv -Path (Join-Path $stage "localstate_listing.csv") -NoTypeInformation

# Prefer the Parallels shared Mac Downloads folder so the zip lands on the
# Mac side automatically; fall back to the Windows Desktop otherwise.
$macDownloads = "\\Mac\Home\Downloads"
if (Test-Path $macDownloads) {
    $destDir = $macDownloads
} else {
    $destDir = [Environment]::GetFolderPath("Desktop")
}

$zipPath = Join-Path $destDir "samsung_notes_export.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Write-Host "Zipping to $zipPath ..."
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath

Write-Host ""
Write-Host "Done. Created:"
Write-Host "  $zipPath"
if ($destDir -eq $macDownloads) {
    Write-Host ""
    Write-Host "This is your Mac's Downloads folder (via the Mac shared drive) -- no transfer needed."
} else {
    Write-Host ""
    Write-Host "Next: move samsung_notes_export.zip to the Mac (shared folder, AirDrop-via-cloud, USB, etc.)"
    Write-Host "and tell Claude where it landed."
}
