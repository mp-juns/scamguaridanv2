param(
  [string]$Distro = "Ubuntu",
  [Parameter(Mandatory = $true)][string]$Server,
  [Parameter(Mandatory = $true)][string]$Share,
  [string]$Subdir = "A-EYE\ScamGuardianBackups",
  [string]$User = ""
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Root = "\\$Server\$Share"
$DriveName = "BEE"

Write-Host "BeeStation SMB root: $Root"
Write-Host "If this asks for credentials, use the BeeStation local account, not your Synology web account."

if (Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue) {
  Remove-PSDrive -Name $DriveName -Force
}

if ($User) {
  $Credential = Get-Credential -UserName $User -Message "BeeStation local SMB account"
  New-PSDrive -Name $DriveName -PSProvider FileSystem -Root $Root -Credential $Credential | Out-Null
} else {
  New-PSDrive -Name $DriveName -PSProvider FileSystem -Root $Root | Out-Null
}

$Dest = "${DriveName}:\$Subdir\wsl-$Distro-$Stamp"
$Archive = Join-Path $Dest "$Distro.tar"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "This creates a restorable WSL export instead of copying a live ext4.vhdx."
Write-Host "All WSL sessions for this distro will be stopped."
wsl.exe --shutdown
wsl.exe --export $Distro $Archive

Write-Host "WSL export written to: $Archive"
Write-Host "Restore example:"
Write-Host "  wsl.exe --import ${Distro}-restored C:\WSL\${Distro}-restored $Archive"
