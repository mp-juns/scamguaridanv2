param(
  [string]$ListenAddress = "0.0.0.0",
  [int]$ListenPort = 18002,
  [Parameter(Mandatory = $true)][string]$TargetHost,
  [int]$TargetPort = 8002
)

$ErrorActionPreference = "Stop"

$ip = [System.Net.IPAddress]::Parse($ListenAddress)
$listener = [System.Net.Sockets.TcpListener]::new($ip, $ListenPort)
$listener.Start()
Write-Host "[apk-relay] listening ${ListenAddress}:${ListenPort} -> ${TargetHost}:${TargetPort}"

while ($true) {
  $client = $listener.AcceptTcpClient()
  try {
    $target = [System.Net.Sockets.TcpClient]::new($TargetHost, $TargetPort)
  } catch {
    $client.Close()
    Write-Host "[apk-relay] target connect failed: $($_.Exception.Message)"
    continue
  }

  $clientStream = $client.GetStream()
  $targetStream = $target.GetStream()

  $toTarget = [System.Threading.Thread]::new([System.Threading.ThreadStart]{
    try {
      $clientStream.CopyTo($targetStream)
    } catch {
    } finally {
      try { $target.Close() } catch {}
      try { $client.Close() } catch {}
    }
  })
  $toClient = [System.Threading.Thread]::new([System.Threading.ThreadStart]{
    try {
      $targetStream.CopyTo($clientStream)
    } catch {
    } finally {
      try { $client.Close() } catch {}
      try { $target.Close() } catch {}
    }
  })
  $toTarget.IsBackground = $true
  $toClient.IsBackground = $true
  $toTarget.Start()
  $toClient.Start()
}
