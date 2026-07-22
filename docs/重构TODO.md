# ResearchTool 一次性重构 TODO

## 已确认边界

- [x] 使用 `src/research_tool/` 标准包结构和唯一入口 `research-tool`
- [x] 按 `cli`、`research`、`knowledge`、`rag`、`llm`、`shared` 业务能力组织
- [x] 不保留旧模块、旧函数、旧命令或启动脚本兼容层
- [x] `knowledge/` 仅存原始证据，`reports/` 存生成报告
- [x] `.research-tool/` 存索引、缓存和运行状态
- [x] 文档使用 UUID、内容哈希和相邻的 `*.meta.json`
- [x] 调研直接启动所选本机工具，单进程不限时并支持取消
- [x] 默认增量索引，保留显式全量重建
- [x] 支持 OpenAI Responses、Anthropic Messages、Ollama、OpenCode 四种协议
- [x] 所有非交互命令支持稳定的 `--json` 输出
- [x] OpenCode Skill 仅作为统一 CLI 的薄适配层
- [x] 清空旧 `knowledge/`，不迁移且不保留备份

## 实现任务

- [x] 创建重构前 Git 检查点
- [x] 建立 `pyproject.toml`、开发依赖和 `src/research_tool/` 包骨架
- [x] 实现共享路径、配置、异常、进度事件和领域模型
- [x] 实现 `KnowledgeRepository`、sidecar 元数据、UUID 和哈希去重
- [x] 删除内部 Grok、网页、Browser Relay、arXiv 与 Semantic Scholar 调研链
- [x] 实现外部工具直连、结果提取和原子化资料保存
- [x] 封装 LangChain 加载、分块、Embedding 和 Chroma
- [x] 实现基于文档哈希的增量索引、删除同步和全量重建
- [x] 实现四种 LLM Provider 协议的统一接口、配置和健康检查
- [x] 实现问答与报告服务，报告写入 `reports/`
- [x] 实现 `menu`、`research`、`index`、`ask`、`report`、`config`、`doctor`
- [x] 实现普通 Rich 输出、标准错误进度和标准输出 JSON 协议
- [x] 将 OpenCode Skill 改为调用 `research-tool research --json`
- [x] 删除旧 `cli/`、`indexer/`、`scripts/`、`启动项目.py`、`启动项目.ps1`
- [x] 清空旧 `knowledge/` 并创建新目录结构
- [x] 替换旧说明文档，编写 README、架构、CLI 和配置文档

## 测试与验收

- [x] 知识写入、sidecar、去重和文件删除测试
- [x] 外部工具命令、结果提取、落盘和取消测试
- [x] 增量索引新增、更新、删除和重建测试
- [x] 四种 Provider 协议配置与适配测试
- [x] 问答、报告、菜单命令和 `--json` 输出测试
- [x] OpenCode Skill 薄适配调用测试
- [x] `ruff check` 通过
- [x] `mypy src` 通过
- [x] `pytest` 通过
- [x] `research-tool doctor` 通过

## 外部调研工具与反馈优化

### 已确认边界

- [x] 使用 `.research-tool/config.json` 作为唯一配置来源，允许不兼容旧配置
- [x] 调研工具与 RAG Provider 档案分离，互不覆盖
- [x] 支持内部 JSON、Codex JSON 与 Claude Code JSON 配置样式
- [x] 菜单 5 直接选择 Codex、Claude Code、OpenCode 或 Grok
- [x] 四种工具直接使用各自本地认证、模型、插件、MCP 和搜索能力
- [x] 切换工具只保存选择，不发送请求或检测登录状态
- [x] API Key 写入已忽略的统一 JSON，界面、日志和普通 JSON 输出必须脱敏
- [x] 功能 1 一次启动一个外部工具进程，由工具完成搜索和报告生成
- [x] ResearchTool 不再代理 Grok API 或维护统一搜索 MCP
- [x] 工具请求不限时；重试由工具自身控制；`Ctrl+C` 可终止子进程
- [x] 调研从第 0 秒显示状态，每秒刷新阶段和累计耗时
- [x] 展示当前工具和累计耗时，不展示工具隐藏思维链
- [x] `--quiet` 关闭动态过程；`--json` 的结构化进度只写 stderr

### 实现任务

- [x] 定义版本化统一 JSON Schema 和原子配置存储
- [x] 实现内部、Codex、Claude Code JSON 导入与自动识别
- [x] 实现 OpenAI Responses、Anthropic Messages、Ollama、OpenCode 命名档案
- [x] 将菜单 5 改为四种本机调研工具选择器
- [x] 实现 PowerShell 包装、非交互参数和工具命令发现
- [x] 实现外部工具报告提取、知识落盘和原子报告保存
- [x] 将最终报告与原始证据分离，按网页、论文和源码归档报告引用来源
- [x] 删除 ResearchTool 内部 `grok-search` MCP 客户端与依赖
- [x] 实现动态阶段、累计耗时、取消和结构化 stderr 进度
- [x] 实时显示外部工具安全输出、搜索和工具调用状态，过滤隐藏推理块
- [x] 更新 CLI、配置、架构和 Skill 文档
- [x] 补齐配置、导入、Provider、工具命令、CLI 和进度测试
- [x] 通过 Ruff、mypy、pytest、doctor 与 CLI 冒烟验证
