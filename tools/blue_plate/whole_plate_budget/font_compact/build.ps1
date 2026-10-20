$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$env:PYTHONHOME='D:/Efinity/python311'
Push-Location -LiteralPath (Join-Path $repo 'tmp/blue-plate-whole-plate-budget/font-compact/synthesis')
try {
    & 'D:/Efinity/bin/efx_run.bat' plate_osd_compact.xml --flow map --output_dir out *> map.console.log
    if ($LASTEXITCODE -ne 0) { throw 'Efinity map failed; see map.console.log' }
} finally { Pop-Location }
