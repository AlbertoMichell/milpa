$path = (Join-Path $PSScriptRoot '..\start.ps1' | Resolve-Path)
$errs = $null
$tok = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tok, [ref]$errs)
if ($errs -and $errs.Count -gt 0) {
    $errs | ForEach-Object { Write-Host $_.Message; Write-Host ("Line " + $_.Extent.StartLineNumber + ": " + $_.Extent.Text) }
    exit 1
}
Write-Host 'Parse OK'
