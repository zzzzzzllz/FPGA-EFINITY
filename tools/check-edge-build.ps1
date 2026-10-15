param(
    [Parameter(Mandatory=$true)][string]$ReportPath
)
$ErrorActionPreference = 'Stop'
# RTL simulation missed an undriven pixel bus in Efinity's synthesized circuit.
$report = Get-Content -LiteralPath $ReportPath -Raw
$zeroBits = [regex]::Matches($report, "'checker0/u_vid_rx_align/fi_data\[\d+\]'.*\(optimized to 0\)")
$rgbZeroBits = @($zeroBits | Where-Object {
    $bit = [int]([regex]::Match($_.Value, 'fi_data\[(\d+)\]').Groups[1].Value)
    ($bit -lt 24) -or ($bit -ge 32 -and $bit -lt 56)
})
if ($zeroBits.Count -ge 64 -or $rgbZeroBits.Count -ge 48) {
    throw 'DDR camera pixel input was synthesized as all zero. Do not load this bitstream.'
}
$netlistPath = [IO.Path]::ChangeExtension($ReportPath, '.v')
if (Test-Path -LiteralPath $netlistPath) {
    $netlist = Get-Content -LiteralPath $netlistPath -Raw
    if ($netlist.Contains('checker0/control/')) {
        foreach ($fifo in @('capture_fifo', 'result_fifo')) {
            $pattern = 'EFX_FF\s+\\[^\s]*checker0/' + $fifo + '/upper\[(\d+)\]~FF\s+\(\.D\(([^)]+)\)'
            $rgbInputs = @([regex]::Matches($netlist, $pattern) | Where-Object {
                $bit = [int]$_.Groups[1].Value
                (($fifo -eq 'capture_fifo' -and $bit -lt 48) -or
                 ($fifo -eq 'result_fifo' -and (($bit -lt 24) -or ($bit -ge 32 -and $bit -lt 56)))) -and
                    ($_.Groups[2].Value -notmatch "^\s*\d+'[bhd]0+\s*$")
            })
            if ($rgbInputs.Count -ne 48) {
                throw "M08 $fifo RGB input has $($rgbInputs.Count)/48 nonconstant registered bits. Inspect synthesis before loading."
            }
        }
    }
}
Write-Output 'PASS: synthesized DDR camera pixel input is not constant zero.'
