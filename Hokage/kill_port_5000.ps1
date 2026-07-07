$port = 5000
$connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($connections) {
    foreach ($conn in $connections) {
        $proc_id = $conn.OwningProcess
        if ($proc_id -gt 0) {
            Write-Host "Killing process $proc_id listening on port $port"
            Stop-Process -Id $proc_id -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Host "No process listening on port $port"
}
