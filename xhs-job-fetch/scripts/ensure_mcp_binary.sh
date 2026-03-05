#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

normalize_platform() {
  local uname_s uname_m os arch
  uname_s="$(uname -s | tr '[:upper:]' '[:lower:]')"
  uname_m="$(uname -m | tr '[:upper:]' '[:lower:]')"

  case "${uname_s}" in
    darwin*) os="darwin" ;;
    linux*) os="linux" ;;
    msys*|mingw*|cygwin*) os="windows" ;;
    *)
      echo "❌ Unsupported OS: ${uname_s}" >&2
      return 2
      ;;
  esac

  case "${uname_m}" in
    x86_64|amd64) arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *)
      echo "❌ Unsupported arch: ${uname_m}" >&2
      return 2
      ;;
  esac

  printf '%s-%s\n' "${os}" "${arch}"
}

suffix="$(normalize_platform)"
os_part="${suffix%-*}"
ext=""
if [[ "${os_part}" == "windows" ]]; then
  ext=".exe"
fi
asset="xiaohongshu-mcp-${suffix}${ext}"

# Prefer explicit path from env.
if [[ -n "${XHS_MCP_BINARY_PATH:-}" ]]; then
  if [[ -x "${XHS_MCP_BINARY_PATH}" ]]; then
    printf '%s\n' "${XHS_MCP_BINARY_PATH}"
    exit 0
  fi
  echo "❌ XHS_MCP_BINARY_PATH 不可执行: ${XHS_MCP_BINARY_PATH}" >&2
  exit 2
fi

# Reuse binary from PATH if available.
if command -v xiaohongshu-mcp >/dev/null 2>&1; then
  path_bin="$(command -v xiaohongshu-mcp)"
  printf '%s\n' "${path_bin}"
  exit 0
fi

local_candidate="${SKILL_DIR}/bin/${asset}"
if [[ -x "${local_candidate}" ]]; then
  printf '%s\n' "${local_candidate}"
  exit 0
fi

echo "❌ 未找到 xiaohongshu-mcp 可执行文件。" >&2
echo "请先自行安装对应平台二进制 (${asset})，然后选择其一：" >&2
echo "  1) 导出环境变量: XHS_MCP_BINARY_PATH=/abs/path/to/${asset}" >&2
echo "  2) 将 xiaohongshu-mcp 加入 PATH" >&2
echo "  3) 放到 skill 目录: ${local_candidate}" >&2
exit 2
