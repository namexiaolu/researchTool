#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "没有找到虚拟环境 Python：$python"
}

if ($SelfTest) {
    & $python (Join-Path $projectRoot '启动项目.py') '--self-test'
} else {
    & $python (Join-Path $projectRoot '启动项目.py')
}
