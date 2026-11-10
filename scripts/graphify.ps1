param(
    [ValidateSet('refresh', 'query', 'explain', 'path', 'status')]
    [string]$Action = 'status',
    [string]$Question = '',
    [string]$Target = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$graphPython = Join-Path $projectRoot '.cache/graphify-tools/graphifyy/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $graphPython)) { throw 'Pinned Graphify tool is missing. See docs/graphify-setup.md.' }
& $graphPython -I (Join-Path $PSScriptRoot 'graphify_local.py') $Action $Question $Target
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
