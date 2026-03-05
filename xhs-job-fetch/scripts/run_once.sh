#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKFLOW_DIR="${WORKFLOW_DIR:-${SKILL_DIR}}"

load_env_file() {
  local file="$1"
  if [[ -f "${file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${file}"
    set +a
  fi
}

load_env_file "${WORKFLOW_DIR}/.env"
load_env_file "${SKILL_DIR}/.env"
load_env_file "${SKILL_DIR}/.env.local"

requirement_guard="${XHS_REQUIREMENT_GUARD:-1}"
effective_topic="${JOB_TOPIC:-${JOB_ROLE:-}}"
effective_time_constraint="${JOB_TIME_CONSTRAINT:-}"
effective_output_format="${JOB_OUTPUT_FORMAT:-}"

if [[ -n "${JOB_FETCH_CONFIG:-}" ]]; then
  resolved_config="${JOB_FETCH_CONFIG}"
  if [[ ! -f "${resolved_config}" && "${resolved_config}" != /* ]]; then
    if [[ -f "${SKILL_DIR}/${resolved_config}" ]]; then
      resolved_config="${SKILL_DIR}/${resolved_config}"
    elif [[ -f "${SKILL_DIR}/configs/${resolved_config}" ]]; then
      resolved_config="${SKILL_DIR}/configs/${resolved_config}"
    fi
  fi
  if [[ ! -f "${resolved_config}" ]]; then
    echo "❌ JOB_FETCH_CONFIG 文件不存在: ${JOB_FETCH_CONFIG}"
    exit 2
  fi
  export JOB_FETCH_CONFIG="${resolved_config}"
  _cfg_fields="$(
    python3 - "${resolved_config}" <<'PY'
import json
import sys

cfg_path = sys.argv[1]
try:
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

topic = str(cfg.get("topic") or cfg.get("role") or "").strip()
time_constraint = str(cfg.get("time_constraint") or "").strip()
output_format = str(cfg.get("output_format") or "").strip().lower()
print(topic)
print(time_constraint)
print(output_format)
PY
  )"

  cfg_topic="$(printf '%s\n' "${_cfg_fields}" | sed -n '1p')"
  cfg_time_constraint="$(printf '%s\n' "${_cfg_fields}" | sed -n '2p')"
  cfg_output_format="$(printf '%s\n' "${_cfg_fields}" | sed -n '3p')"

  if [[ -z "${effective_topic}" ]]; then
    effective_topic="${cfg_topic}"
  fi
  if [[ -z "${effective_time_constraint}" ]]; then
    effective_time_constraint="${cfg_time_constraint}"
  fi
  if [[ -z "${effective_output_format}" ]]; then
    effective_output_format="${cfg_output_format}"
  fi
fi

if [[ -n "${effective_output_format}" ]]; then
  case "${effective_output_format}" in
    json|markdown|both) ;;
    *)
      echo "❌ 返回格式无效: ${effective_output_format}"
      echo "   仅支持: json / markdown / both"
      exit 2
      ;;
  esac
fi

if [[ "${requirement_guard}" != "0" && "${requirement_guard}" != "false" && "${requirement_guard}" != "False" ]]; then
  missing_requirements=()
  if [[ -z "${effective_topic}" ]]; then
    missing_requirements+=("信息类型（JOB_TOPIC）")
  fi
  if [[ -z "${effective_time_constraint}" ]]; then
    missing_requirements+=("时间约束（JOB_TIME_CONSTRAINT）")
  fi
  if [[ -z "${effective_output_format}" ]]; then
    missing_requirements+=("返回格式（JOB_OUTPUT_FORMAT）")
  fi

  if [[ ${#missing_requirements[@]} -gt 0 ]]; then
    echo "❌ 需求未澄清，已阻止执行。"
    echo "   缺失项: ${missing_requirements[*]}"
    echo "   请先补充这三项再执行："
    echo "   1) 信息类型（例如：AI 工具 / 租房 / 探店）"
    echo "   2) 时间约束（近7天 / 近30天 / 不限）"
    echo "   3) 返回格式（json / markdown / both）"
    echo
    echo "   示例："
    echo "   bash ${SCRIPT_DIR}/xhs_skill.sh run --topic 'AI 工具' --time-constraint '近7天' --output-format both"
    echo "   或在 JOB_FETCH_CONFIG 对应 JSON 中补齐 topic/time_constraint/output_format。"
    echo "   如需跳过校验（不推荐），设置 XHS_REQUIREMENT_GUARD=0。"
    exit 4
  fi
fi

ensure_mcp_script="${SCRIPT_DIR}/ensure_mcp_binary.sh"
if [[ ! -f "${ensure_mcp_script}" ]]; then
  echo "❌ MCP installer not found: ${ensure_mcp_script}"
  exit 2
fi

if ! resolved_mcp_bin="$(bash "${ensure_mcp_script}")"; then
  echo "❌ MCP 二进制准备失败，请先在本机安装并配置 xiaohongshu-mcp。"
  echo "   可直接运行：bash ${SCRIPT_DIR}/xhs_skill.sh setup"
  exit 3
fi
export XHS_MCP_BINARY_PATH="${resolved_mcp_bin}"

missing_required=()
for v in FEISHU_WEBHOOK_URL; do
  if [[ -z "${!v:-}" ]]; then
    missing_required+=("${v}")
  fi
done
missing_qr_creds=()
for v in FEISHU_APP_ID FEISHU_APP_SECRET; do
  if [[ -z "${!v:-}" ]]; then
    missing_qr_creds+=("${v}")
  fi
done

job_cron_script="${SCRIPT_DIR}/job_cron_run.sh"
if [[ ! -f "${job_cron_script}" ]]; then
  echo "❌ Invalid WORKFLOW_DIR: ${WORKFLOW_DIR}"
  echo "   ${job_cron_script} not found"
  exit 2
fi

echo "========================================"
echo "xhs-info-fetch skill run"
echo "WORKFLOW_DIR=${WORKFLOW_DIR}"
echo "START_AT=$(date '+%Y-%m-%d %H:%M:%S')"
echo "XHS_MCP_BINARY_PATH=${XHS_MCP_BINARY_PATH}"
echo "JOB_FETCH_CONFIG=${JOB_FETCH_CONFIG:-}"
echo "JOB_TOPIC=${JOB_TOPIC:-}"
echo "JOB_REGION=${JOB_REGION:-}"
echo "JOB_TIME_CONSTRAINT=${JOB_TIME_CONSTRAINT:-}"
echo "JOB_OUTPUT_FORMAT=${JOB_OUTPUT_FORMAT:-}"
echo "EFFECTIVE_TOPIC=${effective_topic:-}"
echo "EFFECTIVE_TIME_CONSTRAINT=${effective_time_constraint:-}"
echo "EFFECTIVE_OUTPUT_FORMAT=${effective_output_format:-}"
echo "JOB_ROLE=${JOB_ROLE:-}"
echo "JOB_LOCATION=${JOB_LOCATION:-}"
echo "========================================"

if [[ ${#missing_required[@]} -gt 0 ]]; then
  echo "⚠️  缺少必需环境变量: ${missing_required[*]}"
  echo "   请在 ${SKILL_DIR}/.env.local 配置："
  echo "   FEISHU_WEBHOOK_URL=..."
  echo "   未配置 webhook 时，无法推送登录提示。"
  echo
fi

if [[ ${#missing_qr_creds[@]} -gt 0 ]]; then
  echo "⚠️  未配置二维码图片能力变量: ${missing_qr_creds[*]}"
  echo "   当前将降级为“仅文本提示 + 本机手动登录”模式。"
  echo "   如需飞书直接收到二维码图片，请补充："
  echo "   FEISHU_APP_ID=..."
  echo "   FEISHU_APP_SECRET=..."
  echo
fi

set +e
WORK_DIR="${WORKFLOW_DIR}" bash "${job_cron_script}"
status=$?
set -e

latest_job_log="$(ls -t "${WORKFLOW_DIR}"/logs/job_cron_*.log 2>/dev/null | head -n 1 || true)"
latest_result="$(ls -t "${WORKFLOW_DIR}"/results/result_*.json 2>/dev/null | head -n 1 || true)"
latest_report="$(
  { ls -t "${WORKFLOW_DIR}"/reports/info_report_*.json 2>/dev/null || true
    ls -t "${WORKFLOW_DIR}"/reports/job_report_*.json 2>/dev/null || true; } \
  | head -n 1
)"
latest_markdown="$(ls -t "${WORKFLOW_DIR}"/reports/info_report_*.md 2>/dev/null | head -n 1 || true)"

echo
echo "RESULT_SUMMARY"
echo "status=${status}"
echo "job_log=${latest_job_log}"
echo "result_json=${latest_result}"
echo "report_json=${latest_report}"
echo "report_markdown=${latest_markdown}"

if [[ -n "${latest_job_log}" ]]; then
  echo
  echo "LAST_LOG_TAIL"
  tail -n 80 "${latest_job_log}" || true
fi

if [[ ${status} -ne 0 ]]; then
  if [[ -n "${latest_job_log}" ]] && grep -q "未登录" "${latest_job_log}"; then
    echo
    echo "NEXT_ACTION=LOGIN_REQUIRED"
    echo "Run: bash ${SKILL_DIR}/scripts/xhs_skill.sh login"
  fi
  exit ${status}
fi

echo
echo "✅ Workflow completed successfully."
