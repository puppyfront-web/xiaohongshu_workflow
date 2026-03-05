#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爬虫执行器（MCP 版）
通过 xiaohongshu-mcp 执行检索任务，不再依赖 LittleCrawler。
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import time
import base64
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    # Package import path.
    from .intent_recognizer import Intent
except ImportError:
    # Module execution path.
    from core.intent_recognizer import Intent


class CrawlerExecutor:
    """爬虫执行器（MCP）"""

    def __init__(
        self,
        mcp_url: str = "http://127.0.0.1:18060/mcp",
        health_url: str = "http://127.0.0.1:18060/health",
        mcp_binary_path: Optional[str] = None,
        auto_start_server: bool = True,
        server_start_timeout: int = 45,
        request_timeout: int = 120,
    ):
        self.work_dir = Path(__file__).resolve().parent.parent
        self.data_dir = self.work_dir / "data" / "xhs" / "json"
        self.log_dir = self.work_dir / "logs"
        self.browser_data_dir = self.work_dir / "browser_data"

        self.source_cookie_path = self.browser_data_dir / "xiaohongshu_cookies.json"
        self.mcp_cookie_path = self.browser_data_dir / "xiaohongshu_mcp_cookies.json"
        self.server_log_path = self.log_dir / "mcp_server.log"

        if mcp_binary_path is None:
            env_path = os.getenv("XHS_MCP_BINARY_PATH", "").strip()
            mcp_binary_path = env_path or None
        if mcp_binary_path is None:
            for candidate in self._default_mcp_binary_candidates():
                if candidate.exists():
                    mcp_binary_path = str(candidate)
                    break
        if mcp_binary_path is None:
            from_path = shutil.which("xiaohongshu-mcp")
            if from_path:
                mcp_binary_path = from_path
        if mcp_binary_path is None:
            # 兜底为命令名，后续会给出更明确错误提示。
            mcp_binary_path = "xiaohongshu-mcp"

        self.mcp_url = mcp_url
        self.health_url = health_url
        self.mcp_binary_path = Path(mcp_binary_path)
        self.auto_start_server = auto_start_server
        self.server_start_timeout = server_start_timeout
        self.request_timeout = request_timeout

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)

        self.login_qr_path = self.browser_data_dir / "mcp_login_qr_live.png"
        self.login_qr_dir = self.browser_data_dir / "login_qr_history"
        self.login_qr_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _platform_asset_suffix() -> str:
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system.startswith("darwin"):
            os_part = "darwin"
        elif system.startswith("linux"):
            os_part = "linux"
        elif system.startswith("windows"):
            os_part = "windows"
        else:
            os_part = system

        if machine in ("x86_64", "amd64"):
            arch_part = "amd64"
        elif machine in ("arm64", "aarch64"):
            arch_part = "arm64"
        else:
            arch_part = machine

        return f"{os_part}-{arch_part}"

    def _default_mcp_binary_candidates(self) -> List[Path]:
        suffix = self._platform_asset_suffix()
        ext = ".exe" if suffix.startswith("windows-") else ""
        asset = f"xiaohongshu-mcp-{suffix}{ext}"
        return [
            self.work_dir / "codex_skills" / "xhs-job-fetch" / "bin" / asset,
            self.work_dir / "bin" / asset,
        ]

    def _http_json(
        self,
        method: str,
        url: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = 20,
    ) -> Tuple[dict, dict]:
        raw = None
        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if headers:
            req_headers.update(headers)
        if payload is not None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(url=url, data=raw, method=method.upper(), headers=req_headers)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(body) if body else {}
                response_headers = {k.lower(): v for k, v in resp.headers.items()}
                return data, response_headers
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code} 调用失败: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            # 在受限环境中 urllib 直连本地端口可能被拦截，回退到 curl。
            if "operation not permitted" in str(exc).lower():
                return self._http_json_with_curl(method, url, payload, req_headers, timeout)
            raise RuntimeError(f"网络调用失败: {exc}") from exc
        except PermissionError as exc:
            return self._http_json_with_curl(method, url, payload, req_headers, timeout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("响应解析失败：非 JSON") from exc

    @staticmethod
    def _parse_curl_response(raw: str) -> Tuple[int, dict, str]:
        chunks = re.split(r"\r?\n\r?\n", raw)
        if not chunks:
            return 0, {}, ""

        body = chunks[-1]
        header_block = ""
        for idx in range(len(chunks) - 2, -1, -1):
            block = chunks[idx]
            if block.startswith("HTTP/"):
                header_block = block
                break

        headers = {}
        status = 0
        if header_block:
            lines = header_block.splitlines()
            if lines:
                parts = lines[0].split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status = int(parts[1])
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

        return status, headers, body

    def _http_json_with_curl(
        self,
        method: str,
        url: str,
        payload: Optional[dict],
        headers: dict,
        timeout: int,
    ) -> Tuple[dict, dict]:
        cmd = [
            "curl",
            "-sS",
            "-i",
            "-X",
            method.upper(),
            "--max-time",
            str(timeout),
            url,
        ]
        for key, value in (headers or {}).items():
            cmd.extend(["-H", f"{key}: {value}"])
        if payload is not None:
            cmd.extend(["--data-raw", json.dumps(payload, ensure_ascii=False)])

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"curl 调用失败: {proc.stderr.strip()}")

        status, response_headers, body = self._parse_curl_response(proc.stdout)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} 调用失败: {body[:500]}")
        if not body:
            return {}, response_headers

        try:
            return json.loads(body), response_headers
        except json.JSONDecodeError as exc:
            raise RuntimeError("响应解析失败：非 JSON") from exc

    def _check_server_health(self) -> bool:
        try:
            data, _ = self._http_json("GET", self.health_url, timeout=3)
        except Exception:
            return False
        return bool(data.get("success"))

    def _get_listening_pid(self) -> Optional[int]:
        parsed = urllib.parse.urlparse(self.mcp_url)
        port = str(parsed.port or 18060)
        try:
            proc = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                return None
            first = (proc.stdout or "").strip().splitlines()
            if not first:
                return None
            return int(first[0].strip())
        except Exception:
            return None

    @staticmethod
    def _get_process_cmdline(pid: int) -> str:
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                return ""
            return (proc.stdout or "").strip()
        except Exception:
            return ""

    def _restart_if_non_headless_server(self) -> bool:
        """
        如果当前在线 MCP 由 headless=false 启动，尝试重启为 headless=true，避免反复拉起浏览器。
        返回值：是否已重启（True 表示后续需要重新启动服务）。
        """
        enforce = os.getenv("XHS_ENFORCE_HEADLESS_TRUE", "1").strip().lower()
        if enforce in ("0", "false", "off", "no"):
            return False

        pid = self._get_listening_pid()
        if not pid:
            return False

        cmdline = self._get_process_cmdline(pid)
        if "xiaohongshu-mcp" not in cmdline:
            return False
        if "-headless=false" not in cmdline:
            return False

        try:
            subprocess.run(["kill", str(pid)], check=False)
            for _ in range(30):
                if not self._check_server_health():
                    break
                time.sleep(0.2)
            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                logf.write(
                    f"[{datetime.now().isoformat()}] 检测到 headless=false MCP（pid={pid}），已请求重启为 headless=true\n"
                )
            return True
        except Exception:
            return False

    def _port_flag(self) -> str:
        parsed = urllib.parse.urlparse(self.mcp_url)
        port = parsed.port or 18060
        return f":{port}"

    @staticmethod
    def _mcp_headless_flag() -> str:
        # 默认强制 headless=true，避免反复拉起可视浏览器导致登录会话抖动。
        enforce = os.getenv("XHS_ENFORCE_HEADLESS_TRUE", "1").strip().lower()
        if enforce not in ("0", "false", "off", "no"):
            return "true"

        raw = os.getenv("XHS_MCP_HEADLESS", "true").strip().lower()
        if raw in ("0", "false", "off", "no"):
            return "false"
        return "true"

    def _prepare_mcp_cookie_file(self) -> None:
        """
        准备 MCP Cookie 文件。

        根因修复：
        xiaohongshu-mcp 每次新建浏览器时都会从 cookies 文件加载状态。
        若把旧/脏 cookie 反复同步回 MCP，会导致扫码登录会话持续异常（App 侧 often failed to login）。
        因此这里改为：
        - MCP cookie 优先作为真值来源；
        - 仅在 MCP cookie 缺失且 source cookie 明显有效时，才回填到 MCP；
        - 回写 source 仅用于补齐，不做“谁新谁覆盖”的互相污染。
        """
        source_cookies = self._load_cookie_list(self.source_cookie_path)
        mcp_cookies = self._load_cookie_list(self.mcp_cookie_path)

        source_valid = self._has_login_cookies(source_cookies)
        mcp_valid = self._has_login_cookies(mcp_cookies)

        # MCP 缺失时，才用 source 回填，避免把旧状态反复灌进 MCP。
        if (not mcp_valid) and source_valid and source_cookies:
            self._write_cookie_list(self.mcp_cookie_path, source_cookies)
            mcp_cookies = source_cookies
            mcp_valid = True

        # MCP 有效时，回写 source 作为工作流侧缓存。
        if mcp_valid and mcp_cookies:
            self._write_workflow_cookie_payload(self.source_cookie_path, mcp_cookies)

    @staticmethod
    def _load_cookie_list(path: Path) -> Optional[List[dict]]:
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return None

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
            return payload["cookies"]
        return None

    @staticmethod
    def _has_login_cookies(cookies: Optional[List[dict]]) -> bool:
        if not cookies:
            return False
        keys = {}
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if isinstance(name, str) and isinstance(value, str):
                keys[name] = value
        # a1/web_session 是登录关键字段，至少命中其一才认为是可用登录态
        return bool(keys.get("a1") or keys.get("web_session"))

    @staticmethod
    def _write_cookie_list(path: Path, cookies: List[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _write_workflow_cookie_payload(path: Path, cookies: List[dict]) -> None:
        key_names = ["a1", "web_session", "webId", "xsecappid", "x-uid"]
        key_values = {name: "" for name in key_names}

        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if name in key_values and isinstance(value, str):
                key_values[name] = value

        payload = {
            "saved_at": datetime.now().isoformat(),
            "cookies": cookies,
            "cookies_str": "; ".join([f"{k}={v}" for k, v in key_values.items() if v]),
            "xhs_cookies": key_values,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _start_server_if_needed(self) -> Tuple[bool, str]:
        if self._check_server_health():
            restarted = self._restart_if_non_headless_server()
            if not restarted and self._check_server_health():
                return True, "MCP 服务已在线"

        if not self.auto_start_server:
            return False, "MCP 服务未运行，请先启动 xiaohongshu-mcp"

        if not self.mcp_binary_path.exists():
            return False, f"未找到 MCP 二进制: {self.mcp_binary_path}"

        self._prepare_mcp_cookie_file()

        env = os.environ.copy()
        if self.mcp_cookie_path.exists():
            env["COOKIES_PATH"] = str(self.mcp_cookie_path)

        cmd = [
            str(self.mcp_binary_path),
            f"-headless={self._mcp_headless_flag()}",
            "-port",
            self._port_flag(),
        ]

        with open(self.server_log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n[{datetime.now().isoformat()}] 启动 MCP 服务: {' '.join(cmd)}\n")

        log_stream = open(self.server_log_path, "a", encoding="utf-8")
        process = subprocess.Popen(
            cmd,
            cwd=str(self.work_dir),
            env=env,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        deadline = time.time() + self.server_start_timeout
        while time.time() < deadline:
            if process.poll() is not None:
                return False, f"MCP 服务启动失败（退出码 {process.returncode}），请查看 {self.server_log_path}"
            if self._check_server_health():
                return True, "MCP 服务启动成功"
            time.sleep(1)

        return False, f"MCP 服务启动超时，请查看 {self.server_log_path}"

    def _initialize_mcp_session(self) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "xiaohongshu-workflow", "version": "1.0.0"},
            },
        }
        _, headers = self._http_json("POST", self.mcp_url, payload=payload, timeout=15)

        session_id = headers.get("mcp-session-id") or headers.get("mcp-session-id".title())
        if not session_id:
            raise RuntimeError("MCP initialize 成功但未返回 mcp-session-id")
        return session_id

    def _call_tool(self, name: str, arguments: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
        session_id = self._initialize_mcp_session()
        payload = {
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        response, _ = self._http_json(
            "POST",
            self.mcp_url,
            payload=payload,
            headers={"mcp-session-id": session_id},
            timeout=timeout or self.request_timeout,
        )

        if "error" in response:
            error = response["error"]
            raise RuntimeError(f"MCP 工具调用失败({name}): {error}")

        return response.get("result", {})

    @staticmethod
    def _extract_text_content(result: dict) -> str:
        chunks = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                chunks.append(item.get("text", ""))
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_image_content(result: dict) -> Optional[dict]:
        for item in result.get("content", []):
            if item.get("type") == "image" and item.get("data"):
                return item
        return None

    def _check_login_status(self) -> Tuple[bool, str]:
        result = self._call_tool("check_login_status", {}, timeout=30)
        text = self._extract_text_content(result)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first_line = lines[0] if lines else text.strip()

        if "未登录" in first_line:
            return False, text
        if "已登录" in first_line:
            return True, text

        # 兼容返回体里既含“已登录”又含“未登录提示文案”的情况，优先用首行语义判断。
        logged_in = ("已登录" in text) and ("未登录" not in text)
        return logged_in, text

    def _reset_login_state_for_qr(self) -> None:
        """
        在生成二维码前清理旧登录态，避免脏 cookie 导致扫码后 failed to login。
        """
        try:
            result = self._call_tool("delete_cookies", {}, timeout=30)
            text = self._extract_text_content(result)
            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                logf.write(
                    f"[{datetime.now().isoformat()}] 已调用 delete_cookies，返回: {(text or '(empty)').strip()}\n"
                )
        except Exception as exc:
            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                logf.write(f"[{datetime.now().isoformat()}] 调用 delete_cookies 失败: {exc}\n")

        for path in (self.source_cookie_path, self.mcp_cookie_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception as exc:
                with open(self.server_log_path, "a", encoding="utf-8") as logf:
                    logf.write(f"[{datetime.now().isoformat()}] 删除 cookie 文件失败 {path}: {exc}\n")

    @staticmethod
    def _post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 15) -> dict:
        req_headers = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=req_headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body) if body else {}

    @staticmethod
    def _post_feishu_webhook_text(webhook_url: str, text: str, timeout: int = 15) -> None:
        if not webhook_url:
            return
        payload = {"msg_type": "text", "content": {"text": text}}
        CrawlerExecutor._post_json(webhook_url, payload, timeout=timeout)

    @staticmethod
    def _multipart_form_data(fields: List[Tuple[str, bytes, Optional[str], Optional[str]]]) -> Tuple[bytes, str]:
        """
        fields: [(name, value_bytes, filename, content_type)]
        """
        boundary = f"----WebKitFormBoundary{int(time.time() * 1000)}"
        chunks: List[bytes] = []
        for name, value, filename, content_type in fields:
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            disposition = f'Content-Disposition: form-data; name="{name}"'
            if filename:
                disposition += f'; filename="{filename}"'
            chunks.append(f"{disposition}\r\n".encode("utf-8"))
            if content_type:
                chunks.append(f"Content-Type: {content_type}\r\n".encode("utf-8"))
            chunks.append(b"\r\n")
            chunks.append(value)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        return body, boundary

    @staticmethod
    def _get_feishu_tenant_access_token(app_id: str, app_secret: str, timeout: int = 15) -> str:
        payload = {"app_id": app_id, "app_secret": app_secret}
        obj = CrawlerExecutor._post_json(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            payload,
            timeout=timeout,
        )
        code = obj.get("code", 0)
        if code not in (0, "0", None):
            raise RuntimeError(f"获取 tenant_access_token 失败: code={code}, msg={obj.get('msg', '')}")
        token = obj.get("tenant_access_token", "")
        if not token:
            raise RuntimeError("获取 tenant_access_token 失败: 空 token")
        return token

    @staticmethod
    def _upload_feishu_image(image_bytes: bytes, token: str, timeout: int = 20) -> str:
        body, boundary = CrawlerExecutor._multipart_form_data(
            [
                ("image_type", b"message", None, None),
                ("image", image_bytes, "xhs-login-qr.png", "image/png"),
            ]
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/images",
            data=body,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
        code = obj.get("code", 0)
        if code not in (0, "0", None):
            raise RuntimeError(f"上传二维码失败: code={code}, msg={obj.get('msg', '')}")
        image_key = ((obj.get("data") or {}).get("image_key", "")) or obj.get("image_key", "")
        if not image_key:
            raise RuntimeError("上传二维码失败: 未返回 image_key")
        return image_key

    @staticmethod
    def _post_feishu_webhook_image(webhook_url: str, image_key: str, timeout: int = 15) -> None:
        if not webhook_url or not image_key:
            return
        payload = {"msg_type": "image", "content": {"image_key": image_key}}
        CrawlerExecutor._post_json(webhook_url, payload, timeout=timeout)

    def _auto_login_via_feishu(self) -> Tuple[bool, str]:
        """
        未登录时自动获取二维码并推送飞书，轮询登录状态，成功后继续任务。
        依赖：
        - FEISHU_WEBHOOK_URL（文本通知）
        - FEISHU_APP_ID / FEISHU_APP_SECRET（可选；用于上传二维码图片并发送 image 消息）
        """
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
        app_id = os.getenv("FEISHU_APP_ID", "").strip()
        app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
        auto_login_flag = os.getenv("XHS_AUTO_LOGIN_FEISHU", "1").strip().lower()
        if auto_login_flag in ("0", "false", "off", "no"):
            return False, "自动登录已关闭（XHS_AUTO_LOGIN_FEISHU=0）"

        if not webhook_url:
            return False, "未配置 FEISHU_WEBHOOK_URL，无法推送登录二维码"

        total_wait = int(os.getenv("XHS_LOGIN_WAIT_SECONDS", "420"))
        poll_interval = int(os.getenv("XHS_LOGIN_POLL_SECONDS", "25"))
        # 上游二维码默认有效期约 4 分钟。过于频繁换码会让手机端“确认登录”命中过期会话。
        qr_refresh = int(os.getenv("XHS_LOGIN_QR_REFRESH_SECONDS", "210"))
        qr_refresh = max(30, qr_refresh)
        deadline = time.time() + max(60, total_wait)

        reset_before_qr = os.getenv("XHS_RESET_COOKIES_BEFORE_QR", "0").strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
        if reset_before_qr:
            self._reset_login_state_for_qr()

        # 仅配置 webhook 时，降级为：文本提示 + 本机二维码扫码等待模式。
        if not app_id or not app_secret:
            auto_open_qr = os.getenv("XHS_AUTO_OPEN_QR", "1").strip().lower() not in ("0", "false", "off", "no")
            try:
                self._post_feishu_webhook_text(
                    webhook_url,
                    (
                        "小红书抓取任务检测到未登录。\n"
                        "当前仅配置了 FEISHU_WEBHOOK_URL，将使用文本提示模式。\n"
                        "系统将自动在本机生成登录二维码并尝试打开。\n"
                        f"系统将等待约 {total_wait} 秒，检测到登录后自动继续执行。"
                    ),
                )
            except Exception:
                pass

            attempt = 0
            while time.time() < deadline:
                attempt += 1
                try:
                    qr_result = self._call_tool("get_login_qrcode", {}, timeout=40)
                except Exception as exc:
                    return False, f"获取登录二维码失败: {exc}"

                qr_text = self._extract_text_content(qr_result) or "请用小红书 App 扫码登录"
                image_item = self._extract_image_content(qr_result)
                if not image_item:
                    return False, "二维码返回内容缺少 image 数据"

                image_bytes = base64.b64decode(image_item["data"])
                try:
                    qr_file = self.login_qr_dir / f"mcp_login_qr_{int(time.time())}_{attempt}.png"
                    with open(qr_file, "wb") as f:
                        f.write(image_bytes)
                    with open(self.login_qr_path, "wb") as f:
                        f.write(image_bytes)
                    with open(self.server_log_path, "a", encoding="utf-8") as logf:
                        logf.write(
                            f"[{datetime.now().isoformat()}] 已生成登录二维码 attempt={attempt} file={qr_file}\n"
                        )
                except Exception as exc:
                    return False, f"保存本地二维码失败: {exc}"

                if auto_open_qr:
                    try:
                        proc = subprocess.run(
                            ["open", str(qr_file)],
                            capture_output=True,
                            text=True,
                        )
                        if proc.returncode != 0:
                            subprocess.run(["open", str(self.login_qr_path)], check=False)
                            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                                logf.write(
                                    f"[{datetime.now().isoformat()}] 打开二维码文件失败，已回退 live 文件: {proc.stderr.strip()}\n"
                                )
                        else:
                            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                                logf.write(
                                    f"[{datetime.now().isoformat()}] 已尝试打开本机二维码文件: {qr_file}\n"
                                )
                    except Exception as exc:
                        try:
                            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                                logf.write(f"[{datetime.now().isoformat()}] 打开二维码异常: {exc}\n")
                        except Exception:
                            pass

                try:
                    self._post_feishu_webhook_text(
                        webhook_url,
                        (
                            f"{qr_text}\n"
                            f"二维码已保存到本机：{qr_file}\n"
                            f"二维码尝试 #{attempt}，请扫码后自动继续。"
                        ),
                    )
                except Exception:
                    pass

                round_deadline = min(deadline, time.time() + max(30, qr_refresh))
                while time.time() < round_deadline:
                    try:
                        logged_in, _ = self._check_login_status()
                    except Exception:
                        logged_in = False
                    if logged_in:
                        try:
                            self._post_feishu_webhook_text(
                                webhook_url,
                                "✅ 检测到本机扫码登录成功，任务继续执行。",
                            )
                        except Exception:
                            pass
                        return True, "本机扫码登录成功"
                    time.sleep(max(15, poll_interval))

            try:
                self._post_feishu_webhook_text(
                    webhook_url,
                    "⏰ 等待本机扫码登录超时，本次任务终止。请重新触发工作流。",
                )
            except Exception:
                pass
            return False, "仅 webhook 模式：等待本机扫码登录超时"

        try:
            self._post_feishu_webhook_text(
                webhook_url,
                "小红书抓取任务检测到未登录，正在生成扫码二维码，扫描后将自动继续执行。",
            )
        except Exception:
            pass

        try:
            token = self._get_feishu_tenant_access_token(app_id, app_secret)
        except Exception as exc:
            return False, f"飞书鉴权失败: {exc}"

        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                qr_result = self._call_tool("get_login_qrcode", {}, timeout=40)
            except Exception as exc:
                return False, f"获取登录二维码失败: {exc}"

            qr_text = self._extract_text_content(qr_result) or "请用小红书 App 扫码登录"
            image_item = self._extract_image_content(qr_result)
            if not image_item:
                return False, "二维码返回内容缺少 image 数据"

            image_bytes = base64.b64decode(image_item["data"])
            try:
                with open(self.login_qr_path, "wb") as f:
                    f.write(image_bytes)
                with open(self.server_log_path, "a", encoding="utf-8") as logf:
                    logf.write(
                        f"[{datetime.now().isoformat()}] 已生成飞书推送二维码 attempt={attempt} file={self.login_qr_path}\n"
                    )
            except Exception:
                pass

            try:
                image_key = self._upload_feishu_image(image_bytes, token)
                self._post_feishu_webhook_text(
                    webhook_url,
                    f"{qr_text}\n二维码尝试 #{attempt}，任务将自动等待扫码并继续执行。",
                )
                self._post_feishu_webhook_image(webhook_url, image_key)
            except Exception as exc:
                return False, f"推送二维码到飞书失败: {exc}"

            round_deadline = min(deadline, time.time() + max(30, qr_refresh))
            while time.time() < round_deadline:
                try:
                    logged_in, login_msg = self._check_login_status()
                except Exception as exc:
                    login_msg = str(exc)
                    logged_in = False
                if logged_in:
                    try:
                        self._post_feishu_webhook_text(
                            webhook_url,
                            "✅ 小红书已登录，招聘抓取任务继续执行。",
                        )
                    except Exception as exc:
                        try:
                            with open(self.server_log_path, "a", encoding="utf-8") as logf:
                                logf.write(
                                    f"[{datetime.now().isoformat()}] 飞书成功通知发送失败（不影响主流程）: {exc}\n"
                                )
                        except Exception:
                            pass
                    return True, "扫码登录成功"
                time.sleep(max(15, poll_interval))

        try:
            self._post_feishu_webhook_text(
                webhook_url,
                "⏰ 小红书扫码等待超时，本次任务终止。可重新触发工作流再次获取二维码。",
            )
        except Exception as exc:
            try:
                with open(self.server_log_path, "a", encoding="utf-8") as logf:
                    logf.write(
                        f"[{datetime.now().isoformat()}] 飞书超时通知发送失败（不影响主流程）: {exc}\n"
                    )
            except Exception:
                pass
        return False, "扫码超时，未检测到登录成功"

    def _search_feeds(self, keyword: str) -> Tuple[List[dict], int]:
        result = self._call_tool(
            "search_feeds",
            {"keyword": keyword},
            timeout=self.request_timeout,
        )
        text = self._extract_text_content(result)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"search_feeds 返回非 JSON: {text[:300]}") from exc

        feeds = payload.get("feeds", [])
        if not isinstance(feeds, list):
            raise RuntimeError("search_feeds 返回格式异常：feeds 不是列表")

        count = payload.get("count", len(feeds))
        return feeds, int(count)

    @staticmethod
    def _feed_to_legacy(feed: dict, keyword: str) -> dict:
        note_card = feed.get("noteCard") or {}
        user = note_card.get("user") or {}
        interact = note_card.get("interactInfo") or {}
        cover = note_card.get("cover") or {}
        image_list_raw = note_card.get("imageList") or []

        image_urls: List[str] = []
        if isinstance(image_list_raw, list):
            for image in image_list_raw:
                if not isinstance(image, dict):
                    continue
                candidate = image.get("url") or image.get("urlDefault") or image.get("urlPre")
                if isinstance(candidate, str) and candidate.strip():
                    image_urls.append(candidate.strip())

        if not image_urls and isinstance(cover, dict):
            candidate = cover.get("url") or cover.get("urlDefault") or cover.get("urlPre")
            if isinstance(candidate, str) and candidate.strip():
                image_urls.append(candidate.strip())

        note_id = feed.get("id", "")
        xsec_token = feed.get("xsecToken", "")
        encoded_token = urllib.parse.quote(str(xsec_token), safe="")
        note_url = (
            f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={encoded_token}&xsec_source=pc_search"
            if note_id and xsec_token
            else ""
        )

        now_ms = int(time.time() * 1000)
        return {
            "note_id": str(note_id),
            "type": str(note_card.get("type", "")),
            "title": str(note_card.get("displayTitle", "")),
            "desc": "",
            "time": 0,
            "last_update_time": now_ms,
            "user_id": str(user.get("userId", "")),
            "nickname": str(user.get("nickName") or user.get("nickname") or ""),
            "avatar": str(user.get("avatar", "")),
            "liked_count": str(interact.get("likedCount", "0")),
            "collected_count": str(interact.get("collectedCount", "0")),
            "comment_count": str(interact.get("commentCount", "0")),
            "share_count": str(interact.get("sharedCount", "0")),
            "ip_location": "",
            "image_list": ",".join(image_urls),
            "tag_list": "",
            "last_modify_ts": now_ms,
            "note_url": note_url,
            "source_keyword": keyword,
            "xsec_token": str(xsec_token),
        }

    @staticmethod
    def _is_valid_note_feed(feed: dict) -> bool:
        """过滤搜索结果中的非笔记项（如热搜推荐等）。"""
        if not isinstance(feed, dict):
            return False
        note_id = str(feed.get("id", ""))
        note_card = feed.get("noteCard")
        if not note_id or "#" in note_id:
            return False
        if not isinstance(note_card, dict):
            return False
        user = note_card.get("user")
        interact = note_card.get("interactInfo")
        return isinstance(user, dict) and isinstance(interact, dict)

    def _save_search_data(self, feeds: List[dict], keyword: str) -> Path:
        valid_feeds = [feed for feed in feeds if self._is_valid_note_feed(feed)]
        records = [self._feed_to_legacy(feed, keyword) for feed in valid_feeds]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = self.data_dir / f"search_contents_{ts}.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return output

    async def run_crawler(self, intent: Intent) -> Dict:
        start_time = datetime.now()

        if intent.platform != "xhs":
            return {
                "success": False,
                "error": f"当前仅支持 xhs 平台，收到: {intent.platform}",
            }

        try:
            ok, server_msg = self._start_server_if_needed()
            if not ok:
                return {"success": False, "error": server_msg}

            logged_in, login_msg = self._check_login_status()
            if not logged_in:
                auto_ok, auto_msg = self._auto_login_via_feishu()
                if not auto_ok:
                    return {
                        "success": False,
                        "error": "小红书 MCP 未登录，请先扫码登录",
                        "details": f"{login_msg}\n自动登录结果: {auto_msg}",
                    }
                logged_in, login_msg = self._check_login_status()
                if not logged_in:
                    return {
                        "success": False,
                        "error": "小红书 MCP 未登录，请先扫码登录",
                        "details": f"{login_msg}\n自动登录结果: {auto_msg}",
                    }

            feeds, _ = self._search_feeds(intent.keywords)
            output_file = self._save_search_data(feeds, intent.keywords)

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            data_info = self.get_crawled_data()
            return {
                "success": True,
                "intent": {
                    "platform": intent.platform,
                    "keywords": intent.keywords,
                    "crawler_type": intent.crawler_type,
                },
                "data": data_info,
                "execution_time": execution_time,
                "mcp": {
                    "url": self.mcp_url,
                    "server": server_msg,
                    "output_file": str(output_file),
                },
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    def get_crawled_data(self) -> Dict:
        json_files = sorted(
            self.data_dir.glob("search_contents_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        file_info = []
        total_records = 0

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                record_count = len(data) if isinstance(data, list) else 0
                total_records += record_count
                file_info.append(
                    {
                        "name": json_file.name,
                        "path": str(json_file),
                        "size": json_file.stat().st_size,
                        "records": record_count,
                        "modified": datetime.fromtimestamp(json_file.stat().st_mtime).isoformat(),
                    }
                )
            except Exception:
                continue

        return {
            "files": file_info,
            "total_count": total_records,
            "directory": str(self.data_dir),
        }

    def format_result(self, result: Dict) -> str:
        if not result.get("success"):
            return (
                f"❌ 爬取失败\n"
                f"错误: {result.get('error', '未知错误')}\n"
                f"详情: {result.get('details', '')}"
            )

        intent = result["intent"]
        data = result["data"]
        response = (
            f"✅ 爬取成功！\n\n"
            f"📊 执行统计\n"
            f"• 平台: 小红书\n"
            f"• 关键词: {intent['keywords']}\n"
            f"• 类型: {intent['crawler_type']}\n"
            f"• 耗时: {result['execution_time']:.1f} 秒\n"
            f"• 数据条数: {data['total_count']}\n\n"
        )

        if data["files"]:
            response += "📁 数据文件:\n"
            for file in data["files"][:3]:
                size_mb = file["size"] / (1024 * 1024)
                response += f"• {file['name']} ({size_mb:.2f} MB, {file['records']} 条记录)\n"

        response += f"\n💾 数据保存位置: {data['directory']}"
        return response


if __name__ == "__main__":
    print("请通过 core.workflow 或 core.job_fetch 调用 CrawlerExecutor")
