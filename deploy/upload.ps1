param(
    [Parameter(Mandatory=$true)][string]$Server,
    [Parameter(Mandatory=$true)][string]$User,
    [Parameter(Mandatory=$true)][string]$Key
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$archive = Join-Path $workspace '.local/deploy.tar.gz'
$entries = @('scripts', 'public', 'deploy', 'tests', 'translations', 'LICENSES', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'package.json', 'package-lock.json', 'requirements.txt', 'glossary.json', 'README.md', '.gitignore')
& tar -czf $archive --exclude='public/data' --exclude='public/assets' --exclude='__pycache__' @entries
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$sshOptions = @('-i', $Key, '-o', 'BatchMode=yes', '-o', 'UserKnownHostsFile=.local/known_hosts')
& scp @sshOptions $archive "${User}@${Server}:/tmp/vulkan-deploy.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
& ssh @sshOptions "${User}@${Server}" 'sudo -n mkdir -p /opt/vulkan-tutorial && sudo -n tar -xzf /tmp/vulkan-deploy.tar.gz -C /opt/vulkan-tutorial && sudo -n bash /opt/vulkan-tutorial/deploy/install.sh'
if ($LASTEXITCODE -ne 0) { throw 'Server installation failed.' }
