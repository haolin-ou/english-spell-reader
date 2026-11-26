[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Done {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[DONE] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Fail {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Invoke-ExternalStep {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$FailureMessage,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$Arguments = @()
    )

    Write-Info $Label
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail ("{0} Exit code: {1}" -f $FailureMessage, $LASTEXITCODE)
    }
}

function Invoke-ExternalStatus {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$Arguments = @()
    )

    $nativePreference = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNativePreference = $null
    if ($nativePreference) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        & $FilePath @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        if ($nativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
}

function Test-VenvPip {
    param([Parameter(Mandatory = $true)][string]$VenvPython)

    if (-not (Test-Path $VenvPython)) {
        return $false
    }

    return (Invoke-ExternalStatus -FilePath $VenvPython -Arguments @("-m", "pip", "--version"))
}

function Initialize-VenvPip {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$VenvPython,
        [Parameter(Mandatory = $true)][hashtable]$PythonCommand
    )

    if (Test-VenvPip -VenvPython $VenvPython) {
        return
    }

    Write-Warn "Virtual environment pip is not usable. Attempting repair with ensurepip..."
    if (Invoke-ExternalStatus -FilePath $VenvPython -Arguments @("-m", "ensurepip", "--upgrade")) {
        if (Test-VenvPip -VenvPython $VenvPython) {
            return
        }
    }

    Write-Warn "Existing virtual environment pip is still broken. Recreating .venv..."
    $venvDir = Join-Path $RepoRoot ".venv"
    if (Test-Path $venvDir) {
        Remove-Item -Path $venvDir -Recurse -Force
    }

    Invoke-ExternalStep -Label "Creating virtual environment..." -FailureMessage "Failed to create .venv." -FilePath $PythonCommand.FilePath -Arguments @($PythonCommand.Arguments + @("-m", "venv", ".venv"))

    if (-not (Test-Path $VenvPython)) {
        Fail "Virtual environment setup completed, but .venv\Scripts\python.exe was not found."
    }

    if (-not (Test-VenvPip -VenvPython $VenvPython)) {
        Invoke-ExternalStep -Label "Bootstrapping pip with ensurepip..." -FailureMessage "Failed to bootstrap pip in .venv." -FilePath $VenvPython -Arguments @("-m", "ensurepip", "--upgrade")
    }

    if (-not (Test-VenvPip -VenvPython $VenvPython)) {
        Fail "Virtual environment pip is still not usable after recreate."
    }
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$Arguments = @()
    )

    $command = Get-Command $FilePath -ErrorAction SilentlyContinue
    if (-not $command) {
        return $false
    }

    $source = [string]$command.Source
    $definition = [string]$command.Definition
    if ($source -like "*\WindowsApps\python*.exe" -or $definition -like "*\WindowsApps\python*.exe") {
        return $false
    }

    $nativePreference = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNativePreference = $null
    if ($nativePreference) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        & $FilePath @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        if ($nativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
}

function Get-KnownPythonCandidates {
    $paths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python311\python.exe")
    )

    foreach ($path in $paths) {
        if ($path -and (Test-Path $path)) {
            @{ FilePath = $path; Arguments = @() }
        }
    }
}

function Find-PythonCommand {
    $candidates = @(
        @{ FilePath = "py"; Arguments = @("-3.11") },
        @{ FilePath = "python"; Arguments = @() },
        @{ FilePath = "python3"; Arguments = @() }
    )

    $candidates += @(Get-KnownPythonCandidates)

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -FilePath $candidate.FilePath -Arguments $candidate.Arguments) {
            return $candidate
        }
    }

    return $null
}

function Show-PiperAssetStatus {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $assetDir = Join-Path $RepoRoot "app\voices\piper"
    $expectedMessage = "Packaging expects Piper model files under app\\voices\\piper as .onnx plus matching .onnx.json files."

    if (-not (Test-Path $assetDir)) {
        Write-Warn "No bundled Piper asset directory was found."
        Write-Warn $expectedMessage
        return
    }

    $modelFiles = @(Get-ChildItem -Path $assetDir -Filter "*.onnx" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $configFiles = @(Get-ChildItem -Path $assetDir -Filter "*.onnx.json" -File -ErrorAction SilentlyContinue | Sort-Object Name)

    if ($modelFiles.Count -eq 0 -and $configFiles.Count -eq 0) {
        Write-Warn "The Piper asset directory exists, but no model files were found."
        Write-Warn $expectedMessage
        return
    }

    $missingConfigs = @()
    foreach ($modelFile in $modelFiles) {
        $expectedConfig = "{0}.json" -f $modelFile.Name
        if (-not (Test-Path (Join-Path $assetDir $expectedConfig))) {
            $missingConfigs += $expectedConfig
        }
    }

    if ($modelFiles.Count -eq 0) {
        Write-Warn "No .onnx model files were found in app\\voices\\piper."
    }

    if ($configFiles.Count -eq 0) {
        Write-Warn "No .onnx.json config files were found in app\\voices\\piper."
    }

    if ($missingConfigs.Count -gt 0) {
        Write-Warn ("Missing Piper config file(s): {0}" -f ($missingConfigs -join ", "))
    }

    if ($modelFiles.Count -gt 0 -and $configFiles.Count -gt 0 -and $missingConfigs.Count -eq 0) {
        Write-Info ("Bundled Piper model assets found in {0}." -f $assetDir)
        foreach ($modelFile in $modelFiles) {
            Write-Info ("  Piper model: {0}" -f $modelFile.Name)
        }
        return
    }

    Write-Warn $expectedMessage
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
    Set-Location $repoRoot

    $pythonCommand = Find-PythonCommand
    if (-not $pythonCommand) {
        Write-Host "[ERROR] Python 3.11 or newer was not found." -ForegroundColor Red
        Write-Host "[ERROR] Install Python from https://www.python.org/downloads/windows/ and enable Add python.exe to PATH." -ForegroundColor Red
        Write-Host "[ERROR] After installing, close this window, open a new terminal, and run the build again." -ForegroundColor Red
        exit 1
    }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Invoke-ExternalStep -Label "Creating virtual environment..." -FailureMessage "Failed to create .venv." -FilePath $pythonCommand.FilePath -Arguments @($pythonCommand.Arguments + @("-m", "venv", ".venv"))
    } else {
        Write-Info "Using existing virtual environment."
    }

    if (-not (Test-Path $venvPython)) {
        Fail "Virtual environment setup completed, but .venv\Scripts\python.exe was not found."
    }

    Initialize-VenvPip -RepoRoot $repoRoot -VenvPython $venvPython -PythonCommand $pythonCommand
    Invoke-ExternalStep -Label "Upgrading pip, setuptools, and wheel..." -FailureMessage "Failed to upgrade packaging tools." -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    Invoke-ExternalStep -Label "Installing project and dev dependencies..." -FailureMessage "Failed to install .[dev,speech,build]." -FilePath $venvPython -Arguments @("-m", "pip", "install", "-e", ".[dev,speech,build]")
    Invoke-ExternalStep -Label "Running pytest..." -FailureMessage "pytest failed. Build stopped." -FilePath $venvPython -Arguments @("-m", "pytest")
    Show-PiperAssetStatus -RepoRoot $repoRoot
    Invoke-ExternalStep -Label "Running Piper smoke test..." -FailureMessage "Piper smoke test failed. Build stopped." -FilePath $venvPython -Arguments @("scripts\piper_smoke.py")

    $specPath = Join-Path $repoRoot "spelling_reader.spec"
    if (-not (Test-Path $specPath)) {
        Fail "spelling_reader.spec was not found. Build cannot continue."
    }

    Invoke-ExternalStep -Label "Running PyInstaller..." -FailureMessage "PyInstaller build failed." -FilePath $venvPython -Arguments @("-m", "PyInstaller", $specPath)

    $expectedExe = Join-Path $repoRoot "dist\EnglishSpellReader.exe"
    if (Test-Path $expectedExe) {
        Invoke-ExternalStep -Label "Running packaged Piper smoke test..." -FailureMessage "Packaged Piper smoke test failed. Build stopped." -FilePath $venvPython -Arguments @("scripts\piper_exe_smoke.py", $expectedExe)
        Write-Done "Executable created at: $expectedExe"
        exit 0
    }

    $distDir = Join-Path $repoRoot "dist"
    $fallbackExe = Get-ChildItem -Path $distDir -Filter "EnglishSpellReader*.exe" -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($fallbackExe) {
        Invoke-ExternalStep -Label "Running packaged Piper smoke test..." -FailureMessage "Packaged Piper smoke test failed. Build stopped." -FilePath $venvPython -Arguments @("scripts\piper_exe_smoke.py", $fallbackExe.FullName)
        Write-Done "Executable created at: $($fallbackExe.FullName)"
        exit 0
    }

    Write-Done "Build command completed, but no executable was found at the expected path. Check: $distDir"
    exit 0
}
catch {
    Fail ("Unhandled exception: {0}" -f $_.Exception.Message)
}
