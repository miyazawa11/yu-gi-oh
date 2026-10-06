# プロジェクト内のOllamaを起動します。既存サービスがある場合は再起動しません。
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$ollamaExecutable = Join-Path $projectRoot 'tools\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaExecutable)) {
    throw 'tools/ollama/ollama.exe がありません。Ollamaの準備を先に行ってください。'
}
try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    Write-Output 'Ollamaは既に起動しています。'
    exit 0
} catch { }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot 'tools\ollama-models'
$env:OLLAMA_NUM_PARALLEL = '1'
$logDirectory = Join-Path $projectRoot 'advisor\artifacts\ollama'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$server = Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'server.stderr.log')
$server.Id | Set-Content -LiteralPath (Join-Path $logDirectory 'server.pid')
Write-Output "Ollama起動 PID=$($server.Id)。モデル保存先: $env:OLLAMA_MODELS"
