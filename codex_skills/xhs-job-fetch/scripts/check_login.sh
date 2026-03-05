#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKFLOW_DIR="${WORKFLOW_DIR:-$(cd "${SKILL_DIR}/../.." && pwd)}"

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

ensure_mcp_script="${SCRIPT_DIR}/ensure_mcp_binary.sh"
if [[ ! -f "${ensure_mcp_script}" ]]; then
  echo "❌ MCP installer not found: ${ensure_mcp_script}"
  exit 2
fi

if ! resolved_mcp_bin="$(WORKFLOW_DIR="${WORKFLOW_DIR}" bash "${ensure_mcp_script}")"; then
  echo "❌ MCP 二进制准备失败，请先在本机安装并配置 xiaohongshu-mcp。"
  echo "   可直接运行：bash ${SCRIPT_DIR}/xhs_skill.sh setup"
  exit 3
fi
export XHS_MCP_BINARY_PATH="${resolved_mcp_bin}"

WITH_QR=0
if [[ "${1:-}" == "--with-qr" ]]; then
  WITH_QR=1
fi

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

if [[ ! -f "${WORKFLOW_DIR}/core/crawler_executor.py" ]]; then
  echo "❌ Invalid WORKFLOW_DIR: ${WORKFLOW_DIR}"
  echo "   core/crawler_executor.py not found"
  exit 2
fi

echo "MCP_BINARY=${XHS_MCP_BINARY_PATH}"

if [[ ${#missing_required[@]} -gt 0 ]]; then
  echo "⚠️  缺少必需环境变量: ${missing_required[*]}"
  echo "   请在 ${SKILL_DIR}/.env.local 配置 FEISHU_WEBHOOK_URL"
  echo "   未配置 webhook 时，无法推送登录提示。"
  echo
fi

if [[ ${#missing_qr_creds[@]} -gt 0 ]]; then
  echo "⚠️  未配置二维码图片能力变量: ${missing_qr_creds[*]}"
  echo "   当前将降级为“仅文本提示 + 本机手动登录”模式。"
  echo "   如需飞书直接收到二维码图片，请补充 FEISHU_APP_ID / FEISHU_APP_SECRET"
  echo
fi

WORKFLOW_DIR="${WORKFLOW_DIR}" XHS_CHECK_LOGIN_WITH_QR="${WITH_QR}" PYTHONUNBUFFERED=1 python3 - <<'PY'
import os
import sys
import time
import base64
import subprocess
from datetime import datetime
from pathlib import Path

workflow_dir = Path(os.environ["WORKFLOW_DIR"]).resolve()
sys.path.insert(0, str(workflow_dir))

from core.crawler_executor import CrawlerExecutor  # noqa: E402

executor = CrawlerExecutor(auto_start_server=True)
ok, msg = executor._start_server_if_needed()
if not ok:
    print(f"❌ MCP 启动失败: {msg}")
    sys.exit(2)

with_qr = os.getenv("XHS_CHECK_LOGIN_WITH_QR", "0").strip().lower() in ("1", "true", "yes", "on")

if not with_qr:
    try:
        logged_in, detail = executor._check_login_status()
        print(detail.strip() or "(empty status)")
        if logged_in:
            print("✅ 登录状态正常")
            sys.exit(0)
    except Exception as exc:
        print(f"❌ 检查登录状态失败: {exc}")
        sys.exit(2)

if with_qr:
    try:
        reset_before_qr = os.getenv("XHS_RESET_COOKIES_BEFORE_QR", "0").strip().lower() not in ("0", "false", "off", "no")
        if reset_before_qr:
            executor._reset_login_state_for_qr()
            print("🧹 已清理旧登录态（delete_cookies + 本地 cookie 文件）")

        qr_result = executor._call_tool("get_login_qrcode", {}, timeout=90)
        qr_text = executor._extract_text_content(qr_result) or "请用小红书 App 扫码登录"
        image_item = executor._extract_image_content(qr_result)
        if not image_item:
            print("❌ 获取二维码失败：返回中缺少 image 数据")
            sys.exit(3)

        image_bytes = base64.b64decode(image_item["data"])
        executor.login_qr_dir.mkdir(parents=True, exist_ok=True)
        qr_file = executor.login_qr_dir / f"mcp_login_qr_check_{int(time.time())}.png"
        qr_file.write_bytes(image_bytes)
        executor.login_qr_path.write_bytes(image_bytes)

        print("📷 已生成登录二维码")
        print(f"   文案: {qr_text}")
        print(f"   文件: {qr_file}")
        print(f"   Live: {executor.login_qr_path}")

        try:
            proc = subprocess.run(["open", str(qr_file)], capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"🖥️ 已尝试打开二维码: {qr_file}")
            else:
                subprocess.run(["open", str(executor.login_qr_path)], check=False)
                print("⚠️ 打开二维码文件失败，已回退打开 live 文件")
        except Exception as exc:
            print(f"⚠️ 自动打开二维码失败: {exc}")

        wait_seconds = int(os.getenv("XHS_LOGIN_WAIT_SECONDS", "180"))
        poll_seconds = int(os.getenv("XHS_LOGIN_POLL_SECONDS", "20"))
        deadline = time.time() + max(30, wait_seconds)
        print(f"⏳ 等待扫码登录，最长 {wait_seconds}s，每 {poll_seconds}s 检查一次...")

        last_text = None
        while time.time() < deadline:
            try:
                now_logged_in, now_detail = executor._check_login_status()
            except Exception as exc:
                now_logged_in = False
                now_detail = str(exc)
            if now_detail != last_text:
                print(f"🔎 状态变化: {now_detail.strip() or '(empty status)'}")
                last_text = now_detail
            if now_logged_in:
                print(f"✅ 检测到登录成功: {datetime.now().isoformat()}")
                sys.exit(0)
            time.sleep(max(15, poll_seconds))

        print("❌ 等待扫码登录超时")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ 二维码登录验证失败: {exc}")
        sys.exit(3)

print("❌ 当前未登录，请先登录后再执行抓取。")
print("建议：使用统一入口执行 all 动作，脚本会自动处理登录检查与抓取。")
print(f"命令: bash {workflow_dir}/codex_skills/xhs-job-fetch/scripts/xhs_skill.sh all --topic 'AI 工具' --time-constraint '近7天' --output-format both")
print("如需只做登录验证并拉起二维码，可运行：")
print(f"命令: bash {workflow_dir}/codex_skills/xhs-job-fetch/scripts/xhs_skill.sh login --with-qr")
sys.exit(1)
PY
