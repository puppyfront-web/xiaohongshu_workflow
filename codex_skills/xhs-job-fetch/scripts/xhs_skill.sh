#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKFLOW_DIR="${WORKFLOW_DIR:-$(cd "${SKILL_DIR}/../.." && pwd)}"

LOGIN_SCRIPT="${SCRIPT_DIR}/check_login.sh"
RUN_SCRIPT="${SCRIPT_DIR}/run_once.sh"
INSTALL_SCRIPT="${WORKFLOW_DIR}/scripts/install.sh"
ENSURE_MCP_SCRIPT="${SCRIPT_DIR}/ensure_mcp_binary.sh"
ENV_LOCAL_FILE="${SKILL_DIR}/.env.local"

TOPIC="${JOB_TOPIC:-${JOB_ROLE:-}}"
REGION="${JOB_REGION:-${JOB_LOCATION:-}}"
TIME_CONSTRAINT="${JOB_TIME_CONSTRAINT:-}"
OUTPUT_FORMAT="${JOB_OUTPUT_FORMAT:-}"
CONFIG_PATH="${JOB_FETCH_CONFIG:-}"
WITH_QR=0
SKIP_LOGIN=0
INSTALL_ARGS=()

usage() {
  cat <<'EOF'
用法:
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh <action> [options]

动作:
  setup     执行安装初始化（调用 scripts/install.sh）
  clarify   打印需求澄清模板（不执行抓取）
  login     执行登录检查（可选 --with-qr）
  run       执行一次抓取
  all       先登录检查，再执行抓取（推荐）
  help      显示帮助

选项:
  --topic <text>             信息主题（映射 JOB_TOPIC）
  --region <text>            地区（映射 JOB_REGION）
  --time-constraint <text>   时间约束（映射 JOB_TIME_CONSTRAINT）
  --output-format <value>    输出格式：json/markdown/both（映射 JOB_OUTPUT_FORMAT）
  --config <path>            配置文件（映射 JOB_FETCH_CONFIG）
  --with-qr                  login 阶段主动拉起二维码检查
  --skip-login               all 动作跳过 login 阶段
  --mcp-path <path>          setup 动作参数：指定本地 MCP 路径
  --mcp-url <url>            setup 动作参数：下载 MCP URL
  --mcp-sha256 <sha256>      setup 动作参数：下载 MCP 的 SHA256
  --mcp-repo <url>           setup 动作参数：MCP GitHub 仓库（默认 xpzouying/xiaohongshu-mcp）
  --feishu-webhook <url>     setup 动作参数：写入 FEISHU_WEBHOOK_URL
  --feishu-app-id <id>       setup 动作参数：写入 FEISHU_APP_ID
  --feishu-app-secret <sec>  setup 动作参数：写入 FEISHU_APP_SECRET
  --non-interactive          setup 动作参数：非交互安装

示例:
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup --mcp-path /abs/path/to/xiaohongshu-mcp
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh setup --mcp-url https://example.com/xiaohongshu-mcp --mcp-sha256 <sha256>
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh clarify
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh login --with-qr
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh run \
    --topic "AI 工具" --time-constraint "近7天" --output-format both --region "上海"
  bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh all \
    --topic "AI 工具" --time-constraint "近7天" --output-format both --region "上海" \
    --config configs/job_fetch.profile.example.json

说明:
  - login/run/all 会自动检测运行环境。
  - 首次使用或未配置 MCP 时，会自动触发 setup。
EOF
}

ensure_scripts() {
  if [[ ! -f "${LOGIN_SCRIPT}" ]]; then
    echo "❌ 缺少登录脚本: ${LOGIN_SCRIPT}"
    exit 2
  fi
  if [[ ! -f "${RUN_SCRIPT}" ]]; then
    echo "❌ 缺少执行脚本: ${RUN_SCRIPT}"
    exit 2
  fi
  if [[ ! -f "${INSTALL_SCRIPT}" ]]; then
    echo "❌ 缺少安装脚本: ${INSTALL_SCRIPT}"
    exit 2
  fi
  if [[ ! -f "${ENSURE_MCP_SCRIPT}" ]]; then
    echo "❌ 缺少 MCP 检测脚本: ${ENSURE_MCP_SCRIPT}"
    exit 2
  fi
}

parse_options() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --topic)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ --topic 缺少值"
          exit 2
        fi
        TOPIC="${2:-}"
        shift 2
        ;;
      --region)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ --region 缺少值"
          exit 2
        fi
        REGION="${2:-}"
        shift 2
        ;;
      --time-constraint)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ --time-constraint 缺少值"
          exit 2
        fi
        TIME_CONSTRAINT="${2:-}"
        shift 2
        ;;
      --output-format)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ --output-format 缺少值"
          exit 2
        fi
        OUTPUT_FORMAT="${2:-}"
        shift 2
        ;;
      --config)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ --config 缺少值"
          exit 2
        fi
        CONFIG_PATH="${2:-}"
        shift 2
        ;;
      --with-qr)
        WITH_QR=1
        shift
        ;;
      --skip-login)
        SKIP_LOGIN=1
        shift
        ;;
      --mcp-path|--mcp-url|--mcp-sha256|--mcp-repo|--feishu-webhook|--feishu-app-id|--feishu-app-secret)
        if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
          echo "❌ $1 缺少值"
          exit 2
        fi
        INSTALL_ARGS+=("$1" "$2")
        shift 2
        ;;
      --non-interactive)
        INSTALL_ARGS+=("$1")
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "❌ 未知参数: $1"
        usage
        exit 2
        ;;
    esac
  done
}

apply_runtime_env() {
  if [[ -n "${TOPIC}" ]]; then
    export JOB_TOPIC="${TOPIC}"
  fi
  if [[ -n "${REGION}" ]]; then
    export JOB_REGION="${REGION}"
  fi
  if [[ -n "${TIME_CONSTRAINT}" ]]; then
    export JOB_TIME_CONSTRAINT="${TIME_CONSTRAINT}"
  fi
  if [[ -n "${OUTPUT_FORMAT}" ]]; then
    export JOB_OUTPUT_FORMAT="${OUTPUT_FORMAT}"
  fi
  if [[ -n "${CONFIG_PATH}" ]]; then
    export JOB_FETCH_CONFIG="${CONFIG_PATH}"
  fi
}

do_clarify() {
  cat <<'EOF'
请先确认以下需求（前三项必填）：
1) 信息类型/主题（例如：AI 工具、租房、探店）
2) 时间约束（近7天 / 近30天 / 不限）
3) 返回格式（json / markdown / both）
4) 地区约束（可选）
5) 包含词/排除词（可选）

命令示例：
bash codex_skills/xhs-job-fetch/scripts/xhs_skill.sh all \
  --topic "AI 工具" --time-constraint "近7天" --output-format both --region "上海" \
  --config configs/job_fetch.profile.example.json
EOF
}

do_setup() {
  local args=("$@")
  if [[ ${#args[@]} -eq 0 ]]; then
    args=("${INSTALL_ARGS[@]}")
  fi
  bash "${INSTALL_SCRIPT}" "${args[@]}"
}

needs_bootstrap() {
  if [[ ! -f "${ENV_LOCAL_FILE}" ]]; then
    return 0
  fi
  if ! WORKFLOW_DIR="${WORKFLOW_DIR}" bash "${ENSURE_MCP_SCRIPT}" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

bootstrap_if_needed() {
  if needs_bootstrap; then
    local auto_setup_args=()
    if [[ "${INSTALL_ARGS+set}" == "set" && ${#INSTALL_ARGS[@]} -gt 0 ]]; then
      auto_setup_args=("${INSTALL_ARGS[@]}")
    fi
    if [[ ${#auto_setup_args[@]} -eq 0 ]]; then
      auto_setup_args=(--non-interactive)
    fi
    echo "⚙️  检测到尚未完成初始化，正在自动执行 setup..."
    do_setup "${auto_setup_args[@]}"
    echo "✅ setup 完成，继续执行 ${1}..."
  fi
}

do_login() {
  if [[ ${WITH_QR} -eq 1 ]]; then
    bash "${LOGIN_SCRIPT}" --with-qr
  else
    bash "${LOGIN_SCRIPT}"
  fi
}

do_run() {
  apply_runtime_env
  bash "${RUN_SCRIPT}"
}

main() {
  ensure_scripts

  local action="${1:-help}"
  shift || true
  parse_options "$@"

  echo "========================================"
  echo "xhs-info-fetch unified entry"
  echo "action=${action}"
  echo "WORKFLOW_DIR=${WORKFLOW_DIR}"
  echo "JOB_TOPIC=${TOPIC:-}"
  echo "JOB_REGION=${REGION:-}"
  echo "JOB_TIME_CONSTRAINT=${TIME_CONSTRAINT:-}"
  echo "JOB_OUTPUT_FORMAT=${OUTPUT_FORMAT:-}"
  echo "JOB_FETCH_CONFIG=${CONFIG_PATH:-}"
  echo "========================================"

  case "${action}" in
    setup)
      do_setup
      ;;
    clarify)
      do_clarify
      ;;
    login)
      bootstrap_if_needed "login"
      do_login
      ;;
    run)
      bootstrap_if_needed "run"
      do_run
      ;;
    all)
      bootstrap_if_needed "all"
      if [[ ${SKIP_LOGIN} -ne 1 ]]; then
        do_login
      fi
      do_run
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      echo "❌ 未知 action: ${action}"
      usage
      exit 2
      ;;
  esac
}

main "$@"
