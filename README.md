# xhs-info-fetch

一个可直接安装使用的小红书信息抓取 skill。

## 先看这里（必须）

本 skill **不会自动安装** `xiaohongshu-mcp`。使用前请先自行安装：

- 项目地址：`https://github.com/xpzouying/xiaohongshu-mcp`
- 安装完成后至少满足其一：
  - `xiaohongshu-mcp` 已在 `PATH` 中（可直接执行）
  - 或配置环境变量：`XHS_MCP_BINARY_PATH=/abs/path/to/xiaohongshu-mcp`

建议先自检：

```bash
xiaohongshu-mcp --help
# 或
ls -l /abs/path/to/xiaohongshu-mcp
```

## 前置条件

- Python 3
- 已安装 `xiaohongshu-mcp`（见上）
- 可选：`FEISHU_WEBHOOK_URL`
- 可选：`FEISHU_APP_ID` + `FEISHU_APP_SECRET`（用于推送二维码图片到飞书）

## 入口

安装后推荐这样调用：

```bash
SKILL_DIR=/path/to/xhs-job-fetch
bash "$SKILL_DIR/scripts/xhs_skill.sh" <action>
```

Codex 默认路径通常是：

```bash
SKILL_DIR="$HOME/.codex/skills/xhs-job-fetch"
bash "$SKILL_DIR/scripts/xhs_skill.sh" <action>
```

仓库本地调试：

```bash
bash xhs-job-fetch/scripts/xhs_skill.sh <action>
```

## 快速开始

### 1) 初始化本地配置

```bash
SKILL_DIR=/path/to/xhs-job-fetch
bash "$SKILL_DIR/scripts/xhs_skill.sh" setup
```

### 2) 确认需求（必填 3 项）

- 信息类型（主题）
- 时间约束（近7天 / 近30天 / 不限）
- 返回格式（json / markdown / both）

### 3) 执行

```bash
bash "$SKILL_DIR/scripts/xhs_skill.sh" all \
  --topic "AI 工具" \
  --time-constraint "近7天" \
  --output-format both \
  --region "上海" \
  --config configs/job_fetch.profile.example.json
```

## 常用命令

```bash
# 输出澄清模板
bash "$SKILL_DIR/scripts/xhs_skill.sh" clarify

# 初始化/重写配置（显式指定 MCP 路径）
bash "$SKILL_DIR/scripts/xhs_skill.sh" setup --mcp-path /abs/path/to/xiaohongshu-mcp

# 仅登录检查（可拉起二维码）
bash "$SKILL_DIR/scripts/xhs_skill.sh" login --with-qr

# 仅执行抓取
bash "$SKILL_DIR/scripts/xhs_skill.sh" run \
  --topic "AI 工具" --time-constraint "近7天" --output-format both
```

## 常见问题

- 提示 `未找到 xiaohongshu-mcp 可执行文件`：
  - 先安装 `xiaohongshu-mcp`：`https://github.com/xpzouying/xiaohongshu-mcp`
  - 再设置 `XHS_MCP_BINARY_PATH` 或加入 `PATH`
- 提示 `bind: operation not permitted`：
  - 当前运行环境限制本地端口，换到非受限环境重试

## 输出文件（skill 目录下）

- `logs/job_cron_*.log`
- `results/result_*.json`
- `reports/info_report_*.json`
- `reports/info_report_*.md`（当输出格式为 `markdown` 或 `both`）
