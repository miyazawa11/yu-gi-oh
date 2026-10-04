$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
function Assert-Success {
    if ($LASTEXITCODE -ne 0) { throw "コマンドが終了コード $LASTEXITCODE で失敗しました" }
}
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)"
Assert-Success
if (-not (Test-Path '.venv')) {
    py -3.12 -m venv .venv
    Assert-Success
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
Assert-Success
& .\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
Assert-Success
& .\.venv\Scripts\python.exe -m pip check
Assert-Success
