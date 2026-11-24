#!/usr/bin/env python3
"""Build and incrementally translate the official Vulkan Tutorial without serving credentials."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import html
import gc
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from bs4 import BeautifulSoup, NavigableString

if __package__:
    from .translation_cache import cache_path, import_cache, export_cache
    from .terminology import TermAnnotator
else:
    # Direct CLI execution and importlib-based checks both resolve this sibling module.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from translation_cache import cache_path, import_cache, export_cache
    from terminology import TermAnnotator

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "https://github.com/KhronosGroup/Vulkan-Tutorial.git"
PROVIDER = "Google Translate（免费网页接口，非 SLA API）"
TOKEN_RE = re.compile(r"__VT([0-9]{5})__")
API_RE = r"\b(?:vk::[\w:]+|vk[A-Z]\w+|VK_[A-Z0-9_]+)\b"
SEED = {
    "Khronos Vulkan® Tutorial": "Khronos Vulkan® 教程",
    "Introduction": "简介", "Overview": "概述", "Attribution": "署名与许可",
    "Differences": "与原版教程的区别", "About": "关于本教程", "Requirements": "前置要求",
    "Selecting a physical device": "选择物理设备", "Base code": "基础代码",
    "Physical devices and queue families": "物理设备与队列族",
    "Build and development environment": "构建与开发环境",
    "Development environment": "开发环境", "Instance": "实例",
    "Validation layers": "验证层", "Logical device and queues": "逻辑设备与队列",
    "Window surface": "窗口表面", "Swap chain": "交换链", "Image views": "图像视图",
    "Command buffers": "命令缓冲区", "Dynamic rendering": "动态渲染",
    "Drawing a triangle": "绘制三角形", "Vertex buffers": "顶点缓冲区",
    "Uniform buffers": "统一缓冲区", "Texture mapping": "纹理映射",
    "Depth buffering": "深度缓冲", "Loading models": "加载模型",
    "Generating Mipmaps": "生成 Mipmap", "Multisampling": "多重采样",
    "Compute Shader": "计算着色器", "Conclusion": "结语", "Summary": "小结",
    "Swap chain recreation": "重建交换链", "Frames in flight": "并行帧",
    "Rendering and presentation": "渲染与呈现", "Presentation": "呈现", "Images": "图像",
    "Shader modules": "着色器模块", "Graphics pipeline basics": "图形管线基础",
    "Vertex input description": "顶点输入描述", "Descriptor layout and buffer": "描述符布局与缓冲区",
    "Descriptor pool and sets": "描述符池与描述符集",
    "Tooling": "开发工具", "TLAS Animation": "TLAS 动画", "NNEF Introduction": "NNEF 简介",
    "Engine Architecture: Component Systems": "引擎架构：组件系统",
    "GUI: Setting Up Dear ImGui": "GUI：配置 Dear ImGui",
    "Slang for Spatial Shaders: Single-Pass Stereo and Beyond": "用于空间着色器的 Slang：单遍立体渲染及更多应用",
    "Slang Architecture for N-View Shaders": "N 视图着色器的 Slang 架构",
    "Slang Architecture": "Slang 架构",
    "Storing the Plenoptic Function": "存储全光函数",
}
SEED_CASEFOLD = {text.casefold(): translation for text, translation in SEED.items()}
GROUPS = {
    "Building_a_Simple_Engine": "构建简易引擎", "Advanced_Vulkan_Compute": "高级 Vulkan 计算",
    "ML_Inference": "机器学习推理", "OpenXR_Vulkan_Spatial_Computing": "OpenXR 与空间计算",
    "AI_Assisted_Vulkan": "AI 辅助 Vulkan 开发", "Advanced_glTF": "高级 glTF",
    "Synchronization": "同步专题", "courses": "专题课程",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def translation_key(original, tokens, glossary_version, provider="google"):
    # The placeholder-to-markup map is part of identity: different APIs/links must never share output.
    payload = json.dumps({"version": 5, "provider": provider, "glossary": glossary_version, "text": original, "tokens": tokens},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def navigation_metadata(entries, known_ids, cache, glossary_version, terminology=None):
    """Preserve the official hierarchy, reusing only exact cached title translations."""
    navigation = []
    for raw in entries:
        entry = {"title": raw["title"], "depth": raw["depth"]}
        if raw.get("id") in known_ids:
            entry["id"] = raw["id"]
        if re.match(r"^https?://", raw.get("href", "")):
            entry["href"] = raw["href"]
        seed = SEED_CASEFOLD.get(raw["title"].strip().casefold())
        translated = seed or cache.get(translation_key(raw["title"], {}, glossary_version))
        if translated:
            entry["titleZh"] = BeautifulSoup(translated, "html.parser").get_text()
            if terminology:
                english = BeautifulSoup(f'<span>{html.escape(raw["title"])}</span>', "html.parser").span
                chinese = BeautifulSoup(f'<span>{html.escape(entry["titleZh"])}</span>', "html.parser").span
                terminology.annotate(english, chinese)
                entry["titleZh"] = chinese.get_text()
        navigation.append(entry)
    return navigation


def route_link(href: str, page_id: str, known_ids: set[str]):
    """Rewrite local chapter, image and attachment targets; never rewrite external sites."""
    if href.startswith(("http://", "https://", "mailto:", "data:", "#", "javascript:")):
        return href
    decoded = unquote(href)
    for segment in ("images/", "attachments/"):
        position = decoded.find(segment)
        if position >= 0:
            return "/assets/" + decoded[position:]
    path, marker, anchor = decoded.partition("#")
    if not path.endswith((".adoc", ".html")):
        return href
    path = re.sub(r"\.(adoc|html)$", "", path)
    # Antora xref paths are often ROOT-relative, while authored links may be relative.
    candidates = [path.lstrip("/"), str(PurePosixPath(page_id).parent / path)]
    for candidate in candidates:
        parts = []
        for component in candidate.split("/"):
            if component == "..":
                if parts: parts.pop()
            elif component not in ("", "."):
                parts.append(component)
        candidate = "/".join(parts)
        if candidate in known_ids:
            return "/?page=" + quote(candidate, safe="") + ("#" + anchor if marker else "")
    return "https://docs.vulkan.org/tutorial/latest/" + path.lstrip("/") + ".html" + ("#" + anchor if marker else "")


def prepare_translation(block, glossary):
    """Protect inline markup, Vulkan API identifiers and glossary terms from MT changes."""
    clone = BeautifulSoup(str(block), "html.parser").find()
    tokens = {}

    def protect(value):
        token = f"__VT{len(tokens):05d}__"
        tokens[token] = value
        return token

    for element in list(clone.select("code,kbd,samp,math")):
        element.replace_with(NavigableString(protect(str(element))))
    terms = sorted(glossary, key=len, reverse=True)
    term_re = re.compile(r"(?<![\w])(" + "|".join(re.escape(term) for term in terms) + r")(?![\w])" if terms else r"(?!)", re.I)
    glossary_lower = {key.lower(): value for key, value in glossary.items()}
    for text_node in list(clone.find_all(string=True)):
        if not str(text_node).strip():
            continue

        def term_match(match):
            english = match.group(0)
            chinese = glossary_lower[english.lower()]
            return protect(f'<span class="vt-term" data-term="{html.escape(english, quote=True)}" title="{html.escape(english, quote=True)}">{html.escape(chinese)}</span>')

        value = term_re.sub(term_match, str(text_node))
        value = re.sub(API_RE, lambda match: protect(html.escape(match.group(0))), value)
        text_node.replace_with(NavigableString(value))
    inner = clone.decode_contents()
    # Markup remains exact; only prose is sent to translation.
    plain = re.sub(r"<[^>]*>", lambda match: protect(match.group(0)), inner)
    plain = re.sub(r"\s+", " ", html.unescape(plain)).strip()
    return plain, tokens


def restore_translation(translated: str, tokens: dict[str, str]):
    # Google sometimes rewrites only marker decoration (spaces, underscore width/count or VT case).
    # Retain the exact five-digit identity; a missing or duplicated identity is still an error.
    # Match intact markers first so adjacent English does not cause the loose form to split them.
    translated = re.sub(
        TOKEN_RE.pattern + r"|(?<![A-Za-z0-9])(?:[_＿]\s*)*[Vv][Tt]\s*(?P<loose>[0-9０-９]{5})(?:\s*[_＿])*(?![A-Za-z0-9])",
        lambda match: "__VT" + unicodedata.normalize("NFKC", match["loose"]) + "__"
        if match["loose"] else match[0], translated)
    actual = {match.group(0) for match in TOKEN_RE.finditer(translated)}
    if actual != set(tokens):
        raise ValueError("Translation lost or invented a protected token identity")
    for token in tokens:
        if translated.count(token) != 1:
            raise ValueError("Translation changed a protected code/markup token")
    safe = html.escape(translated, quote=False)
    for token, original in tokens.items():
        safe = safe.replace(token, original)
    return safe


def load_reviewed_translations(path):
    """Load source-keyed corrections separately from Google's raw cache."""
    reviewed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(reviewed, dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(text, str) or not text.strip()
        for key, text in reviewed.items()
    ):
        raise ValueError("Reviewed translations must map source cache keys to translation text")
    return reviewed


def local_term_translation(plain, tokens):
    """A block made entirely of protected terms needs no machine translation."""
    if re.search(r"[A-Za-z]{3}", TOKEN_RE.sub("", plain)):
        return None
    if not any('data-term=' in value for value in tokens.values()):
        return None
    return restore_translation(plain, tokens)


def wrap_bilingual_pair(soup, block):
    cell = block.name in ("td", "th", "dt")
    pair = soup.new_tag("span" if cell else "div")
    pair["class"] = ["vt-pair", "vt-pending"]
    if cell:
        # Keep the cell itself visible in every language; only its inner original is English-only.
        original = soup.new_tag("span")
        original["class"] = ["vt-en"]
        for child in list(block.contents): original.append(child)
        block.append(pair)
        pair.append(original)
    else:
        block["class"] = block.get("class", []) + ["vt-en"]
        block.wrap(pair)
    return pair


class TranslationRateLimited(RuntimeError):
    pass


def describe_rpc_error(error):
    details = type(error).__name__
    if isinstance(error, HTTPError): details += f", HTTP {error.code}"
    # Do not log request URLs, source paragraphs or response bodies.
    return details


class GoogleTranslator:
    def __init__(self, delay=1.0, max_retries=3):
        self.delay = delay
        self.max_retries = max_retries
        self.request_lock = threading.Lock()
        self.last_request = 0
        self.gtx_retry_disabled = False

    def throttle(self):
        with self.request_lock:
            pause = self.delay - (time.monotonic() - self.last_request)
            if pause > 0: time.sleep(pause)
            self.last_request = time.monotonic()

    def translate(self, text):
        query = urlencode({"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text})
        for attempt in range(self.max_retries):
            limited = 0
            last_error = None
            for host in ("translate.google.com", "translate.googleapis.com"):
                try:
                    self.throttle()
                    with urlopen(f"https://{host}/translate_a/single?" + query, timeout=45) as response:
                        data = json.loads(response.read())
                    result = "".join(part[0] for part in data[0] if part and part[0])
                    if not result.strip(): raise ValueError("Empty translation")
                    return result
                except (URLError, ValueError, TypeError, IndexError, TimeoutError) as error:
                    last_error = error
                    if isinstance(error, HTTPError) and error.code == 429:
                        limited += 1
            if limited == 2:
                self.gtx_retry_disabled = True
                raise TranslationRateLimited("Both Google translation endpoints returned 429; retry on the next scheduled run")
            if attempt + 1 == self.max_retries:
                raise last_error
            time.sleep(min(60, 10 * 2 ** attempt))

    def translate_many(self, texts):
        try:
            return self.translate_rpc(texts)
        except (URLError, ValueError, TypeError, IndexError, KeyError, TimeoutError) as rpc_error:
            print(f"Google RPC batch deferred ({describe_rpc_error(rpc_error)}; {len(texts)} items)", flush=True)
            if self.gtx_retry_disabled:
                if isinstance(rpc_error, HTTPError) and rpc_error.code == 429:
                    raise TranslationRateLimited("Google RPC and GTX returned rate limits; retry next scheduled run") from rpc_error
                # A malformed item or another transport error is not evidence of RPC rate limiting.
                raise
            # Both implementations are Google Translate. Smaller GTX groups keep GET URLs bounded.
            results = []
            items = [(str(index), {"text": text}) for index, text in enumerate(texts)]
            for group in translation_batches(items, max_items=10, max_characters=3500):
                results.extend(self.translate_gtx_many([item[1]["text"] for item in group]))
            return results

    def translate_rpc(self, texts):
        requests_payload = [["MkEWBc", json.dumps([[text, "en", "zh-CN", True], [None]], ensure_ascii=False, separators=(",", ":")), None, str(index)]
                            for index, text in enumerate(texts)]
        body = urlencode({"f.req": json.dumps([requests_payload], ensure_ascii=False, separators=(",", ":"))}).encode("utf-8")
        request = Request(
            "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute?rpcids=MkEWBc&source-path=%2F&hl=en&soc-app=1&soc-platform=1&soc-device=1&rt=c",
            data=body, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "Mozilla/5.0", "Referer": "https://translate.google.com/"}, method="POST")
        self.throttle()
        with urlopen(request, timeout=60) as response:
            return parse_google_rpc(response.read().decode("utf-8"), len(texts))

    def translate_gtx_many(self, texts):
        if len(texts) == 1: return [self.translate(texts[0])]
        payload = google_batch_payload(texts)
        result = self.translate(payload)
        try:
            return parse_google_batch(result, len(texts))
        except ValueError:
            # Never guess where a paragraph ends if a provider changes delimiters.
            time.sleep(max(2, self.delay * 2))
            return [self.translate(text) for text in texts]


def parse_google_rpc(response, expected):
    results = {}
    for line in response.splitlines():
        line = line.strip()
        if not line.startswith("["): continue
        try: records = json.loads(line)
        except json.JSONDecodeError: continue
        if records and isinstance(records[0], str): records = [records]
        for record in records:
            if not isinstance(record, list) or len(record) < 7 or record[0:2] != ["wrb.fr", "MkEWBc"]:
                continue
            index = int(record[6])
            if index < 0 or index >= expected or index in results:
                raise ValueError("Invalid or duplicate Google RPC translation index")
            entry = None
            stage = "payload"
            try:
                data = json.loads(record[2])
                stage = "entry"
                entry = data[1][0][0]
                stage = "segments"
                segments = entry[5]
                if not isinstance(segments, list): raise ValueError("RPC segments are not a list")
                chunks = []
                for part in segments:
                    if not part: continue
                    if not isinstance(part, list) or (part[0] is not None and not isinstance(part[0], str)):
                        raise ValueError("RPC segment has no text field")
                    if part[0]: chunks.append(part[0])
                text = "".join(chunks)
                if not text.strip(): raise ValueError("Empty Google RPC translation")
                results[index] = text
            except (ValueError, TypeError, IndexError, KeyError) as error:
                # A bad result must not discard unrelated, correctly indexed translations.
                results[index] = None
                if isinstance(entry, list):
                    shape = ",".join(type(value).__name__ + (f":{len(value)}" if isinstance(value, (list, dict, str)) else "") for value in entry[:8])
                    shape = f"list:{len(entry)}[{shape}]"
                else: shape = type(entry).__name__
                print(f"Google RPC item pending (index={index}; stage={stage}; error={type(error).__name__}; entry_shape={shape})", flush=True)
    valid = sum(isinstance(value, str) for value in results.values())
    if not valid:
        raise ValueError("Google RPC response has no valid translations")
    if valid != expected:
        print(f"Google RPC retained {valid}/{expected} valid items; other indices remain pending", flush=True)
    return [results.get(index) for index in range(expected)]


def google_batch_payload(texts):
    return "\n\n".join(f"__VTSEG{index:05d}__\n{text}" for index, text in enumerate(texts)) + "\n\n__VTEND__"


def parse_google_batch(result, expected):
    result = re.sub(r"__\s*VTSEG\s*(\d{5})\s*__", lambda match: "__VTSEG" + match.group(1) + "__", result)
    result = re.sub(r"__\s*VTEND\s*__", "__VTEND__", result)
    markers = list(re.finditer(r"__VTSEG\d{5}__|__VTEND__", result))
    wanted = [f"__VTSEG{index:05d}__" for index in range(expected)] + ["__VTEND__"]
    if [match.group(0) for match in markers] != wanted or result[:markers[0].start()].strip() or result[markers[-1].end():].strip():
        raise ValueError("Google changed the batch delimiters; individual translation required")
    texts = [result[markers[index].end():markers[index + 1].start()].strip() for index in range(expected)]
    if not all(texts): raise ValueError("Empty Google batch translation")
    return texts


def translation_batches(items, max_items=32, max_characters=12000):
    batch = []
    characters = 0
    for item in items:
        length = len(item[1]["text"]) + 28  # Include the numbered segment delimiters in the request budget.
        if batch and (len(batch) >= max_items or characters + length > max_characters):
            yield batch
            batch = []
            characters = 0
        batch.append(item)
        characters += length
    if batch: yield batch


def translate_validated_batch(translator, batch):
    """Keep successful RPC items even when one item's optional fallback cannot run."""
    texts = [job["text"] for _, job in batch]
    results = translator.translate_many(texts)
    if len(results) != len(batch):
        raise ValueError("Translation batch length changed before cache write")
    restored = []
    retry_errors = (ValueError, URLError, TimeoutError, TypeError, IndexError, KeyError, TranslationRateLimited)
    for (key, job), result in zip(batch, results):
        try:
            if not isinstance(result, str): raise ValueError("Google RPC item is unavailable")
            restored.append((key, restore_translation(result, job["tokens"]), None))
            continue
        except ValueError as error:
            retry_error = error
        # Independent RPC context can repair a marker without using the separately limited GTX endpoint.
        try:
            single = translator.translate_rpc([job["text"]])
            if len(single) != 1: raise ValueError("Single RPC result length changed")
            restored.append((key, restore_translation(single[0], job["tokens"]), None))
            continue
        except retry_errors as error:
            retry_error = error
        if not translator.gtx_retry_disabled:
            try:
                single = translator.translate(job["text"])
                restored.append((key, restore_translation(single, job["tokens"]), None))
                continue
            except retry_errors as error:
                retry_error = error
                if isinstance(error, TranslationRateLimited): translator.gtx_retry_disabled = True
        # This error belongs only to the item: the main RPC batch succeeded and remains usable.
        restored.append((key, None, retry_error))
    return restored


def checkout_upstream_revision(source, revision):
    """Prepare an exact upstream revision without discarding local changes."""
    git = ["git", "-C", str(source)]
    if not source.exists() or (source.is_dir() and not any(source.iterdir())):
        subprocess.run(["git", "init", "--quiet", str(source)], check=True)
        subprocess.run([*git, "remote", "add", "origin", UPSTREAM_URL], check=True)
    root = subprocess.check_output([*git, "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(root).resolve() != source.resolve():
        raise ValueError(f"Upstream path must be the root of a Git worktree: {source}")
    changes = subprocess.check_output([*git, "status", "--porcelain", "--untracked-files=all", "--ignored"], text=True)
    if changes:
        raise ValueError(f"Pinned upstream requires a clean worktree: {source}")
    head = subprocess.run([*git, "rev-parse", "--verify", "--quiet", "HEAD"], capture_output=True, text=True)
    if head.stdout.strip() == revision:
        return revision
    available = subprocess.run([*git, "cat-file", "-t", revision], capture_output=True, text=True)
    if available.stdout.strip() != "commit":
        subprocess.run([*git, "fetch", "--depth", "1", "--no-tags", UPSTREAM_URL, revision], check=True)
    subprocess.run([*git, "checkout", "--quiet", "--detach", revision], check=True)
    head = subprocess.check_output([*git, "rev-parse", "--verify", "HEAD"], text=True).strip()
    if head != revision:
        raise ValueError(f"Expected upstream revision {revision}, got {head}")
    return head


def sync(args):
    source = Path(args.upstream).resolve()
    output = Path(args.output).resolve()
    state = ROOT / ".local"
    cache_input = cache_path(args.import_cache, ROOT) if args.import_cache else None
    cache_output = cache_path(args.export_cache, ROOT) if args.export_cache else None
    state.mkdir(exist_ok=True)
    if args.upstream_revision:
        commit = checkout_upstream_revision(source, args.upstream_revision)
    else:
        if not source.exists():
            subprocess.run(["git", "clone", "--depth", "1", UPSTREAM_URL, str(source)], check=True)
        elif not args.no_fetch:
            # Do not execute upstream build scripts or modify a locally edited checkout.
            subprocess.run(["git", "-C", str(source), "fetch", "origin", "main"], check=True)
            subprocess.run(["git", "-C", str(source), "merge", "--ff-only", "FETCH_HEAD"], check=True)
        commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    rendered_path = state / "rendered.json"
    subprocess.run(["node", str(ROOT / "scripts/build.mjs"), "--upstream", str(source), "--output", str(rendered_path)], check=True)
    rendered = json.loads(rendered_path.read_text(encoding="utf-8"))
    glossary = json.loads((ROOT / "glossary.json").read_text(encoding="utf-8"))
    version = hashlib.sha256(json.dumps(glossary, sort_keys=True).encode()).hexdigest()
    reviewed = load_reviewed_translations(ROOT / "translations/reviewed.json")
    # Display annotations never enter Google's v5 identity or stored HTML. Updating
    # terminology can therefore improve every cached page without retranslating it.
    terminology = TermAnnotator(json.loads((ROOT / "terminology.json").read_text(encoding="utf-8")))
    database = sqlite3.connect(state / "translations.sqlite3")
    database.execute("CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, source TEXT NOT NULL, html TEXT NOT NULL, translated_at TEXT NOT NULL)")
    if cache_input:
        imported = import_cache(database, cache_input, ROOT)
        print(f"Imported {imported} new or newer Google cache entries", flush=True)
    cache = dict(database.execute("SELECT key, html FROM translations"))
    known_ids = {page["id"] for page in rendered["pages"]}
    raw_navigation = rendered.get("navigation", [])
    pages = []
    jobs = {}
    active_google_keys = set()

    def register(original, tokens, page, target, title=False):
        key = translation_key(original, tokens, version)
        active_google_keys.add(key)
        seed = SEED_CASEFOLD.get(original.strip().casefold())
        if key in reviewed:
            value = restore_translation(reviewed[key], tokens)
        else:
            value = html.escape(seed) if seed else cache.get(key)
        if value is not None:
            if title:
                page["titleZh"] = BeautifulSoup(value, "html.parser").get_text()
            else:
                inject(target, value, reviewed_source=key in reviewed)
            page["translated"] += 1
        else:
            job = jobs.setdefault(key, {"text": original, "tokens": tokens, "targets": []})
            if target is not None: target["data-vt-key"] = key
            job["targets"].append((page, key, title))
        page["total"] += 1

    def inject(pair, value, *, reviewed_source=False):
        english = pair.find(class_="vt-en", recursive=False)
        chinese = copy.copy(english)
        chinese["class"] = [class_name for class_name in chinese.get("class", []) if class_name != "vt-en"] + ["vt-zh"]
        if chinese.has_attr("id"): del chinese["id"]
        chinese.clear()
        fragment = BeautifulSoup(value, "html.parser")
        for child in list(fragment.contents): chinese.append(child)
        terminology.annotate(english, chinese)
        if reviewed_source:
            chinese["data-vt-reviewed"] = "true"
        pair.append(chinese)
        pair["class"] = [class_name for class_name in pair.get("class", []) if class_name != "vt-pending"]

    for raw in rendered["pages"]:
        soup = BeautifulSoup(raw["html"], "html.parser")
        # The mirror is static: upstream scripts, embedded frames and event handlers are never published.
        for unsafe in list(soup.select("script,iframe,object,embed")): unsafe.decompose()
        for element in soup.find_all(True):
            for attribute in list(element.attrs):
                if attribute.lower().startswith("on"): del element.attrs[attribute]
            for attr in ("href", "src", "poster"):
                if element.has_attr(attr):
                    if str(element[attr]).lower().lstrip().startswith("javascript:"): del element[attr]
                    else:
                        address = route_link(element[attr], raw["id"], known_ids)
                        if address.startswith("/assets/"):
                            relative = unquote(urlsplit(address).path[len("/assets/"):])
                            asset = source / relative
                            if attr == "href" and asset.is_dir():
                                # Directory indexes are deliberately not exposed by nginx.
                                address = f"https://github.com/KhronosGroup/Vulkan-Tutorial/tree/{commit}/{quote(relative)}"
                            elif not asset.exists():
                                address = f"https://github.com/KhronosGroup/Vulkan-Tutorial/blob/{commit}/{quote(relative)}"
                                element["data-upstream-missing"] = "true"
                                element["title"] = "原文引用的资源在当前上游仓库中缺失；此链接指向原始来源以便核对。"
                                if element.name == "img":
                                    element["alt"] = element.get("alt", "") + "（上游资源缺失）"
                        element[attr] = address
        page = {key: raw[key] for key in ("id", "title", "group", "depth", "order", "license", "copyright")}
        section = page["id"].split("/")[0]
        page["group"] = GROUPS.get(section, "基础教程" if re.match(r"^\d{2}_|^conclusion$", section) else "更多专题")
        page["title"] = BeautifulSoup(page["title"], "html.parser").get_text()
        page.update({"titleZh": None, "translated": 0, "total": 0, "resolved": {},
                     "sourceUrl": f"https://github.com/KhronosGroup/Vulkan-Tutorial/blob/{commit}/en/{quote(page['id'])}.adoc",
                     "originalUrl": f"https://docs.vulkan.org/tutorial/latest/{quote(page['id'])}.html"})
        register(page["title"], {}, page, None, title=True)
        candidates = list(soup.select("p,h2,h3,h4,h5,h6,dt,td,th,div.title"))
        for block in candidates:
            if block.find_parent(["pre", "code", "script", "style"]) or block.select_one("p,h2,h3,h4,h5,h6,dt,td,th"):
                continue
            if not re.search(r"[A-Za-z]{3}", block.get_text()): continue
            # Translation is per short paragraph; oversized generated listings stay in English.
            if len(block.get_text()) > 4500: continue
            plain, tokens = prepare_translation(block, glossary)
            if not re.search(r"[A-Za-z]{3}", TOKEN_RE.sub("", plain)):
                local = local_term_translation(plain, tokens)
                if local is not None:
                    inject(wrap_bilingual_pair(soup, block), local)
                    page["translated"] += 1
                    page["total"] += 1
                continue
            pair = wrap_bilingual_pair(soup, block)
            register(plain, tokens, page, pair)
        page["html"] = str(soup)
        pages.append(page)

    del rendered
    gc.collect()

    output.mkdir(parents=True, exist_ok=True)
    def copy_changed(src, dst):
        original = Path(src)
        target = Path(dst)
        if not target.exists() or (original.stat().st_size, original.stat().st_mtime_ns) != (target.stat().st_size, target.stat().st_mtime_ns):
            shutil.copy2(src, dst)
        return dst
    for folder in ("images", "attachments"):
        destination = output / "assets" / folder
        shutil.copytree(source / folder, destination, dirs_exist_ok=True, copy_function=copy_changed,
                        ignore=shutil.ignore_patterns(".git", "node_modules", ".cxx", "build", "__pycache__", "venv"))
    shutil.copy2(source / "LICENSE", output / "assets" / "UPSTREAM-LICENSE.txt")
    shutil.copy2(source / "LICENSE", output / "LICENSE.txt")
    (output / "NOTICE.txt").write_text(
        "Vulkan Tutorial 非官方中文镜像 / Unofficial Chinese mirror\n"
        "Upstream: https://github.com/KhronosGroup/Vulkan-Tutorial\n"
        "Original tutorial: Alexander Overvoorde; Khronos Group and the upstream contributors.\n"
        "本镜像保留英文原文，新增中文机器翻译、术语提示和双语阅读。译文可能存在错误，请以英文原文为准。\n"
        "主体教程及其中文衍生内容采用 CC BY-SA 4.0：https://creativecommons.org/licenses/by-sa/4.0/\n"
        "Holochip Corporation 的扩展教程采用 Apache-2.0，中文翻译保留相同许可和原有署名。\n"
        "Holochip sections: ML_Inference, OpenXR_Vulkan_Spatial_Computing, AI_Assisted_Vulkan, Advanced_glTF, "
        "Advanced_Vulkan_Compute, Building_a_Simple_Engine, Synchronization.\n"
        "Arm Limited courses: CC BY-SA 4.0. 附件、代码和第三方素材遵循各自文件中保留的许可；不得将其统一视为 CC BY-SA。\n"
        "上游完整署名及许可说明：https://docs.vulkan.org/tutorial/latest/00_Introduction.html\n"
        "Vulkan is a registered trademark of the Khronos Group Inc. 本镜像并非 Khronos 官方发布。\n",
        encoding="utf-8")
    data = output / "data"
    now = utcnow()
    dirty = set(known_ids)

    def publish(status):
        database.commit()
        for page in pages:
            if page["id"] not in dirty: continue
            if page["resolved"]:
                soup = BeautifulSoup(page["html"], "html.parser")
                for pair in soup.select(".vt-pending[data-vt-key]"):
                    value = page["resolved"].get(pair["data-vt-key"])
                    if value is not None:
                        inject(pair, value)
                        del pair["data-vt-key"]
                page["html"] = str(soup)
                page["resolved"].clear()
            document = {key: value for key, value in page.items() if key != "resolved"}
            if page.get("titleZh"):
                original_title = BeautifulSoup(f'<span>{html.escape(page["title"])}</span>', "html.parser").span
                chinese_title = BeautifulSoup(f'<span>{html.escape(page["titleZh"])}</span>', "html.parser").span
                terminology.annotate(original_title, chinese_title)
                page["titleZh"] = document["titleZh"] = chinese_title.get_text()
                document["titleZhHtml"] = chinese_title.decode_contents()
            document["stats"] = {"translated": page["translated"], "total": page["total"]}
            atomic_json(data / "pages" / (page["id"] + ".json"), document)
        dirty.clear()
        atomic_json(data / "catalog.json", {
            "pages": [{key: value for key, value in page.items() if key not in ("html", "resolved", "sourceUrl", "originalUrl")} for page in pages],
            "navigation": navigation_metadata(raw_navigation, known_ids, cache, version, terminology),
            "upstream": {"commit": commit, "syncedAt": now, "url": UPSTREAM_URL[:-4], "branch": "main"},
            "translation": {"translated": sum(page["translated"] for page in pages), "total": sum(page["total"] for page in pages),
                            "provider": PROVIDER, "providerId": "google", "updatedAt": utcnow(), "status": status, "pending": len(jobs)},
            "license": {"default": "CC-BY-SA-4.0", "notice": "非官方中文镜像，机器翻译；Holochip 等扩展和附件可能采用不同许可，保留原文署名和许可说明。"}
        })
        if cache_output:
            export_cache(database, cache_output, active_google_keys, ROOT)

    publish("partial" if jobs else "complete")
    print(f"Published {len(pages)} pages; {sum(page['translated'] for page in pages)}/{sum(page['total'] for page in pages)} blocks translated; {len(jobs)} uncached requests", flush=True)
    if args.skip_translate or not jobs:
        database.close()
        return
    selected = list(jobs.items())
    if args.translate_limit > 0: selected = selected[:args.translate_limit]
    translator = GoogleTranslator(delay=args.delay)
    failures = 0
    failed_batches = 0
    successes = 0
    rate_limited = False
    started = time.monotonic()

    def execute(batch):
        return translate_validated_batch(translator, batch)

    # Keep at most workers requests in flight, so an interrupted run can stop promptly.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        iterator = iter(translation_batches(selected))
        active = {}
        for _ in range(args.workers):
            item = next(iterator, None)
            if item: active[executor.submit(execute, item)] = item
        while active:
            done, _ = concurrent.futures.wait(active, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                batch = active.pop(future)
                try:
                    for key, value, error in future.result():
                        if error is not None:
                            failures += 1
                            continue
                        job = jobs.pop(key)
                        database.execute("INSERT OR REPLACE INTO translations VALUES (?,?,?,?)", (key, job["text"], value, utcnow()))
                        cache[key] = value
                        for page, target_key, title in job["targets"]:
                            if title: page["titleZh"] = BeautifulSoup(value, "html.parser").get_text()
                            else: page["resolved"][target_key] = value
                            page["translated"] += 1
                            dirty.add(page["id"])
                        successes += 1
                except Exception as error:
                    failures += len(batch)
                    failed_batches += 1
                    if isinstance(error, TranslationRateLimited): rate_limited = True
                    print(f"Translation deferred ({type(error).__name__}); English retained", flush=True)
                if (successes + failures) % 25 < 20:
                    database.commit()
                    publish("running")
                    print(f"Translated {successes} new blocks, deferred {failures}; {len(jobs)} pending", flush=True)
                if not rate_limited and failed_batches < 2 and (not args.translation_seconds or time.monotonic() - started < args.translation_seconds):
                    item = next(iterator, None)
                    if item: active[executor.submit(execute, item)] = item
    database.commit()
    publish("partial" if jobs else "complete")
    database.close()
    print(f"Sync complete: {successes} new translations, {failures} deferred; {len(jobs)} pending", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", default=str(ROOT / ".local/upstream"))
    parser.add_argument("--output", default=str(ROOT / "public"))
    upstream_mode = parser.add_mutually_exclusive_group()
    upstream_mode.add_argument("--no-fetch", action="store_true", help="Use the current upstream checkout without fetching")
    upstream_mode.add_argument("--upstream-revision", metavar="SHA", help="Build the exact full lowercase upstream commit SHA")
    parser.add_argument("--skip-translate", action="store_true", help="Render the complete mirror using cached translations only")
    parser.add_argument("--translate-limit", type=int, default=0, help="Maximum new translation requests; 0 means all")
    parser.add_argument("--translation-seconds", type=int, default=0, help="Stop adding translation requests after this budget; 0 means unlimited")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between Google requests")
    parser.add_argument("--provider", choices=("google",), default="google")
    parser.add_argument("--import-cache", metavar="PATH", help="Import a reviewed Google v5 .jsonl cache inside the project")
    parser.add_argument("--export-cache", metavar="PATH", help="Export current Google v5 translations to a stable project .jsonl file at every checkpoint")
    args = parser.parse_args()
    if args.upstream_revision is not None and not re.fullmatch(r"[0-9a-f]{40}", args.upstream_revision):
        parser.error("--upstream-revision must be a full lowercase 40-digit commit SHA")
    if not 1 <= args.workers <= 4: parser.error("--workers must be 1..4")
    if args.translate_limit < 0 or args.translation_seconds < 0: parser.error("Limits must be nonnegative")
    sync(args)


if __name__ == "__main__":
    main()
