param(
    [string]$Python = 'python',
    [string]$Config = '',
    [switch]$Once,
    [switch]$Apply
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
if (-not $Config) { $Config=Join-Path $projectRoot 'data/private/scheduled-news/settings.json' }
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { throw 'Create the private settings file from config/scheduled-news.example.json first.' }
$workerCommand=if ($Once) { 'once' } else { 'run' }
$workerArgs=@('-B','-m','backend.app.scheduled_news',$workerCommand,'--config',$Config)
if ($Apply) { $workerArgs+='--apply' }
$previousPath=$env:PYTHONPATH
try {
    $env:PYTHONPATH=(Join-Path $projectRoot 'analysis')+';'+$projectRoot+';'+$previousPath
    Push-Location -LiteralPath $projectRoot
    try { & $Python @workerArgs; exit $LASTEXITCODE } finally { Pop-Location }
} finally { $env:PYTHONPATH=$previousPath }
