param([Parameter(Mandatory=$true)][string]$Project)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$source = (Resolve-Path -LiteralPath $Project).Path
if (-not $source.StartsWith((Join-Path $repo 'coding') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Project must be inside coding' }
$name = Split-Path $source -Leaf
$work = [IO.Path]::GetFullPath((Join-Path $repo "tmp\build\$name"))
if (-not $work.StartsWith((Join-Path $repo 'tmp\build') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build path outside tmp/build' }
if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
New-Item -ItemType Directory -Path $work -Force | Out-Null
Get-ChildItem -LiteralPath $source | Where-Object { $_.Name -notin @('release','tests','config') -and $_.Extension -notin @('.cmd','.py') } | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $work -Recurse }
Push-Location -LiteralPath $work
try {
    & "$env:EFINITY_HOME\bin\efx_run.bat" ti60f225_oob.xml --flow compile --output_dir outflow
    if ($LASTEXITCODE -ne 0) { throw "Efinity build failed: $LASTEXITCODE" }
    if ($name -in @('edge-30fps','edge-quality-30fps')) {
        & (Join-Path $PSScriptRoot 'check-edge-build.ps1') -ReportPath (Join-Path $work 'outflow\ti60f225_oob.map.rpt')
        if ($LASTEXITCODE -ne 0) { throw 'Synthesis connectivity check failed' }
    }
    & "$env:EFINITY_HOME\python311\bin\python.exe" -B (Join-Path $PSScriptRoot 'verify-project.py') $source --build-dir $work
    if ($LASTEXITCODE -ne 0) { throw 'Build result verification failed' }
} finally { Pop-Location }
Write-Output "Built bitstream: $work\outflow\ti60f225_oob.bit"
Write-Output 'The frozen release bitstream was not overwritten.'
