# xhs-info-fetch

一个可分享的小红书抓取 skill。对外只保留一个入口脚本：

```bash
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh <action>
```

skill 名称：`xhs-fetch-job`（安装后可在 Codex / Claude Code 里直接调用）。

## 前置条件

- Python 3
- 本机可访问 GitHub（默认会从 `https://github.com/xpzouying/xiaohongshu-mcp` 安装 MCP）
- 可选：`FEISHU_WEBHOOK_URL`
- 可选：`FEISHU_APP_ID` + `FEISHU_APP_SECRET`（用于推送二维码图片到飞书）

## 3 步上手

### 1)（可选）先做安装

```bash
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup
```

### 2) 先确认需求（必做）

必填 3 项：
- 信息类型（主题）
- 时间约束（近7天 / 近30天 / 不限）
- 返回格式（json / markdown / both）

### 3) 直接执行

```bash
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh all \
  --topic "AI 工具" \
  --time-constraint "近7天" \
  --output-format both \
  --region "上海" \
  --config configs/job_fetch.profile.example.json
```

说明：
- `all/login/run` 会检查运行环境；
- 首次使用若未完成配置，会自动进入 `setup`。

## Codex / Claude Code 调用示例

### Codex（对话中直接说）

```text
请使用 xhs-fetch-job：
抓取主题：AI 工具
时间约束：近7天
地区：上海
返回格式：both
```

### Claude Code（对话中直接说）

```text
使用 xhs-fetch-job 执行任务：
1) 先确认我缺的参数（主题/时间约束/返回格式）
2) 再执行抓取
3) 返回 status、job_log、result_json、report_json、report_markdown
```

## 常用动作

```bash
# 仅输出澄清模板
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh clarify

# 安装/重装配置（可附带 MCP 参数）
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup --mcp-path /abs/path/to/xiaohongshu-mcp

# 指定 MCP GitHub 仓库安装
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup --mcp-repo https://github.com/xpzouying/xiaohongshu-mcp

# 仅登录检查（可拉起二维码）
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh login --with-qr

# 仅执行抓取
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh run \
  --topic "AI 工具" --time-constraint "近7天" --output-format both
```

## 输出文件

- `logs/job_cron_*.log`
- `results/result_*.json`
- `reports/info_report_*.json`
- `reports/info_report_*.md`（当输出格式为 `markdown` 或 `both`）

## 目录（最小核心）

- `codex_skills/xhs-job-fetch/`：skill 与脚本
- `core/`：抓取核心代码
- `scripts/install.sh`：安装脚本
- `job_cron_run.sh`：任务入口
- `configs/job_fetch.profile.example.json`：配置示例
