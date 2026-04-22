#requires -Version 5.1
<#
 תיקון: טוען במפורש גם את System.IO.Compression וגם את System.IO.Compression.FileSystem
 כדי לוודא שהסוג ZipArchiveMode קיים ב-Windows PowerShell 5.1.
#>

# טוען את האסמבליז הנחוצים
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ErrorActionPreference = "Stop"

# תיקיית המקור היא התיקייה של הסקריפט
$Root   = $PSScriptRoot
$Name   = Split-Path -Leaf $Root
$ZipDir = Join-Path $Root "Zips"
$Zip    = Join-Path $ZipDir ("{0}.zip" -f $Name)

# תבניות שנרצה להחריג (ניתן להוסיף לפי צורך)
$ExcludeDirs  = @("Zips", ".git", ".svn", ".hg", "node_modules", ".venv", "__pycache__")
$ExcludeFiles = @("zip-it.ps1", "zip-it.bat")

# יצירת תיקיית Zips אם לא קיימת
if (-not (Test-Path -LiteralPath $ZipDir)) {
    New-Item -ItemType Directory -Path $ZipDir | Out-Null
}

# פותחים את ה-zip במצב Update (נוצר אם לא קיים)
$fs = [System.IO.File]::Open($Zip, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)

try {
    # שימוש מפורש בשם המרחב עבור ZipArchiveMode
    $mode = [System.IO.Compression.ZipArchiveMode]::Update
    $archive = New-Object System.IO.Compression.ZipArchive($fs, $mode, $false)

    $added   = 0
    $updated = 0
    $skipped = 0
    $removed = 0

    function Is-UnderExcludedDir($fullPath) {
        foreach ($d in $ExcludeDirs) {
            $ex = Join-Path $Root $d
            if ($fullPath.StartsWith($ex, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        }
        return $false
    }

    $files = Get-ChildItem -Path $Root -Recurse -File -Force | Where-Object {
        -not (Is-UnderExcludedDir $_.FullName) -and
        ($_.FullName -ne $Zip) -and
        ($ExcludeFiles -notcontains $_.Name)
    }

    foreach ($f in $files) {
        $rel = $f.FullName.Substring($Root.Length).TrimStart('\','/')
        $rel = $rel -replace '\\','/'

        $entry = $archive.GetEntry($rel)
        if ($entry -eq $null) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $f.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
            $added++
        } else {
            $fileTime = $f.LastWriteTimeUtc
            $zipTime  = $entry.LastWriteTime.UtcDateTime
            if ($fileTime -gt $zipTime -or $entry.Length -ne $f.Length) {
                $entry.Delete()
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $f.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
                $updated++
            } else {
                $skipped++
            }
        }
    }

    $toRemove = New-Object System.Collections.Generic.List[System.Object]
    foreach ($entry in $archive.Entries) {
        $entryFull = Join-Path $Root ($entry.FullName -replace '/','\')
        if (Is-UnderExcludedDir $entryFull) { continue }
        if ($entryFull -eq $Zip) { continue }
        if ($ExcludeFiles -contains (Split-Path -Leaf $entryFull)) { continue }
        if (-not (Test-Path -LiteralPath $entryFull)) {
            $toRemove.Add($entry) | Out-Null
        }
    }
    foreach ($e in $toRemove) { $e.Delete(); $removed++ }

    Write-Host "`nDone."
    Write-Host ("Zip: {0}" -f $Zip)
    Write-Host ("Added:   {0}" -f $added)
    Write-Host ("Updated: {0}" -f $updated)
    Write-Host ("Removed: {0}" -f $removed)
    Write-Host ("Unchanged: {0}" -f $skipped)
}
finally {
    if ($archive) { $archive.Dispose() }
    if ($fs) { $fs.Dispose() }
}
