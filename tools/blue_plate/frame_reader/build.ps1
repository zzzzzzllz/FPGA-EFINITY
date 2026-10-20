$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$efinity='D:/Efinity'
if ($env:EFINITY_HOME) { $efinity=$env:EFINITY_HOME }
$env:PYTHONHOME=Join-Path $efinity 'python311'
$python=Join-Path $efinity 'python311/bin/python.exe'
& $python -B (Join-Path $PSScriptRoot 'tests/prepare_synthesis.py')
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed' }
$work=Join-Path $repo 'tmp/blue-plate-frame-reader/synthesis'
Push-Location -LiteralPath $work
try {
 & (Join-Path $efinity 'bin/efx_run.bat') frame_reader.xml --flow map --output_dir out 2>&1 | Tee-Object -FilePath map.console.log
 if ($LASTEXITCODE -ne 0) { throw 'Efinity map failed' }
 & $python -B (Join-Path $PSScriptRoot 'tests/verify_synthesis.py')
 if ($LASTEXITCODE -ne 0) { throw 'Synthesis verification failed' }
} finally { Pop-Location }
