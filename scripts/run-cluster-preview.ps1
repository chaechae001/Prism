param(
    [ValidateSet('scheduled-sbs', 'anchor92')]
    [string]$Dataset = 'scheduled-sbs',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8006,
    [string]$Python = 'python',
    [string]$FrontendOrigin = 'http://127.0.0.1:5186'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$datasetPath = Join-Path $projectRoot "testdata/clustering/$Dataset"
$settings = @{
    PRISM_DATA_SOURCE = 'cluster-local'
    CLUSTER_RESULTS_DIR = $datasetPath
    CLUSTER_IMAGES_PATH = (Join-Path $datasetPath 'images.json')
    PRISM_CHAT_ENABLED = '0'
    CORS_ORIGINS = $FrontendOrigin
}
$previous = @{}
foreach ($name in $settings.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
Push-Location $projectRoot
try {
    Write-Host "군집 결과 미리보기: $Dataset / http://127.0.0.1:$Port"
    Write-Host '저장된 파일만 조회합니다. DB 저장, 수집, 모델 실행, LLM 호출은 하지 않습니다.'
    & $Python -B -m uvicorn backend.app.api:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw '미리보기 서버를 시작하지 못했습니다.' }
}
finally {
    Pop-Location
    foreach ($name in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
