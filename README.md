# 研究生科研文献分析智能体 - 多智能体系统

基于 opencode 多智能体架构的科研文献分析工具。使用编排器 + 3 个专用 subagent，实现 PDF 文本提取、多篇文献结构化分析、综述生成和研究突破点识别。

## 项目结构

```
.
├── papers/                     # 存放待分析的PDF文献
├── analysis/                   # 单篇分析结果 (_raw.txt + _analysis.md)
├── review/                     # 综述报告 (synthesis_report.md)
├── output/                     # 研究突破点报告 (research_opportunities.md)
├── agents/                     # subagent 提示词模板
│   ├── analyze.md
│   ├── synthesize.md
│   └── discover.md
├── scripts/
│   ├── orchestrator.py         # 主调度器（状态机 + 任务分发）
│   ├── batch_extract.py        # PDF文本提取脚本
│   └── check_status.py         # 简单状态查看（被orchestrator替代）
├── .orchestrator_state.json    # 状态缓存（自动维护，勿手动编辑）
├── opencode.json               # subagent 配置定义
├── AGENTS.md                   # 编排器行为指令
└── requirements.txt
```

## 快速开始

### 1. 环境配置

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 放入论文

将 PDF 放入 `papers/` 目录。
启动：当前项目目录下打开opencode,例如输入：“开始分析，我的研究方向是XXX""

### 3. 运行编排器

```bash
# 查看当前进度
python scripts/orchestrator.py --status

# 自动推进到下一阶段（带确认）
python scripts/orchestrator.py --run
```

中文乱码时先执行：`chcp 65001`

## 工作流程（四阶段）

| 阶段 | 名称 | 执行方式 |
|------|------|---------|
| 1 | PDF文本提取 | `python scripts/orchestrator.py --stage1` |
| 2 | 单篇文献分析 | `python scripts/orchestrator.py --stage2`（每批3篇） |
| 3 | 综述生成 | `python scripts/orchestrator.py --stage3` |
| 4 | 研究突破点发现 | `python scripts/orchestrator.py --stage4` |

## 多智能体架构

| Agent | 职责 | 调度方式 |
|-------|------|---------|
| `@orchestrator` | 状态管理 + 任务分发 | 默认入口 |
| `@analyze` | 单篇文献结构化分析 | `orchestrator.py --stage2` 调度 |
| `@synthesize` | 生成文献综述报告 | `orchestrator.py --stage3` 调度 |
| `@discover` | 挖掘研究突破点 | `orchestrator.py --stage4` 调度 |

每个 subagent 在独立上下文窗口中运行，处理后即销毁，编排器只保留轻量级状态。

## 缓存失效机制

- 系统对每篇 PDF 计算 **SHA256 哈希**并存入 `.orchestrator_state.json`
- **新增** PDF → 自动加入队列，仅处理该篇
- **修改** PDF（内容变化）→ 该篇的 raw/analysis 自动删除，综述/突破点标记为过期
- **删除** PDF → 该篇的 `_raw.txt` / `_analysis.md` 自动清理
- 论文集发生任何变化 → 综述和突破点报告强制重新生成

```bash
# 全量重置（删除所有产物 + 状态文件，带确认）
python scripts/orchestrator.py --clean
```

**二次运行安全**：重复 `--run` 即可，哈希会自动识别已处理和已变更的论文，不会重复劳动。

## 依赖

- pdfplumber — PDF文本提取
- PyMuPDF (fitz) — PDF文本提取备用方案
