#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKILL_DIR="${ROOT_DIR}/codex_skills/xhs-job-fetch"
SKILL_BIN_DIR="${SKILL_DIR}/bin"
ENV_LOCAL_FILE="${SKILL_DIR}/.env.local"

MCP_PATH_ARG="${XHS_MCP_BINARY_PATH:-}"
MCP_URL_ARG="${XHS_MCP_BINARY_URL:-}"
MCP_SHA256_ARG="${XHS_MCP_BINARY_SHA256:-}"
MCP_REPO_ARG="${XHS_MCP_REPO_URL:-https://github.com/xpzouying/xiaohongshu-mcp}"
WEBHOOK_ARG="${FEISHU_WEBHOOK_URL:-}"
APP_ID_ARG="${FEISHU_APP_ID:-}"
APP_SECRET_ARG="${FEISHU_APP_SECRET:-}"
NON_INTERACTIVE=0

usage() {
  cat <<'EOF'
Usage: bash scripts/install.sh [options]

Options:
  --mcp-path <path>           Use local xiaohongshu-mcp binary path
  --mcp-url <url>             Download xiaohongshu-mcp binary from URL
  --mcp-sha256 <sha256>       SHA256 for downloaded MCP binary (required with --mcp-url)
  --mcp-repo <url>            Auto-install MCP from GitHub repo (default: xpzouying/xiaohongshu-mcp)
  --feishu-webhook <url>      Set FEISHU_WEBHOOK_URL
  --feishu-app-id <id>        Set FEISHU_APP_ID
  --feishu-app-secret <sec>   Set FEISHU_APP_SECRET
  --non-interactive           Fail instead of prompting
  -h, --help                  Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mcp-path)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --mcp-path" >&2
        exit 2
      fi
      MCP_PATH_ARG="${2:-}"
      shift 2
      ;;
    --mcp-url)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --mcp-url" >&2
        exit 2
      fi
      MCP_URL_ARG="${2:-}"
      shift 2
      ;;
    --mcp-sha256)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --mcp-sha256" >&2
        exit 2
      fi
      MCP_SHA256_ARG="${2:-}"
      shift 2
      ;;
    --mcp-repo)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --mcp-repo" >&2
        exit 2
      fi
      MCP_REPO_ARG="${2:-}"
      shift 2
      ;;
    --feishu-webhook)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --feishu-webhook" >&2
        exit 2
      fi
      WEBHOOK_ARG="${2:-}"
      shift 2
      ;;
    --feishu-app-id)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --feishu-app-id" >&2
        exit 2
      fi
      APP_ID_ARG="${2:-}"
      shift 2
      ;;
    --feishu-app-secret)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Missing value for --feishu-app-secret" >&2
        exit 2
      fi
      APP_SECRET_ARG="${2:-}"
      shift 2
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

normalize_platform() {
  local uname_s uname_m os arch
  uname_s="$(uname -s | tr '[:upper:]' '[:lower:]')"
  uname_m="$(uname -m | tr '[:upper:]' '[:lower:]')"

  case "${uname_s}" in
    darwin*) os="darwin" ;;
    linux*) os="linux" ;;
    msys*|mingw*|cygwin*) os="windows" ;;
    *)
      echo "Unsupported OS: ${uname_s}" >&2
      return 2
      ;;
  esac

  case "${uname_m}" in
    x86_64|amd64) arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *)
      echo "Unsupported arch: ${uname_m}" >&2
      return 2
      ;;
  esac

  printf '%s-%s\n' "${os}" "${arch}"
}

prompt() {
  local message="$1"
  local default="${2:-}"
  local value=""
  if [[ ${NON_INTERACTIVE} -eq 1 ]]; then
    printf '%s\n' "${default}"
    return
  fi
  if [[ -n "${default}" ]]; then
    read -r -p "${message} [${default}]: " value || true
    if [[ -z "${value}" ]]; then
      value="${default}"
    fi
  else
    read -r -p "${message}: " value || true
  fi
  printf '%s\n' "${value}"
}

download_binary() {
  local url="$1"
  local target="$2"
  local expected_sha="$3"
  mkdir -p "$(dirname "${target}")"
  echo "Downloading MCP binary..." >&2
  if ! curl -fsSL "${url}" -o "${target}.tmp"; then
    rm -f "${target}.tmp"
    echo "Failed to download MCP binary: ${url}" >&2
    exit 2
  fi
  verify_sha256 "${target}.tmp" "${expected_sha}"
  chmod +x "${target}.tmp"
  mv -f "${target}.tmp" "${target}"
}

calc_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file}" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file}" | awk '{print $1}'
    return
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "${file}" | awk '{print $NF}'
    return
  fi
  echo "No SHA256 tool found (need sha256sum/shasum/openssl)." >&2
  exit 2
}

verify_sha256() {
  local file="$1"
  local expected="$2"
  if [[ ! -f "${file}" ]]; then
    echo "Downloaded MCP binary not found: ${file}" >&2
    exit 2
  fi
  if [[ -z "${expected}" ]]; then
    echo "SHA256 is required for MCP download." >&2
    exit 2
  fi
  local actual expected_lower actual_lower
  actual="$(calc_sha256 "${file}")"
  expected_lower="$(printf '%s' "${expected}" | tr '[:upper:]' '[:lower:]')"
  actual_lower="$(printf '%s' "${actual}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${actual_lower}" != "${expected_lower}" ]]; then
    echo "SHA256 mismatch for downloaded MCP binary." >&2
    echo "expected=${expected_lower}" >&2
    echo "actual=${actual_lower}" >&2
    exit 2
  fi
}

validate_mcp_candidate_name() {
  local bin_path="$1"
  local base_name
  base_name="$(basename "${bin_path}")"
  if [[ "${base_name}" == xiaohongshu-mcp* ]]; then
    return
  fi
  if [[ "${XHS_SKIP_MCP_NAME_CHECK:-0}" == "1" ]]; then
    return
  fi
  echo "Provided MCP path does not look like xiaohongshu-mcp: ${bin_path}" >&2
  echo "If this is intentional, set XHS_SKIP_MCP_NAME_CHECK=1 and retry." >&2
  exit 2
}

normalize_repo_slug() {
  local input="$1"
  local slug="${input}"
  slug="${slug#https://github.com/}"
  slug="${slug#http://github.com/}"
  slug="${slug#git@github.com:}"
  slug="${slug%.git}"
  slug="${slug#/}"
  slug="${slug%/}"
  if [[ "${slug}" =~ ^[^/]+/[^/]+$ ]]; then
    printf '%s\n' "${slug}"
    return 0
  fi
  return 1
}

auto_install_from_repo_release() {
  local repo_url="$1"
  local target="$2"
  local asset="$3"
  local repo_slug
  local try_url
  local tmp_download="${target}.download"
  local extract_dir="${target}.extract"
  local candidate

  if ! repo_slug="$(normalize_repo_slug "${repo_url}")"; then
    echo "Invalid --mcp-repo URL: ${repo_url}" >&2
    return 1
  fi

  mkdir -p "$(dirname "${target}")"
  rm -f "${tmp_download}" "${target}.tmp"
  rm -rf "${extract_dir}"

  for try_url in \
    "https://github.com/${repo_slug}/releases/latest/download/${asset}" \
    "https://github.com/${repo_slug}/releases/latest/download/${asset}.tar.gz" \
    "https://github.com/${repo_slug}/releases/latest/download/${asset}.zip"; do
    echo "Trying MCP auto-download from: ${try_url}" >&2
    if ! curl -fsSL "${try_url}" -o "${tmp_download}"; then
      rm -f "${tmp_download}"
      continue
    fi

    case "${try_url}" in
      *.tar.gz)
        if ! command -v tar >/dev/null 2>&1; then
          rm -f "${tmp_download}"
          continue
        fi
        rm -rf "${extract_dir}"
        mkdir -p "${extract_dir}"
        if ! tar -xzf "${tmp_download}" -C "${extract_dir}" >/dev/null 2>&1; then
          rm -rf "${extract_dir}" "${tmp_download}"
          continue
        fi
        candidate="$(find "${extract_dir}" -type f -name "xiaohongshu-mcp*" | head -n 1 || true)"
        if [[ -z "${candidate}" ]]; then
          rm -rf "${extract_dir}" "${tmp_download}"
          continue
        fi
        cp -f "${candidate}" "${target}.tmp"
        ;;
      *.zip)
        if ! command -v unzip >/dev/null 2>&1; then
          rm -f "${tmp_download}"
          continue
        fi
        rm -rf "${extract_dir}"
        mkdir -p "${extract_dir}"
        if ! unzip -q "${tmp_download}" -d "${extract_dir}" >/dev/null 2>&1; then
          rm -rf "${extract_dir}" "${tmp_download}"
          continue
        fi
        candidate="$(find "${extract_dir}" -type f -name "xiaohongshu-mcp*" | head -n 1 || true)"
        if [[ -z "${candidate}" ]]; then
          rm -rf "${extract_dir}" "${tmp_download}"
          continue
        fi
        cp -f "${candidate}" "${target}.tmp"
        ;;
      *)
        mv -f "${tmp_download}" "${target}.tmp"
        ;;
    esac

    chmod +x "${target}.tmp"
    mv -f "${target}.tmp" "${target}"
    rm -rf "${extract_dir}" "${tmp_download}"
    return 0
  done

  rm -rf "${extract_dir}" "${tmp_download}" "${target}.tmp"
  return 1
}

auto_build_from_repo_source() {
  local repo_url="$1"
  local target="$2"
  local tmp_dir

  if ! command -v git >/dev/null 2>&1; then
    echo "git not found; skip source build fallback." >&2
    return 1
  fi
  if ! command -v go >/dev/null 2>&1; then
    echo "go not found; skip source build fallback." >&2
    return 1
  fi

  tmp_dir="$(mktemp -d /tmp/xhs-mcp-src.XXXXXX)"
  mkdir -p "$(dirname "${target}")"

  if ! git clone --depth 1 "${repo_url}" "${tmp_dir}" >/dev/null 2>&1; then
    rm -rf "${tmp_dir}"
    return 1
  fi

  if ! (cd "${tmp_dir}" && go build -o "${target}.tmp" .) >/dev/null 2>&1; then
    rm -rf "${tmp_dir}"
    rm -f "${target}.tmp"
    return 1
  fi

  chmod +x "${target}.tmp"
  mv -f "${target}.tmp" "${target}"
  rm -rf "${tmp_dir}"
  return 0
}

resolve_mcp_path() {
  local suffix os_part ext asset local_candidate selected_path selected_url selected_sha selected_repo
  suffix="$(normalize_platform)"
  os_part="${suffix%-*}"
  ext=""
  if [[ "${os_part}" == "windows" ]]; then
    ext=".exe"
  fi
  asset="xiaohongshu-mcp-${suffix}${ext}"
  local_candidate="${SKILL_BIN_DIR}/${asset}"

  selected_path="${MCP_PATH_ARG}"
  selected_url="${MCP_URL_ARG}"
  selected_sha="${MCP_SHA256_ARG}"
  selected_repo="${MCP_REPO_ARG}"

  if [[ -n "${selected_path}" ]]; then
    if [[ -x "${selected_path}" ]]; then
      validate_mcp_candidate_name "${selected_path}"
      printf '%s\n' "${selected_path}"
      return
    fi
    echo "Provided MCP path is not executable: ${selected_path}" >&2
    exit 2
  fi

  if command -v xiaohongshu-mcp >/dev/null 2>&1; then
    local from_path
    from_path="$(command -v xiaohongshu-mcp)"
    validate_mcp_candidate_name "${from_path}"
    printf '%s\n' "${from_path}"
    return
  fi

  if [[ -x "${local_candidate}" ]]; then
    validate_mcp_candidate_name "${local_candidate}"
    printf '%s\n' "${local_candidate}"
    return
  fi

  if [[ -n "${selected_url}" ]]; then
    if [[ -z "${selected_sha}" ]]; then
      echo "MCP SHA256 is required with --mcp-url / XHS_MCP_BINARY_URL." >&2
      exit 2
    fi
    download_binary "${selected_url}" "${local_candidate}" "${selected_sha}"
    validate_mcp_candidate_name "${local_candidate}"
    printf '%s\n' "${local_candidate}"
    return
  fi

  if [[ -n "${selected_repo}" ]]; then
    if auto_install_from_repo_release "${selected_repo}" "${local_candidate}" "${asset}"; then
      validate_mcp_candidate_name "${local_candidate}"
      printf '%s\n' "${local_candidate}"
      return
    fi
    if [[ ${NON_INTERACTIVE} -eq 0 ]]; then
      echo "Auto-download from repo release failed, trying source build..." >&2
      if auto_build_from_repo_source "${selected_repo}" "${local_candidate}"; then
        validate_mcp_candidate_name "${local_candidate}"
        printf '%s\n' "${local_candidate}"
        return
      fi
    fi
  fi

  if [[ ${NON_INTERACTIVE} -eq 1 ]]; then
    echo "MCP binary not found." >&2
    echo "Tried repo auto-install: ${selected_repo}" >&2
    echo "Provide --mcp-path, --mcp-url(+--mcp-sha256), or a working --mcp-repo." >&2
    exit 2
  fi

  echo "No MCP binary found for current platform (${asset})." >&2
  echo "Select one option:" >&2
  echo "  1) Input local binary path" >&2
  echo "  2) Input binary download URL (installer downloads automatically)" >&2
  echo "  3) Auto-install from GitHub repo (default: ${selected_repo})" >&2
  read -r -p "Choice [1/2/3]: " choice

  if [[ "${choice}" == "3" ]]; then
    local repo_input
    repo_input="$(prompt "Input MCP GitHub repo URL" "${selected_repo}")"
    if [[ -z "${repo_input}" ]]; then
      echo "MCP repo URL is required." >&2
      exit 2
    fi
    if auto_install_from_repo_release "${repo_input}" "${local_candidate}" "${asset}" \
      || auto_build_from_repo_source "${repo_input}" "${local_candidate}"; then
      validate_mcp_candidate_name "${local_candidate}"
      printf '%s\n' "${local_candidate}"
      return
    fi
    echo "Auto-install from repo failed: ${repo_input}" >&2
    exit 2
  fi

  if [[ "${choice}" == "2" ]]; then
    selected_url="$(prompt "Input MCP binary URL")"
    if [[ -z "${selected_url}" ]]; then
      echo "MCP URL is required." >&2
      exit 2
    fi
    selected_sha="$(prompt "Input MCP binary SHA256")"
    if [[ -z "${selected_sha}" ]]; then
      echo "MCP SHA256 is required." >&2
      exit 2
    fi
    download_binary "${selected_url}" "${local_candidate}" "${selected_sha}"
    validate_mcp_candidate_name "${local_candidate}"
    printf '%s\n' "${local_candidate}"
    return
  fi

  selected_path="$(prompt "Input local MCP binary path")"
  if [[ -z "${selected_path}" || ! -x "${selected_path}" ]]; then
    echo "Invalid MCP path: ${selected_path}" >&2
    exit 2
  fi
  validate_mcp_candidate_name "${selected_path}"
  printf '%s\n' "${selected_path}"
}

write_env_kv() {
  local key="$1"
  local value="$2"
  printf '%s=%q\n' "${key}" "${value}" >> "${ENV_LOCAL_FILE}"
}

main() {
  if [[ ! -d "${SKILL_DIR}" ]]; then
    echo "Skill directory not found: ${SKILL_DIR}" >&2
    exit 2
  fi

  echo "== xhs-info-fetch installer =="
  echo "ROOT_DIR=${ROOT_DIR}"

  local resolved_mcp webhook app_id app_secret
  resolved_mcp="$(resolve_mcp_path)"
  echo "MCP binary: ${resolved_mcp}"

  webhook="${WEBHOOK_ARG}"
  if [[ -z "${webhook}" && ${NON_INTERACTIVE} -eq 0 ]]; then
    webhook="$(prompt "Feishu webhook URL (optional, leave blank to skip)")"
  fi

  app_id="${APP_ID_ARG}"
  app_secret="${APP_SECRET_ARG}"
  if [[ -n "${webhook}" && ${NON_INTERACTIVE} -eq 0 ]]; then
    if [[ -z "${app_id}" ]]; then
      app_id="$(prompt "Feishu APP ID (optional, for QR image push)")"
    fi
    if [[ -z "${app_secret}" ]]; then
      app_secret="$(prompt "Feishu APP SECRET (optional, for QR image push)")"
    fi
  fi

  : > "${ENV_LOCAL_FILE}"
  {
    echo "# Generated by scripts/install.sh"
    echo "# Edit values if needed."
  } >> "${ENV_LOCAL_FILE}"
  write_env_kv "WORKFLOW_DIR" "${ROOT_DIR}"
  write_env_kv "XHS_MCP_BINARY_PATH" "${resolved_mcp}"
  write_env_kv "XHS_MCP_REPO_URL" "${MCP_REPO_ARG}"
  write_env_kv "FEISHU_WEBHOOK_URL" "${webhook}"
  write_env_kv "FEISHU_WEBHOOK_TIMEOUT" "15"
  write_env_kv "FEISHU_APP_ID" "${app_id}"
  write_env_kv "FEISHU_APP_SECRET" "${app_secret}"
  write_env_kv "XHS_AUTO_LOGIN_FEISHU" "1"
  write_env_kv "XHS_LOGIN_WAIT_SECONDS" "420"
  write_env_kv "XHS_LOGIN_POLL_SECONDS" "25"
  write_env_kv "XHS_LOGIN_QR_REFRESH_SECONDS" "210"
  write_env_kv "XHS_RESET_COOKIES_BEFORE_QR" "0"
  write_env_kv "XHS_ENFORCE_HEADLESS_TRUE" "1"
  write_env_kv "XHS_MCP_HEADLESS" "true"
  write_env_kv "JOB_TOPIC" ""
  write_env_kv "JOB_REGION" ""
  write_env_kv "JOB_TIME_CONSTRAINT" ""
  write_env_kv "JOB_OUTPUT_FORMAT" ""
  write_env_kv "XHS_REQUIREMENT_GUARD" "1"

  echo "Wrote config: ${ENV_LOCAL_FILE}"

  local check_script
  check_script="${SKILL_DIR}/scripts/ensure_mcp_binary.sh"
  XHS_MCP_BINARY_PATH="${resolved_mcp}" bash "${check_script}" >/dev/null
  echo "MCP validation passed."

  echo
  echo "Next commands:"
  echo "  bash ${SKILL_DIR}/scripts/xhs_skill.sh clarify"
  echo "  bash ${SKILL_DIR}/scripts/xhs_skill.sh all --topic 'AI 工具' --time-constraint '近7天' --output-format both --region '上海' --config configs/job_fetch.profile.example.json"
  echo
  echo "Assistant command template:"
  echo "  请先和我澄清抓取需求（信息类型、时间约束、返回格式），再执行 xhs_skill.sh 的 all 动作，并返回最新日志与结果文件。"
}

main "$@"
