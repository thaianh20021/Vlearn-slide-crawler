$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'run.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

# Exercise the launcher's actual argument parsing and dispatch without opening UI.
$body = $ast.EndBlock.Statements[1].Body.Statements
$dispatch = [scriptblock]::Create(
    (($body[0..3].Extent.Text + ($body | Where-Object {
        $_.Extent.Text.StartsWith('$entryPoint =')
    }).Extent.Text) -join "`n") +
    "`n[pscustomobject]@{ Entry = `$entryPoint; Forward = @(`$forwardArgs); Python = `$explicitPython }")

$cases = @(
    @{ Args = @(); Entry = 'gui.py'; Forward = @() }
    @{ Args = @('-Gui'); Entry = 'gui.py'; Forward = @() }
    @{ Args = @('--gui'); Entry = 'gui.py'; Forward = @() }
    @{ Args = @('https://example.com/reader', '--timeout', '90'); Entry = 'main.py'; Forward = @('https://example.com/reader', '--timeout', '90') }
    @{ Args = @('--help'); Entry = 'main.py'; Forward = @('--help') }
    @{ Args = @('--gui', '--timeout', '90'); Entry = 'gui.py'; Forward = @('--timeout', '90') }
    @{ Args = @('-Python', (Get-Process -Id $PID).Path); Entry = 'gui.py'; Forward = @() }
)
foreach ($case in $cases) {
    $arguments = $case.Args
    $actual = & $dispatch @arguments
    if ($actual.Entry -ne $case.Entry -or
        ($actual.Forward -join "`0") -cne ($case.Forward -join "`0")) {
        throw "Dispatch failed: $($arguments -join ' ')"
    }
    if ($arguments.Count -and $arguments[0] -eq '-Python' -and
        $actual.Python -ne $arguments[1]) {
        throw 'Explicit Python path was not preserved.'
    }
}
foreach ($arguments in @(@('-Python'), @('-Python', '--gui'))) {
    $rejected = $false
    try { & $dispatch @arguments | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Invalid -Python argument was accepted.' }
}
Write-Output 'Launcher dispatch: 9 checks passed.'
