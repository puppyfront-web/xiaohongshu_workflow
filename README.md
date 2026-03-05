# xhs-info-fetch

这是一个可直接安装的小红书抓取 skill。
安装后主要入口：

```bash
SKILL_DIR=/path/to/xhs-job-fetch
bash "$SKILL_DIR/scripts/xhs_skill.sh" <action>
```

Codex 默认安装路径通常是：

```bash
SKILL_DIR="$HOME/.codex/skills/xhs-job-fetch"
bash "$SKILL_DIR/scripts/xhs_skill.sh" <action>
```

仓库内开发入口（本地调试）：

```bash
bash xhs-job-fetch/scripts/xhs_skill.sh <action>
```

## 前置条件

- Python 3
- 先自行安装 `xiaohongshu-mcp`（安装说明：`https://github.com/xpzouying/xiaohongshu-mcp`）
- 可选：`FEISHU_WEBHOOK_URL`
- 可选：`FEISHU_APP_ID` + `FEISHU_APP_SECRET`（用于推送二维码图片到飞书）

## 3 步上手

### 1)（可选）先做安装

```bash
SKILL_DIR=/path/to/xhs-job-fetch
bash "$SKILL_DIR/scripts/xhs_skill.sh" setup
```

### 2) 先确认需求（必做）

必填 3 项：
- 信息类型（主题）
- 时间约束（近7天 / 近30天 / 不限）
- 返回格式（json / markdown / both）

### 3) 直接执行

```bash
bash "$SKILL_DIR/scripts/xhs_skill.sh" all \
  --topic "AI 工具" \
  --time-constraint "近7天" \
  --output-format both \
  --region "上海" \
  --config configs/job_fetch.profile.example.json
```

说明：
- `all/login/run` 会检查运行环境；
- 首次使用若未完成配置，会自动生成 `.env.local`；
- `setup` 不会安装 MCP，只会写配置并提示缺失项。

## Codex / Claude Code 调用示例

```text
请使用 xhs-fetch-job：
抓取主题：AI 工具
时间约束：近7天
地区：上海
返回格式：both
```

## 常用动作

```bash
# 仅输出澄清模板
bash "$SKILL_DIR/scripts/xhs_skill.sh" clarify

# 初始化/重写本地配置（可附带 MCP 路径）
bash "$SKILL_DIR/scripts/xhs_skill.sh" setup --mcp-path /abs/path/to/xiaohongshu-mcp

# 仅登录检查（可拉起二维码）
bash "$SKILL_DIR/scripts/xhs_skill.sh" login --with-qr

# 仅执行抓取
bash "$SKILL_DIR/scripts/xhs_skill.sh" run \
  --topic "AI 工具" --time-constraint "近7天" --output-format both
```

## 输出文件（位于 skill 目录下）

- `logs/job_cron_*.log`
- `results/result_*.json`
- `reports/info_report_*.json`
- `reports/info_report_*.md`（当输出格式为 `markdown` 或 `both`）

## 目录（最小核心）

- `xhs-job-fetch/SKILL.md`
- `xhs-job-fetch/agents/openai.yaml`
- `xhs-job-fetch/scripts/`
- `xhs-job-fetch/core/`
- `xhs-job-fetch/configs/job_fetch.profile.example.json`
