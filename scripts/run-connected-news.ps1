param(
    [string]$Namespace = 'scheduled-local-test',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8006,
    [string]$Python = 'python',
    [string]$FrontendOrigin = 'http://127.0.0.1:5186',
    [switch]$EnableAccounts,
    [switch]$DisableAccounts,
    [switch]$EnableAIExtensions,
    [switch]$EnableRag
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$settings = @{
    PRISM_DATA_SOURCE = 'cluster-db'
    PRISM_CLUSTER_NAMESPACE = $Namespace
    PRISM_CHAT_ENABLED = '1'
    PRISM_CLUSTER_CHAT_ENABLED = '1'
    PRISM_EDITORIAL_ENABLED = '1'
    PRISM_BODY_PREVIEW_ENABLED = '1'
    PRISM_ACCOUNTS_ENABLED = $(if ($EnableAccounts -and -not $DisableAccounts) { '1' } else { '0' })
    PRISM_LANGCHAIN_ENABLED = $(if ($EnableAIExtensions) { '1' } else { '0' })
    PRISM_LLM_METRICS_ENABLED = $(if ($EnableAIExtensions) { '1' } else { '0' })
    PRISM_RAG_ENABLED = $(if ($EnableRag) { '1' } else { '0' })
    CORS_ORIGINS = $FrontendOrigin
}
$previous = @{}
foreach ($name in $settings.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
Push-Location $projectRoot
try {
    Write-Host "DB 뉴스 및 본문 기반 AI 대화: http://127.0.0.1:$Port"
    Write-Host 'DB와 AI 설정은 서버의 비공개 환경 파일에서 읽습니다. 스키마 변경이나 자동 수집은 하지 않습니다.'
    if ($settings.PRISM_ACCOUNTS_ENABLED -eq '0') { Write-Host '비회원 모드: 로그인·회원가입·인증 메일은 사용하지 않습니다. 기록은 브라우저에 저장합니다.' }
    & $Python -B -m uvicorn backend.app.api:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'DB 뉴스 서버를 시작하지 못했습니다.' }
}
finally {
    Pop-Location
    foreach ($name in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
