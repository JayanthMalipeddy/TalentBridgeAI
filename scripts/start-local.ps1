$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force -Path "$projectRoot\.cache" | Out-Null
$backend = Start-Process -FilePath "$projectRoot\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8000','--no-access-log' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\.cache\release-backend.log" -RedirectStandardError "$projectRoot\.cache\release-backend-errors.log" -PassThru
$frontend = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList 'node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5173','--strictPort' -WorkingDirectory "$projectRoot\frontend" -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\.cache\release-frontend.log" -RedirectStandardError "$projectRoot\.cache\release-frontend-errors.log" -PassThru
@{backend_pid=$backend.Id; frontend_pid=$frontend.Id} | ConvertTo-Json | Set-Content "$projectRoot\.cache\release-processes.json"
Write-Output 'Local services started in hidden processes. Frontend: http://localhost:5173/app'
