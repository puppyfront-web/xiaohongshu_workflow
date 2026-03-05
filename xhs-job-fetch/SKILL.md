---
name: xhs-fetch-job
description: 根据用户给定条件执行小红书抓取；缺少必要条件时先补问再继续。
---

# XHS 通用信息抓取

## 执行规则（Codex / Claude Code）

- 用户调用 `xhs-fetch-job` 后，默认直接进入执行，不只停留在说明。
- 先从用户输入提取：`主题`、`时间约束`、`返回格式`。
- 缺少必要字段时，只补问必要问题；补齐后继续执行。
- 统一命令：
  - `bash scripts/xhs_skill.sh all ...`
- 不要求用户手动先跑 `setup`；`all` 在缺少本地配置时会自动触发初始化。
- 执行完成后返回：`job_log`、`result_json`、`report_json`、`report_markdown`（如有）。

## 适用场景

- 需要抓取小红书某一类信息（不限招聘）。
- 需要按主题/地区/关键词输出结构化结果。
- 需要按时间约束（近7天/近30天/不限）和格式（json/markdown/both）输出。

## 执行前先确认需求

执行脚本前，先确认下列信息；缺失时必须追问：

1. 信息类型 / 主题（必填）  
示例：AI 工具、租房、探店、旅游、穿搭、考研经验
2. 时间约束（必填）  
示例：近7天 / 近30天 / 不限
3. 返回格式（必填）  
可选：`json` / `markdown` / `both`
4. 地区约束（可选）  
示例：上海 / 北京 / 深圳 / 不限
5. 包含词与排除词（可选）  
示例：包含“实测/经验”，排除“广告/抽奖”

可用提问模板：
- 你希望抓取哪一类信息（主题）？
- 有没有时间范围要求（近7天、近30天或不限）？
- 结果希望什么格式（json、markdown、或者都要）？
- 是否限制地区？是否有必须包含/排除的关键词？

## 参数映射

把澄清结果映射到环境变量：

- `JOB_TOPIC`: 主题（推荐）
- `JOB_REGION`: 地区（可选）
- `JOB_TIME_CONSTRAINT`: 时间约束（推荐）
- `JOB_OUTPUT_FORMAT`: `json` / `markdown` / `both`
- `JOB_FETCH_CONFIG`: 配置文件路径（可选）
- `JOB_ROLE` / `JOB_LOCATION`: 旧参数兼容，不建议新任务使用

## 快速执行

1. 先用统一入口初始化：`scripts/xhs_skill.sh setup`。
2. 定位 `xhs-job-fetch` 目录。
3. 统一使用入口脚本：`scripts/xhs_skill.sh`。
4. 推荐执行：`scripts/xhs_skill.sh all`（登录检查 + 抓取）。

执行约束：
- 优先按文件名定位脚本，不假设固定 cwd。
- 若有多个同名脚本，使用当前工作区内 `xhs-job-fetch` 下的脚本。
- 对外只暴露一个入口：`xhs_skill.sh`；其他脚本作为内部实现。
- 入口默认开启 `XHS_REQUIREMENT_GUARD=1`，缺少主题/时间约束/返回格式会阻断执行。

入口动作：
- `setup`：初始化本地配置（调用 `scripts/install.sh`，不安装 MCP）
- `clarify`：仅打印需求澄清模板
- `login`：仅执行登录检查（可加 `--with-qr`）
- `run`：仅执行抓取
- `all`：先登录检查再抓取（推荐）
- `login` / `run` / `all` 会在执行前检查 MCP 可用性；未初始化时自动触发 `setup`
- MCP 需用户提前安装（安装说明：`https://github.com/xpzouying/xiaohongshu-mcp`）

入口示例：
```bash
bash scripts/xhs_skill.sh setup

bash scripts/xhs_skill.sh all \
  --topic "AI 工具" \
  --time-constraint "近7天" \
  --output-format both \
  --region "上海" \
  --config configs/job_fetch.profile.example.json
```

## 兼容性

- Codex：可直接执行 skill 脚本。
- Claude Code：支持 shell 即可走同一流程。
- IDE 工具（Cursor/Cline/Windsurf/Continue）：复用同一套脚本和环境变量。

MCP 说明：
- 项目会在本地拉起 `xiaohongshu-mcp`。
- 默认使用本地 `:18060` HTTP 服务。
- 运行环境需允许本地端口绑定和子进程拉起。

## 输出约定

每次执行后返回：

- 最新 `logs/job_cron_*.log`
- 最新 `results/result_*.json`
- 最新 `reports/info_report_*.json`（若生成）
- 最新 `reports/info_report_*.md`（当 `JOB_OUTPUT_FORMAT=markdown/both`）
- 成功/失败状态与下一步处理建议

## 失败处理

- 日志包含 `未登录`：
  - 配置了飞书应用凭据：生成二维码并推送飞书，扫码后继续。
  - 未配置飞书应用凭据：仅文本提醒，本机手动登录后继续。
- 登录失败：检查 webhook、应用权限和超时参数。
- 日志包含 `bind: operation not permitted`：切换到非受限环境重试。
