param(
    [ValidateSet('gates','live')][string]$Variant='live',
    [ValidateSet('map','interface','pnr','pgm','compile')][string]$Flow='map',
    [switch]$Generate
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$work=Join-Path $repo "tmp/blue-plate-video-base/$Variant"
$efinity='D:/Efinity'
if ($env:EFINITY_HOME) { $efinity=$env:EFINITY_HOME }
$python=Join-Path $efinity 'python311/bin/python.exe'
$env:PYTHONHOME=Join-Path $efinity 'python311'
if ($Generate) {
    & $python -B (Join-Path $PSScriptRoot 'generate.py') $Variant
    if ($LASTEXITCODE -ne 0) { throw 'Candidate generation failed' }
}
if (!(Test-Path -LiteralPath (Join-Path $work 'inputs.json'))) { throw 'Generate candidate first' }
$name="blue_plate_video_$Variant"
Push-Location -LiteralPath $work
try {
    & (Join-Path $efinity 'bin/efx_run.bat') "$name.xml" --flow $Flow --output_dir outflow 2>&1 | Tee-Object -FilePath "$Flow.console.log"
    if ($LASTEXITCODE -ne 0) { throw "Efinity $Flow failed: $LASTEXITCODE" }
    if ($Flow -in @('map','compile')) {
        & (Join-Path $repo 'tools/check-edge-build.ps1') -ReportPath "outflow/$name.map.rpt"
    }
    & $python -B (Join-Path $PSScriptRoot 'verify.py') $Variant
    if ($LASTEXITCODE -ne 0) { throw 'Candidate verification failed' }
} finally { Pop-Location }
