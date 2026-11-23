#!/usr/bin/env python3
"""Set up, rebuild, and preview the mirror on Windows, macOS, or Linux."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
VENV = ROOT / ".venv"
DEFAULT_CACHE = ROOT / "translations" / "google.jsonl"


class LocalError(RuntimeError):
    """A recoverable setup or preview problem with a useful next step."""


def virtual_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command):
    command = [str(part) for part in command]
    display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    print(f"> {display}", flush=True)
    environment = os.environ.copy()
    environment.setdefault("PIP_CACHE_DIR", str(ROOT / ".local" / "pip-cache"))
    environment.setdefault("npm_config_cache", str(ROOT / ".local" / "npm-cache"))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def require_tools():
    tools = {name: shutil.which(name) for name in ("node", "npm", "git")}
    missing = [name for name, program in tools.items() if program is None]
    if missing:
        raise LocalError("缺少依赖：" + ", ".join(missing) + "。请安装 Node.js 18+（含 npm）及 Git，并重新打开终端。")
    version = subprocess.run([tools["node"], "--version"], cwd=ROOT, capture_output=True, text=True, check=True)
    major = re.match(r"v?(\d+)", version.stdout.strip())
    if not major or int(major.group(1)) < 18:
        raise LocalError("需要 Node.js 18 或更高版本。")
    return tools


def setup_environment(tools):
    if not virtual_python().is_file():
        run([sys.executable, "-m", "venv", VENV])
    run([virtual_python(), "-m", "pip", "install", "-r", ROOT / "requirements.txt"])
    run([tools["npm"], "ci", "--ignore-scripts", "--no-audit", "--no-fund"])


def cache_path(value):
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(ROOT) or candidate.suffix != ".jsonl":
        raise LocalError("翻译缓存必须是项目目录中的 .jsonl 文件。")
    return candidate


def build_site(cache, no_fetch=False):
    if not virtual_python().is_file() or not (ROOT / "node_modules" / "@asciidoctor" / "core" / "package.json").is_file():
        raise LocalError("尚未安装构建依赖。请先运行：python scripts/local.py --setup")
    command = [virtual_python(), ROOT / "scripts" / "sync.py", "--skip-translate"]
    if cache.is_file():
        command.extend(["--import-cache", cache])
        print(f"使用已保存的 Google 翻译缓存：{cache.relative_to(ROOT)}", flush=True)
    elif cache == DEFAULT_CACHE:
        print("未找到 translations/google.jsonl，将构建英文内容；后续可导入 Google 翻译缓存。", flush=True)
    else:
        raise LocalError(f"指定的翻译缓存不存在：{cache}")
    if no_fetch:
        command.append("--no-fetch")
    run(command)


def validate_site(directory):
    catalog = directory / "data" / "catalog.json"
    if not (directory / "index.html").is_file() or not catalog.is_file():
        raise LocalError("尚未生成完整站点。请运行：python scripts/local.py --setup --serve")
    try:
        document = json.loads(catalog.read_text(encoding="utf-8"))
        pages = document.get("pages") if isinstance(document, dict) else None
        if not isinstance(pages, list) or not pages:
            raise ValueError("Empty chapter catalog")
    except (OSError, ValueError) as error:
        raise LocalError("站点目录数据不可用。请运行：python scripts/local.py --sync --serve") from error


def serve(port):
    validate_site(PUBLIC)
    handler = partial(SimpleHTTPRequestHandler, directory=str(PUBLIC))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as error:
        raise LocalError(f"无法监听本地端口 {port}：{error}。可使用 --port 8081 更换端口。") from error
    with server:
        print(f"本地预览：http://127.0.0.1:{server.server_port}/", flush=True)
        print("按 Ctrl+C 停止。服务只公开 public/，仅接受本机连接。", flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print("\n本地预览已停止。", flush=True)


def port_number(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("端口必须是 1 至 65535 的整数") from error
    if not 1 <= result <= 65535:
        raise argparse.ArgumentTypeError("端口必须是 1 至 65535 的整数")
    return result


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, epilog="首次运行：python scripts/local.py --setup --serve；之后：python scripts/local.py")
    parser.add_argument("--setup", action="store_true", help="安装本地依赖，并使用已有 Google 缓存构建站点")
    parser.add_argument("--sync", action="store_true", help="同步上游并重新构建；保留未翻译内容，不发起新的翻译请求")
    parser.add_argument("--serve", action="store_true", help="启动本机预览；没有其他操作时默认启动")
    parser.add_argument("--port", type=port_number, default=8080, help="本机预览端口，默认 8080")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="导入的项目内 JSONL 翻译缓存，默认 translations/google.jsonl")
    parser.add_argument("--no-fetch", action="store_true", help="构建时使用已检出的上游源码，不获取更新")
    args = parser.parse_args(argv)
    if args.no_fetch and not (args.setup or args.sync):
        parser.error("--no-fetch 需要同时使用 --setup 或 --sync")
    try:
        if args.setup or args.sync:
            if sys.version_info < (3, 10):
                raise LocalError("构建脚本需要 Python 3.10 或更高版本。")
            cache = cache_path(args.cache)
            tools = require_tools()
            if args.setup:
                setup_environment(tools)
            build_site(cache, args.no_fetch)
        if args.serve or not (args.setup or args.sync):
            serve(args.port)
        return 0
    except LocalError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"命令未成功完成（退出码 {error.returncode}）。请查看上方输出，解决后重试。", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"无法执行本地操作：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n操作已停止。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
