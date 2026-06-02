param(
  [string]$Distro = "Ubuntu",
  [string]$ProjectPath = "/home/mpwsl2/a-eye/idea_2/scamguardian-v2",
  [Parameter(Mandatory = $true)][string]$Server,
  [Parameter(Mandatory = $true)][string]$Share,
  [string]$Subdir = "A-EYE\ScamGuardianBackups",
  [string]$User = "",
  [switch]$ResetExistingConnections
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$TarName = "scamguardian-critical-data-with-env-$Stamp.tgz"
$WslTarPath = "/tmp/$TarName"
$WslUncTarPath = "\\wsl$\$Distro\tmp\$TarName"
$DriveName = "BEE"
$Root = "\\$Server\$Share"

Write-Host "Creating project data archive inside WSL..."
$TarCommand = @"
cd '$ProjectPath' && tar -czf '$WslTarPath' \
  .env \
  .scamguardian/scamguardian.sqlite3 \
  .scamguardian/scamguardian.db \
  .scamguardian/active_models.json \
  data/generated \
  data/processed \
  data/run_drafts.jsonl \
  data/run_drafts.reviewed.jsonl \
  tasks/todo.md \
  tasks/lessons.md \
  codex.md
"@
wsl.exe -d $Distro -- bash -lc $TarCommand

if (!(Test-Path $WslUncTarPath)) {
  throw "Archive was created in WSL but is not visible through $WslUncTarPath"
}

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

$Dest = "${DriveName}:\$Subdir\project-data-$Stamp"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item $WslUncTarPath (Join-Path $Dest $TarName)

Write-Host "Project backup written to: $Dest\$TarName"
Write-Host "Remove temporary WSL archive:"
Write-Host "  wsl.exe -d $Distro -- rm '$WslTarPath'"
