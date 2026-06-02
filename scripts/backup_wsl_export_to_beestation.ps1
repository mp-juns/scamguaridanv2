param(
  [string]$Distro = "Ubuntu",
  [string]$BackupRoot = "$env:USERPROFILE\BeeStation\A-EYE\ScamGuardianBackups"
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Dest = Join-Path $BackupRoot "wsl-$Distro-$Stamp"
$Archive = Join-Path $Dest "$Distro.tar"

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "This creates a restorable WSL export instead of copying a live ext4.vhdx."
Write-Host "All WSL sessions for this distro will be stopped."
wsl.exe --shutdown
wsl.exe --export $Distro $Archive

Write-Host "WSL export written to: $Archive"
Write-Host "Restore example:"
Write-Host "  wsl.exe --import ${Distro}-restored C:\WSL\${Distro}-restored $Archive"
