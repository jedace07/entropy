param([Parameter(Mandatory)][string]$Destination)

# This official build embeds Qt 6.9.3 in the maintenance executable (QTIFW-3330)
$ErrorActionPreference = 'Stop'
$repo = 'https://download.qt.io/online/qtsdkrepository/windows_x86/ifw/tools_ifw_411/qt.tools.ifw.411'
$archive = [IO.Path]::GetTempFileName()
try {
    curl.exe --fail --location --silent --show-error --retry 3 --output $archive "$repo/4.11.0-0-202603231357ifw-win-x64.7z"
    if ($LASTEXITCODE -ne 0) { throw 'Could not download Qt Installer Framework' }
    if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne 'c47201c4f6a82a8b607daa245237f40831d78425e904edd1514b71fd17efefc1') {
        throw 'Qt Installer Framework archive checksum mismatch'
    }
    New-Item -ItemType Directory -Force $Destination | Out-Null
    tar.exe -xf $archive -C $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract Qt Installer Framework' }
    (Get-Item "$Destination/bin/binarycreator.exe").FullName
} finally {
    Remove-Item -LiteralPath $archive
}
