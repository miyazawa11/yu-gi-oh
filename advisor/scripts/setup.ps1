param([string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
# 日本語コメントを含む依存ファイルを Windows の既定文字コードに依存せず読みます。
$env:PYTHONUTF8 = '1'
Set-Location (Join-Path $PSScriptRoot '..')
function Assert-Success {
    if ($LASTEXITCODE -ne 0) { throw "コマンドが終了コード $LASTEXITCODE で失敗しました" }
}
& $PythonExecutable -c "import sys; assert sys.version_info[:2] == (3,12), 'Python 3.12 が必要です'"
Assert-Success
if (-not (Test-Path '.venv')) {
    & $PythonExecutable -m venv .venv
    Assert-Success
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
Assert-Success
& .\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
Assert-Success
& .\.venv\Scripts\python.exe -m pip check
Assert-Success
