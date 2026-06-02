param(
  [string]$Distro = "Ubuntu",
  [Parameter(Mandatory = $true)][string]$Server,
  [Parameter(Mandatory = $true)][string]$Share,
  [string]$Subdir = "A-EYE\ScamGuardianBackups",
  [string]$User = "",
  [switch]$ResetExistingConnections
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Root = "\\$Server\$Share"
$DriveName = "BEE"
$TempArchive = Join-Path $env:TEMP "$Distro-$Stamp.tar"

Write-Host "BeeStation SMB root: $Root"
Write-Host "If this asks for credentials, use the BeeStation local account, not your Synology web account."

if (Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue) {
  Remove-PSDrive -Name $DriveName -Force
}

if ($ResetExistingConnections) {
  Write-Host "Removing existing SMB sessions for \\$Server before mapping..."
  cmd.exe /c "net use \\$Server\$Share /delete /y" | Out-Null
  cmd.exe /c "net use \\$Server\IPC$ /delete /y" | Out-Null
}

if ($User) {
  $Credential = Get-Credential -UserName $User -Message "BeeStation local SMB account"
  try {
    New-PSDrive -Name $DriveName -PSProvider FileSystem -Root $Root -Credential $Credential | Out-Null
  } catch {
    throw "Failed to map $Root. If Windows says multiple connections are not allowed, rerun with -ResetExistingConnections or run: net use \\$Server\$Share /delete /y"
  }
} else {
  try {
    New-PSDrive -Name $DriveName -PSProvider FileSystem -Root $Root | Out-Null
  } catch {
    throw "Failed to map $Root. If Windows says multiple connections are not allowed, rerun with -ResetExistingConnections or run: net use \\$Server\$Share /delete /y"
  }
}

$Dest = "${DriveName}:\$Subdir\wsl-$Distro-$Stamp"
$Archive = Join-Path $Dest "$Distro.tar"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "This creates a restorable WSL export instead of copying a live ext4.vhdx."
Write-Host "All WSL sessions for this distro will be stopped."
wsl.exe --shutdown
wsl.exe --export $Distro $TempArchive
if ($LASTEXITCODE -ne 0) {
  throw "wsl.exe --export failed with exit code $LASTEXITCODE"
}
if (!(Test-Path $TempArchive)) {
  throw "WSL export did not create expected archive: $TempArchive"
}

Copy-Item $TempArchive $Archive
if (!(Test-Path $Archive)) {
  throw "SMB copy failed. Archive not found at: $Archive"
}

$SizeGiB = [math]::Round((Get-Item $Archive).Length / 1GB, 2)
Write-Host "WSL export written to: $Archive"
Write-Host "Archive size: $SizeGiB GiB"
Write-Host "Restore example:"
Write-Host "  wsl.exe --import ${Distro}-restored C:\WSL\${Distro}-restored $Archive"
Write-Host "Temporary local archive:"
Write-Host "  $TempArchive"
Write-Host "Remove it after confirming the SMB copy:"
Write-Host "  Remove-Item '$TempArchive'"
