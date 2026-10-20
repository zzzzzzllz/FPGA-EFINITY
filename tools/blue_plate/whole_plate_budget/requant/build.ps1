$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$efinity='D:/Efinity'
$env:PYTHONHOME=Join-Path $efinity 'python311'
$python=Join-Path $efinity 'python311/bin/python.exe'
& $python -B (Join-Path $PSScriptRoot 'prepare_synthesis.py')
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed' }
Push-Location -LiteralPath (Join-Path $repo 'tmp/blue-plate-whole-plate-budget/requant/synthesis')
try {
    & (Join-Path $efinity 'bin/efx_run.bat') q31_psum_mac8.xml --flow map --output_dir out *> map.console.log
    if ($LASTEXITCODE -ne 0) { throw 'Efinity map failed; see map.console.log' }
} finally { Pop-Location }
