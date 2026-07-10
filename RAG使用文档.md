# RAG 知识库使用说明

最简单的使用方式：右键 [启动项目.ps1](./启动项目.ps1)，选择“使用 PowerShell 运行”，然后按菜单提示操作。

## 1. 启动环境

每次打开新的 PowerShell 窗口，先执行：

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\AI\mySkill'

.\.venv\Scripts\Activate.ps1

$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

激活成功后，命令行前面会出现 `(.venv)`。后续直接使用 `python`，不需要再输入 Python 的完整路径。

如果激活脚本被系统禁止，先执行：

```powershell
$ErrorActionPreference = 'Stop'

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

然后重新执行 `.\.venv\Scripts\Activate.ps1`。

## 2. 添加资料

支持 `.md`、`.txt` 和 `.pdf` 文件。

- Markdown、TXT 放到 `knowledge\web\`。
- PDF 放到 `knowledge\papers\`。

## 3. 建立索引

```powershell
$ErrorActionPreference = 'Stop'

python -m indexer.build_index
```

看到下面的提示表示完成：

```text
✓ 索引构建完成！
```

如果添加、修改或删除了资料：

1. 删除 `knowledge\vector_store` 文件夹。
2. 重新执行 `python -m indexer.build_index`。

不要在旧索引上连续重复构建，否则可能出现重复内容。

## 4. 检查索引

```powershell
$ErrorActionPreference = 'Stop'

if (Test-Path -LiteralPath '.\knowledge\vector_store\chroma.sqlite3') {
    Write-Output '索引已建立'
} else {
    Write-Output '索引未建立'
}
```

查看向量数量：

```powershell
$ErrorActionPreference = 'Stop'

python -c "import sqlite3; p='knowledge/vector_store/chroma.sqlite3'; c=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print('向量数量：', c.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]); c.close()"
```

## 5. 知识库问答

在启动菜单中：

- 输入 `4`：自由提问。
- 输入 `5`：切换 AI 后端。

支持的 AI 后端：

- `Ollama`：使用本地 `qwen3:0.6b`。
- `OpenAI API`：按提示输入 API Key 和模型名称，Key 只在当前窗口使用。
- `CCSwitch`：自动使用 CCSwitch 当前选中的 Codex Provider。

使用启动菜单时，切换后端后直接选择调研、报告或自由提问即可。

### 不使用启动菜单

先确认 Ollama 中有 `qwen3:0.6b`：

```powershell
$ErrorActionPreference = 'Stop'

ollama list
```

如果没有该模型：

```powershell
$ErrorActionPreference = 'Stop'

ollama pull 'qwen3:0.6b'
```

开始提问：

```powershell
$ErrorActionPreference = 'Stop'

python -m cli.main '有哪些一维井筒模拟项目？'
```

同时显示参考文件：

```powershell
$ErrorActionPreference = 'Stop'

python -m cli.main '有哪些一维井筒模拟项目？' --verbose
```

使用 OpenAI API：

```powershell
$ErrorActionPreference = 'Stop'

$env:OPENAI_API_KEY = '你的 API Key'
python -m cli.main '有哪些一维井筒模拟项目？' --provider openai
```

使用 CCSwitch 当前 Codex Provider：

```powershell
$ErrorActionPreference = 'Stop'

python -m cli.main '有哪些一维井筒模拟项目？' --provider ccswitch
```

如果提示无法连接 Ollama，另开一个 PowerShell 窗口执行：

```powershell
$ErrorActionPreference = 'Stop'

ollama serve
```

## 6. 日常使用顺序

1. 激活 `.venv`。
2. 把新资料放入 `knowledge`。
3. 删除旧的 `knowledge\vector_store`。
4. 重新建立索引。
5. 在菜单 5 中选择 AI 后端。
6. 使用菜单 3 生成报告，或菜单 4 自由提问。

开发和维护说明参见 [实施指南](./实施指南.md)。
