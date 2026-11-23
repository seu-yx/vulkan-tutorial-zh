# Vulkan Tutorial 中文镜像

跟踪 [Khronos 官方 Vulkan Tutorial](https://github.com/KhronosGroup/Vulkan-Tutorial) 的非官方中文阅读站：保留英文原文，使用 Google 增量翻译，支持双语对照、术语提示和本地部署。

**在线阅读：[seu-yx.github.io/vulkan-tutorial-zh](https://seu-yx.github.io/vulkan-tutorial-zh/)**

## 功能

- 中文、English、逐段中英对照，保留代码和 Vulkan API 名称。
- 专业术语悬浮查看英文，也可切换为保留英文术语。
- 章节搜索、页内目录、代码复制、深浅色主题、手机阅读。
- GitHub 风格代码高亮，随深浅色主题切换，保留代码原文及复制功能。
- 展示原文、固定版本源码链接、翻译进度及逐页许可。
- 从官方 Git 提交增量更新，按段落复用 Google 译文，未译内容保留英文。

这不是 Khronos 官方中文发布。机器翻译可能存在错误，请结合英文原文阅读；欢迎通过 Issue 或 Pull Request 改善术语和翻译。

## 本地使用

需要 Git、Node.js 18+、Python 3.10+。首次安装会下载上游公开资源并安装构建依赖。

```sh
git clone https://github.com/seu-yx/vulkan-tutorial-zh.git
cd vulkan-tutorial-zh
python scripts/local.py --setup --serve
```

浏览器打开 `http://127.0.0.1:8080/`。Windows 如没有 `python` 命令，可将它替换为 `py`。首次构建导入仓库中的既有 Google 译文，不会重新发起全站翻译。

之后直接运行：

```sh
python scripts/local.py
```

可使用 `--port 9000` 更改端口。已经生成的站点可离线阅读；请通过本地 HTTP 服务打开，直接双击 HTML 会受浏览器对 JSON 请求的限制。

## GitHub Pages 部署

1. Fork 本仓库。
2. 在仓库 **Settings → Pages → Build and deployment** 中选择 **GitHub Actions**。
3. 在 **Actions → Sync Vulkan tutorial and publish Pages** 中启用工作流，并手动运行一次；首次运行勾选 `force_build`。

发布地址通常为 `https://<用户名>.github.io/<仓库名>/`。前端同时兼容仓库子路径和自定义域名根路径。Actions 只发布 `public/`，不会发布项目密钥、SQLite 数据库或本地环境。

## 同步与翻译如何运行

默认每天 **UTC 20:23，即北京时间次日 04:23** 触发一次。GitHub 定时任务可能延迟；也可以随时使用 Actions 的 **Run workflow** 手动触发。

流程如下：

1. `git ls-remote` 比较官方 `main` 分支提交 SHA。
2. 没有新提交、没有待译段落时直接结束，不构建、不请求翻译。
3. 有变化时通过 Git 获取增量更新，复用缓存的上游源码和渲染结果。
4. 导入 `translations/google.jsonl`，每次最多翻译 **500 个新段落、约 10 分钟、单并发**，请求间隔至少 2 秒。
5. 将有效新增译文和上游提交写回 Git，再将生成的静态网站发布到 Pages。

`translations/google.jsonl` 是稳定排序、可版本管理的译文存储；每个条目由原文、保护的代码/链接、术语表和 Google 缓存版本共同标识。它是可持久化的数据来源，不依赖可能被清理的 Actions 缓存。

> GitHub 公共仓库长期无活动时可能停用定时工作流；如发现不再更新，请在 Actions 中重新启用。可手动运行以补齐待译内容。

## 手动构建或翻译

`scripts/local.py --sync` 刷新官方源码并使用已有译文重建。需要运行翻译时，使用安装好的虚拟环境：

```sh
# Linux/macOS；Windows 将 .venv/bin/python 改为 .venv/Scripts/python.exe
.venv/bin/python scripts/sync.py \
  --import-cache translations/google.jsonl \
  --export-cache translations/google.jsonl \
  --provider google --workers 1 --delay 2 \
  --translate-limit 500 --translation-seconds 600
.venv/bin/python scripts/ci_gate.py --record
```

`--skip-translate` 只构建，`--no-fetch` 使用已有上游，`--translate-limit` 限制新段落数。`scripts/sync.py` 中的 `SEED` 校正常见标题。

## 扩展术语

日常补充术语请编辑 `terminology.json` 的 `terms` 数组。例如：

```json
{
  "english": "present mode",
  "chinese": "呈现模式",
  "variants": ["present modes"],
  "aliases": ["呈现模式", "演示模式", "展示模式"],
  "normalize": true
}
```

`english` 是悬浮提示和“保留英文术语”使用的名称；`chinese` 是推荐中文。`variants` 明确列出英文复数或其他形式，英文大小写和换行自动兼容。`aliases` 是现有译文中的说法；默认只加标注，设置 `normalize: true` 才统一为推荐中文。

`exactAliases` 仅在整个英文段落或标题恰好是该术语时使用。例如 `presentation` 的 `"exactAliases": ["介绍"]` 可以修正单独的标题，同时保留其他段落中普通“介绍”的含义。

可选 `context` 限制歧义词的使用范围：`{"requireAny": ["swapchain", "surface"], "excludeAny": ["demo"]}` 表示英文段落须包含至少一个前置词，且不能包含排除词。代码不作为匹配文本。匹配优先使用长术语，只有原英文中出现对应术语才处理中文别名；存在歧义或无法安全合并的内联格式会保留原文。

`terminology.schema.json` 为支持 JSON Schema 的编辑器提供字段提示；构建时也会验证配置。修改后运行 `python scripts/local.py --sync --no-fetch --serve` 预览，或直接提交到 GitHub，由 Actions 重建发布。

运行 `python scripts/audit_terminology.py` 可扫描全部已构建页面，将标注覆盖情况和待人工核对的例句输出到 `.local/terminology-audit-current.json`；该命令不会修改网页或翻译缓存。

此配置只处理生成页面，保留英文、代码和 Google 译文缓存，无需重新翻译全站。`glossary.json` 是兼容历史缓存的翻译保护表，其整体哈希参与缓存身份；日常扩展使用 `terminology.json`。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `public/` | 静态阅读器；生成的数据和上游素材不提交到主分支 |
| `scripts/` | AsciiDoc 渲染、Google 翻译、缓存导入导出、本地启动与 Git 检查 |
| `translations/` | 可持久化的 Google 译文及已同步的上游版本 |
| `terminology.json` / `terminology.schema.json` | 可扩展的术语显示、译法别名、英文变体和上下文规则 |
| `.github/workflows/pages.yml` | 低频同步、测试、续译和 Pages 发布 |
| `tests/` | 内容完整性、缓存隔离、链接、代码保护及本地启动检查 |
| `deploy/` | 可选的自建 Linux 服务器部署示例 |

## 贡献与许可

代码高亮资源随站点自托管，采用 GitHub 浅色和深色配色。修改高亮语言或主题后，运行 `npm ci --ignore-scripts` 和 `npm run build:syntax`，并提交更新后的 `public/syntax.js`、`public/syntax.css`；Actions 发布时也会重新构建这些资源。

请在 Issue 中提供章节链接、原文、现有译文和建议译文。代码贡献可通过 Pull Request 提交；提交前运行：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python tests/check_site.py
```

本站自编阅读器和构建工具采用 [MIT License](LICENSE)。官方教程及中文衍生内容保留对应上游许可：主体 **CC BY-SA 4.0**，部分 Holochip 扩展 **Apache-2.0**；附件和第三方素材还可能采用 CC0、MIT 等许可。MIT 不覆盖这些教程内容及素材。详见 [第三方内容说明](THIRD_PARTY_NOTICES.md)、[上游许可](LICENSES/UPSTREAM-LICENSE.txt) 和各章原始版权声明。

Vulkan 是 Khronos 的注册商标。本项目与 Khronos 不存在官方隶属关系。
