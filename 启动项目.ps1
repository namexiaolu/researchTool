#requires -Version 7.0

param(
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$script:ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$script:KnowledgeRoot = Join-Path $script:ProjectRoot 'knowledge'
$script:VectorStore = Join-Path $script:KnowledgeRoot 'vector_store'
$script:ResearchScript = Join-Path $script:ProjectRoot '.opencode\skills\myresearch\scripts\run_research.py'
$script:OllamaModel = 'qwen3:0.6b'
$script:AppSettingsPath = Join-Path $script:ProjectRoot '.rag-settings.json'
$script:AiProvider = 'ollama'

if (Test-Path -LiteralPath $script:AppSettingsPath -PathType Leaf) {
    try {
        $savedSettings = Get-Content -LiteralPath $script:AppSettingsPath -Encoding UTF8 -Raw |
            ConvertFrom-Json
        if ($savedSettings.provider -in @('ollama', 'openai', 'ccswitch')) {
            $script:AiProvider = [string]$savedSettings.provider
        }
    }
    catch {
        $script:AiProvider = 'ollama'
    }
}
$env:RAG_LLM_PROVIDER = $script:AiProvider

Set-Location -LiteralPath $script:ProjectRoot
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

$activateScript = Join-Path $script:ProjectRoot '.venv\Scripts\Activate.ps1'
if (-not (Test-Path -LiteralPath $activateScript -PathType Leaf)) {
    throw "没有找到虚拟环境激活脚本：$activateScript"
}

. $activateScript

function Wait-ForUser {
    [CmdletBinding()]
    param()

    [void](Read-Host '按 Enter 返回主菜单')
}

function Read-RequiredText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Prompt
    )

    $value = (Read-Host $Prompt).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw '输入不能为空。'
    }
    return $value
}

function ConvertTo-SafeFileName {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    $safeName = $Text.Trim()
    foreach ($character in [System.IO.Path]::GetInvalidFileNameChars()) {
        $safeName = $safeName.Replace([string]$character, '_')
    }

    $safeName = $safeName.Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($safeName)) {
        $safeName = '未命名'
    }
    if ($safeName.Length -gt 40) {
        $safeName = $safeName.Substring(0, 40)
    }
    return $safeName
}

function Test-RagIndex {
    [CmdletBinding()]
    param()

    return Test-Path -LiteralPath (Join-Path $script:VectorStore 'chroma.sqlite3') -PathType Leaf
}

function Test-OllamaModel {
    [CmdletBinding()]
    param()

    if (-not (Get-Command -Name 'ollama' -ErrorAction SilentlyContinue)) {
        return $false
    }

    try {
        $models = (& ollama list | Out-String)
        return $models.Contains($script:OllamaModel, [System.StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Test-OpenAiConfig {
    [CmdletBinding()]
    param()

    return -not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)
}

function Test-CCSwitchConfig {
    [CmdletBinding()]
    param()

    $configPath = if ([string]::IsNullOrWhiteSpace($env:CCSWITCH_CODEX_CONFIG)) {
        Join-Path $env:USERPROFILE '.codex\config.toml'
    }
    else {
        $env:CCSWITCH_CODEX_CONFIG
    }
    $authPath = if ([string]::IsNullOrWhiteSpace($env:CCSWITCH_CODEX_AUTH)) {
        Join-Path $env:USERPROFILE '.codex\auth.json'
    }
    else {
        $env:CCSWITCH_CODEX_AUTH
    }

    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $authPath -PathType Leaf)) {
        return $false
    }

    try {
        $auth = Get-Content -LiteralPath $authPath -Encoding UTF8 -Raw | ConvertFrom-Json
        return -not [string]::IsNullOrWhiteSpace([string]$auth.OPENAI_API_KEY)
    }
    catch {
        return $false
    }
}

function Test-AiProvider {
    [CmdletBinding()]
    param()

    switch ($script:AiProvider) {
        'ollama' { return Test-OllamaModel }
        'openai' { return Test-OpenAiConfig }
        'ccswitch' { return Test-CCSwitchConfig }
        default { return $false }
    }
}

function Get-AiProviderDisplayName {
    [CmdletBinding()]
    param()

    switch ($script:AiProvider) {
        'ollama' { return 'Ollama' }
        'openai' { return 'OpenAI API' }
        'ccswitch' { return 'CCSwitch 当前 Codex Provider' }
        default { return $script:AiProvider }
    }
}

function Save-AiProvider {
    [CmdletBinding()]
    param()

    $settings = [ordered]@{ provider = $script:AiProvider } | ConvertTo-Json
    Set-Content -LiteralPath $script:AppSettingsPath -Value $settings -Encoding UTF8
}

function Select-AiProvider {
    [CmdletBinding()]
    param()

    Write-Host ''
    Write-Host '1. Ollama（本地）'
    Write-Host '2. OpenAI API'
    Write-Host '3. CCSwitch 当前 Codex Provider'
    Write-Host ''
    $choice = (Read-Host '请选择 AI 后端').Trim()

    $selected = switch ($choice) {
        '1' { 'ollama' }
        '2' { 'openai' }
        '3' { 'ccswitch' }
        default { throw '请输入 1、2 或 3。' }
    }

    if ($selected -eq 'openai') {
        if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
            $secureKey = Read-Host '请输入 OpenAI API Key（仅当前会话使用）' -AsSecureString
            $plainKey = [System.Net.NetworkCredential]::new('', $secureKey).Password
            if ([string]::IsNullOrWhiteSpace($plainKey)) {
                throw 'OpenAI API Key 不能为空。'
            }
            $env:OPENAI_API_KEY = $plainKey
        }

        $model = (Read-Host '模型名称（直接回车使用 gpt-5.6）').Trim()
        $env:OPENAI_MODEL = if ([string]::IsNullOrWhiteSpace($model)) { 'gpt-5.6' } else { $model }

        $baseUrl = (Read-Host 'Base URL（官方 OpenAI 直接回车）').Trim()
        if ([string]::IsNullOrWhiteSpace($baseUrl)) {
            Remove-Item Env:OPENAI_BASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:OPENAI_BASE_URL = $baseUrl
        }
        $env:OPENAI_REASONING_EFFORT = 'low'
    }

    $previous = $script:AiProvider
    $script:AiProvider = $selected
    $env:RAG_LLM_PROVIDER = $selected
    try {
        $summary = (& python -c "from cli.llm_provider import describe_config, load_llm_config; print(describe_config(load_llm_config()))" | Out-String).Trim()
    }
    catch {
        $script:AiProvider = $previous
        $env:RAG_LLM_PROVIDER = $previous
        throw
    }

    Save-AiProvider
    Write-Host ''
    Write-Host "AI 后端已切换：$summary" -ForegroundColor Green
}

function Invoke-AiGeneration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Prompt
    )

    if (-not (Test-AiProvider)) {
        throw "当前 AI 后端不可用：$(Get-AiProviderDisplayName)。请执行菜单 5 重新配置。"
    }
    return (& python -m cli.generate $Prompt --provider $script:AiProvider | Out-String).Trim()
}

function Remove-ExistingVectorStore {
    [CmdletBinding()]
    param()

    $target = [System.IO.Path]::GetFullPath($script:VectorStore)
    $expected = [System.IO.Path]::GetFullPath(
        (Join-Path $script:ProjectRoot 'knowledge\vector_store')
    )

    if ($target -ne $expected) {
        throw "索引路径校验失败：$target"
    }
    if (-not $target.StartsWith(
        $script:ProjectRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "拒绝删除项目目录外的路径：$target"
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

function Invoke-KeywordResearch {
    [CmdletBinding()]
    param()

    $keyword = Read-RequiredText -Prompt '请输入调研关键词'
    if (-not (Test-Path -LiteralPath $script:ResearchScript -PathType Leaf)) {
        throw "没有找到调研计划脚本：$script:ResearchScript"
    }

    Write-Host ''
    Write-Host '正在生成调研计划...' -ForegroundColor Cyan
    $planOutput = & python $script:ResearchScript `
        --topic $keyword `
        --depth 2 `
        --lang zh `
        --output plan
    $planJson = ($planOutput | Out-String).Trim()
    $null = $planJson | ConvertFrom-Json

    $researchText = ''
    $researchNote = '本次只生成了调研计划；配置可用的 AI 后端后可生成初步调研内容。'

    if (Test-AiProvider) {
        Write-Host "正在使用 $(Get-AiProviderDisplayName) 生成初步调研内容..." -ForegroundColor Cyan
        $prompt = @"
请围绕“$keyword”生成一份简洁的中文初步调研。

调研计划如下：
$planJson

要求：
1. 使用 Markdown。
2. 包含概述、主要方案或项目、对比、建议。
3. 不确定的信息明确标注，不要编造来源链接。
4. 不要声称已经进行了实时联网搜索。
"@
        try {
            $researchText = Invoke-AiGeneration -Prompt $prompt
            $researchNote = "内容由 $(Get-AiProviderDisplayName) 生成，不包含实时联网搜索。"
        }
        catch {
            $researchText = "生成初步调研内容失败：$($_.Exception.Message)"
            $researchNote = 'AI 后端调用失败，已保留调研计划。'
        }
    }

    if ([string]::IsNullOrWhiteSpace($researchText)) {
        $researchText = '请根据下面的调研计划继续收集和补充资料。'
    }

    $outputDirectory = Join-Path $script:KnowledgeRoot 'web'
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $safeKeyword = ConvertTo-SafeFileName -Text $keyword
    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $outputPath = Join-Path $outputDirectory "调研_${safeKeyword}_${timestamp}.md"
    $generatedAt = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    $document = @"
# $keyword 调研

- 生成时间：$generatedAt
- 说明：$researchNote

## 初步结果

$researchText

## 调研计划

~~~json
$planJson
~~~
"@

    Set-Content -LiteralPath $outputPath -Value $document -Encoding UTF8
    Write-Host ''
    Write-Host "调研内容已保存：$outputPath" -ForegroundColor Green
    Write-Host '需要让 RAG 使用新内容时，请再执行菜单 2。' -ForegroundColor Yellow
}

function Invoke-RagBuild {
    [CmdletBinding()]
    param()

    Write-Host ''
    Write-Host '正在清理旧索引并重新构建...' -ForegroundColor Cyan
    Remove-ExistingVectorStore
    & python -m indexer.build_index
    Write-Host ''
    Write-Host 'RAG 索引处理完成。' -ForegroundColor Green
}

function Invoke-ResearchReport {
    [CmdletBinding()]
    param()

    if (-not (Test-RagIndex)) {
        throw 'RAG 索引尚未建立，请先执行菜单 2。'
    }
    if (-not (Test-AiProvider)) {
        throw "当前 AI 后端不可用：$(Get-AiProviderDisplayName)。请执行菜单 5 重新配置。"
    }

    $request = Read-RequiredText -Prompt '请输入报告要求'
    $reportPrompt = @"
请仅根据知识库内容，按照下面的要求生成一份中文调研报告：

$request

报告使用 Markdown，至少包含标题、摘要、主要发现、对比或分析、结论。知识库没有的信息请明确说明不知道，不要编造。
"@

    Write-Host ''
    Write-Host '正在生成调研报告...' -ForegroundColor Cyan
    $reportOutput = (& python -m cli.main $reportPrompt --verbose --provider $script:AiProvider | Out-String).Trim()

    $outputDirectory = Join-Path $script:KnowledgeRoot 'reports'
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $safeName = ConvertTo-SafeFileName -Text $request
    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $outputPath = Join-Path $outputDirectory "报告_${safeName}_${timestamp}.md"
    $generatedAt = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    $document = @"
# 调研报告

- 生成时间：$generatedAt
- 用户要求：$request

$reportOutput
"@

    Set-Content -LiteralPath $outputPath -Value $document -Encoding UTF8
    Write-Host ''
    Write-Host $reportOutput
    Write-Host ''
    Write-Host "报告已保存：$outputPath" -ForegroundColor Green
}

function Invoke-FreeQuestion {
    [CmdletBinding()]
    param()

    if (-not (Test-RagIndex)) {
        throw 'RAG 索引尚未建立，请先执行菜单 2。'
    }
    if (-not (Test-AiProvider)) {
        throw "当前 AI 后端不可用：$(Get-AiProviderDisplayName)。请执行菜单 5 重新配置。"
    }

    $question = Read-RequiredText -Prompt '请输入问题'
    Write-Host ''
    & python -m cli.main $question --verbose --provider $script:AiProvider
}

function Invoke-SelfTest {
    [CmdletBinding()]
    param()

    $pythonVersion = (& python --version | Out-String).Trim()
    [pscustomobject]@{
        ProjectRoot = $script:ProjectRoot
        Python = $pythonVersion
        ResearchScript = Test-Path -LiteralPath $script:ResearchScript -PathType Leaf
        RagIndex = Test-RagIndex
        OllamaModel = Test-OllamaModel
        AiProvider = $script:AiProvider
        AiProviderReady = Test-AiProvider
        CCSwitchConfig = Test-CCSwitchConfig
    } | Format-List
}

function Start-ProjectMenu {
    [CmdletBinding()]
    param()

    while ($true) {
        try {
            Clear-Host
        }
        catch {
            # 输出被重定向时可能没有可用控制台，跳过清屏即可。
        }
        $indexStatus = if (Test-RagIndex) { '已建立' } else { '未建立' }
        $providerStatus = if (Test-AiProvider) { '可用' } else { '不可用' }

        Write-Host '========================================' -ForegroundColor DarkCyan
        Write-Host '        个人知识库助手' -ForegroundColor Cyan
        Write-Host '========================================' -ForegroundColor DarkCyan
        Write-Host "RAG 索引：$indexStatus"
        Write-Host "AI 后端：$(Get-AiProviderDisplayName)（$providerStatus）"
        Write-Host ''
        Write-Host '1. 按关键词进行调研并保存到 knowledge'
        Write-Host '2. 执行 RAG 索引'
        Write-Host '3. 根据提示词生成调研报告'
        Write-Host '4. 自由提问'
        Write-Host '5. 切换 AI 后端（Ollama / OpenAI / CCSwitch）'
        Write-Host '0. 退出'
        Write-Host ''

        $choice = (Read-Host '请选择').Trim()
        if ($choice -eq '0') {
            return
        }

        try {
            switch ($choice) {
                '1' { Invoke-KeywordResearch }
                '2' { Invoke-RagBuild }
                '3' { Invoke-ResearchReport }
                '4' { Invoke-FreeQuestion }
                '5' { Select-AiProvider }
                default { Write-Host '请输入 0 到 5。' -ForegroundColor Yellow }
            }
        }
        catch {
            Write-Host ''
            Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
        }

        Write-Host ''
        Wait-ForUser
    }
}

try {
    if ($SelfTest) {
        Invoke-SelfTest
    }
    else {
        Start-ProjectMenu
    }
}
catch {
    Write-Host ''
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    if (-not $SelfTest) {
        [void](Read-Host '按 Enter 关闭')
    }
    exit 1
}
