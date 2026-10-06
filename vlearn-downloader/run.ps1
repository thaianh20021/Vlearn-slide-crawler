$ErrorActionPreference = 'Stop'

try {
    $explicitPython = $null
    $gui = $false
    $forwardArgs = @()
    for ($i = 0; $i -lt $args.Count; $i++) {
        if ($args[$i] -eq '-Python') {
            if ($i + 1 -ge $args.Count -or $args[$i + 1] -like '-*') {
                throw '-Python requires a Python executable path.'
            }
            $explicitPython = $args[++$i]
            if (-not (Test-Path -LiteralPath $explicitPython -PathType Leaf)) {
                throw "Python executable not found: $explicitPython"
            }
        } elseif ($args[$i] -in @('-Gui', '--gui')) {
            $gui = $true
        } else {
            $forwardArgs += $args[$i]
        }
    }

    $venv = Join-Path $PSScriptRoot '.venv'
    $python = Join-Path $venv 'Scripts\python.exe'

    if (-not (Test-Path -LiteralPath $venv)) {
        if ($explicitPython) {
            $candidates = @($explicitPython)
        } else {
            $candidates = @(Get-Command py, python -CommandType Application -ErrorAction SilentlyContinue |
                Where-Object { $_.Source -notlike '*\WindowsApps\*' } |
                Select-Object -ExpandProperty Source)
            $candidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        }
        $bootstrap = $null
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
            try {
                & $candidate -c 'import sys; sys.exit(0 if sys.version_info.major == 3 else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $bootstrap = $candidate
                    break
                }
            } catch { continue }
        }
        if (-not $bootstrap) {
            throw 'Working Python 3 not found. Rerun with -Python "C:\path\to\python.exe".'
        }
        & $bootstrap -m venv $venv
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Virtual environment Python not found: $python"
    }

    $dependencyCheck = @'
import sys
try:
    import playwright.sync_api
except Exception as error:
    print('Playwright dependency check failed: ' + str(error))
    sys.exit(1)
'@
    & $python -c $dependencyCheck
    if ($LASTEXITCODE -ne 0) {
        & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) {
            $installExitCode = $LASTEXITCODE
            [Console]::Error.WriteLine('Playwright installation failed. Check pip output above.')
            exit $installExitCode
        }
        & $python -c $dependencyCheck
        if ($LASTEXITCODE -ne 0) {
            $dependencyExitCode = $LASTEXITCODE
            [Console]::Error.WriteLine('Playwright remains unavailable after installation.')
            exit $dependencyExitCode
        }
    }

    $entryPoint = if ($gui -or $forwardArgs.Count -eq 0) { 'gui.py' } else { 'main.py' }
    & $python (Join-Path $PSScriptRoot $entryPoint) @forwardArgs
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
