$Timestamp = Get-Date -Format "yyyy_MM_dd"
$LogDir = ".\pipeline\logs"
$PythonExe = ".venv\Scripts\python.exe"
$PipelineDir = "C:\Users\shure\TaroBall\Gtech\ISYE-7406-OAN\Project"

cd $PipelineDir

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment not found at: $PythonExe"
    exit
}

$Tasks = "pl_api_to_bronze.py", "pl_bronze_to_silver.py", "pl_silver_to_gold.py"

foreach ($Task in $Tasks) {

    $LogFile = "$LogDir\$($Task)_$($Timestamp).log"
    
    Write-Host "Executing $Task..." -ForegroundColor Cyan
    & $PythonExe ".\pipeline\$Task" > $LogFile 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Completed $Task." -ForegroundColor Green
    } else {
        Write-Host "Error in $Task (Exit Code: $LASTEXITCODE). Check $LogFile" -ForegroundColor Red
    }
}

Write-Host "All scripts processed." -ForegroundColor Yellow