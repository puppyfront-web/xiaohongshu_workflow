#!/usr/bin/env bash
#
# 小红书信息抓取单次任务脚本
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_DIR="${WORK_DIR:-$SKILL_DIR}"
cd "$WORK_DIR" || exit 1

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/anaconda3/bin:$PATH"

mkdir -p "$WORK_DIR/logs" "$WORK_DIR/reports" "$WORK_DIR/results"

LOG_FILE="$WORK_DIR/logs/job_cron_$(date +%Y%m%d_%H%M%S).log"
FEISHU_WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}"
if [ -n "$FEISHU_WEBHOOK_URL" ]; then
  export FEISHU_WEBHOOK_URL
else
  unset FEISHU_WEBHOOK_URL || true
fi

if [ -x "/opt/anaconda3/bin/python3" ]; then
  PYTHON_BIN="/opt/anaconda3/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ 未找到 python3" | tee -a "$LOG_FILE"
  exit 1
fi

JOB_FETCH_ARGS=()
if [ -n "${JOB_FETCH_CONFIG:-}" ]; then
  if [ ! -f "${JOB_FETCH_CONFIG}" ] && [ "${JOB_FETCH_CONFIG#/}" = "${JOB_FETCH_CONFIG}" ]; then
    if [ -f "${WORK_DIR}/${JOB_FETCH_CONFIG}" ]; then
      JOB_FETCH_CONFIG="${WORK_DIR}/${JOB_FETCH_CONFIG}"
    elif [ -f "${SKILL_DIR}/configs/${JOB_FETCH_CONFIG}" ]; then
      JOB_FETCH_CONFIG="${SKILL_DIR}/configs/${JOB_FETCH_CONFIG}"
    fi
  fi
  JOB_FETCH_ARGS+=(--config "$JOB_FETCH_CONFIG")
fi
if [ -n "${JOB_ROLE:-}" ]; then
  JOB_FETCH_ARGS+=(--role "$JOB_ROLE")
fi
if [ -n "${JOB_LOCATION:-}" ]; then
  JOB_FETCH_ARGS+=(--location "$JOB_LOCATION")
fi
if [ -n "${JOB_TOPIC:-}" ]; then
  JOB_FETCH_ARGS+=(--topic "$JOB_TOPIC")
fi
if [ -n "${JOB_REGION:-}" ]; then
  JOB_FETCH_ARGS+=(--region "$JOB_REGION")
fi
if [ -n "${JOB_TIME_CONSTRAINT:-}" ]; then
  JOB_FETCH_ARGS+=(--time-constraint "$JOB_TIME_CONSTRAINT")
fi
if [ -n "${JOB_OUTPUT_FORMAT:-}" ]; then
  JOB_FETCH_ARGS+=(--output-format "$JOB_OUTPUT_FORMAT")
fi
if [ "${JOB_NO_FEISHU:-0}" = "1" ]; then
  JOB_FETCH_ARGS+=(--no-feishu)
fi

echo "========================================" | tee -a "$LOG_FILE"
echo "信息抓取任务 开始: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
if [ ${#JOB_FETCH_ARGS[@]} -gt 0 ]; then
  echo "job_fetch args: ${JOB_FETCH_ARGS[*]}" | tee -a "$LOG_FILE"
fi

if "$PYTHON_BIN" -m core.job_fetch "${JOB_FETCH_ARGS[@]}" >> "$LOG_FILE" 2>&1; then
    echo "✅ 信息抓取任务完成" | tee -a "$LOG_FILE"
    exit 0
else
    echo "❌ 信息抓取任务失败" | tee -a "$LOG_FILE"
    exit 1
fi
