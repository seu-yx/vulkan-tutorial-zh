# 维护指南

本文件面向维护者和代码代理。项目是 Khronos Vulkan Tutorial 的非官方中文镜像，英文内容直接使用上游源码。修改阅读器和翻译流程时，请保留英文段落、代码、API 标识符、链接与逐页许可。可公开的变更通过普通 Git 分支和 Pull Request 提交。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `public/` | 静态阅读器。构建时生成 `data/`、`assets/` 和许可副本 |
| `scripts/build.mjs` | 将上游 AsciiDoc 渲染为页面，读取官方导航层级 |
| `scripts/sync.py`、`scripts/translation_cache.py` | 生成双语页面，缓存和续译 Google 基础译文 |
| `scripts/terminology.py`、`terminology.json`、`terminology.schema.json` | 术语的显示、原文提示与别名校正 |
| `scripts/polish.py` | 生成 Copilot 对照预览，续跑校订队列，应用有效校订缓存 |
| `scripts/ci_gate.py`、`.github/workflows/` | 判断是否需要同步，安排翻译、检查和 Pages 发布 |
| `translations/` | 随 Git 保留的译文、校订结果和上游状态 |
| `tests/`、`deploy/` | 回归与站点完整性检查、可选的 Linux 部署示例 |

`.local/` 存放上游检出、渲染缓存、SQLite 数据和本地报告。提交时只纳入相关源码、文档和规定的翻译缓存。将凭据、私钥、SQLite、依赖及构建产物留在本机。文本换行遵守 `.gitattributes`，尤其注意 JSON、YAML 和 Markdown 使用 LF。

## 本地构建与检查

需要 Git、Node.js 18+、Python 3.10+。首次安装会下载公开的上游资源和构建依赖，同时导入已有的翻译缓存。

```sh
git clone https://github.com/seu-yx/vulkan-tutorial-zh.git
cd vulkan-tutorial-zh
python scripts/local.py --setup --serve
```

打开 `http://127.0.0.1:8080/`。Windows 可用 `py` 代替 `python`。已完成构建后，运行 `python scripts/local.py` 即可预览，可以加 `--port 9000`。通过本地 HTTP 服务阅读已生成的站点，以便浏览器正常加载 JSON。

- `python scripts/local.py --sync` 更新上游并用已有缓存重建。
- `python scripts/local.py --sync --no-fetch --serve` 使用本地上游检出重建并预览。
- 本地构建会应用现有有效校订，联网续译和 Copilot 预览采用下文的独立入口。

使用项目虚拟环境执行与改动相关的检查。Windows 将 `.venv/bin/python` 换成 `.venv/Scripts/python.exe`。

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python tests/check_site.py
.venv/bin/python scripts/audit_terminology.py
```

后两项需要先构建站点。若修改高亮语言、主题或打包入口，运行 `npm ci --ignore-scripts` 和 `npm run build:syntax`，一并提交生成的 `public/syntax.js` 和 `public/syntax.css`。CI 也会重建高亮资源。

## 上游同步、Google 译文与 Pages

[Pages 工作流](.github/workflows/pages.yml)按 UTC 20:23（北京时间次日 04:23）每日触发，也支持 `main` 上匹配路径的 push 和手动运行。工作流使用 `git ls-remote` 比较官方 `main`。有上游变更、Google 待译、已过冷却期的校订积压，或需要重建时，才进入构建。渲染使用 Git 检出与 Actions 缓存。

Google 续译默认单并发，文本块上限 500，时间预算约 10 分钟，请求间隔至少 2 秒。手动运行可通过 `translate_limit` 调低上限。译文尚不可用时保留英文，后续运行再续译。

- `translations/google.jsonl` 是长期保留且按键排序的 Google 译文缓存。键包含原文、受保护的代码或链接、术语保护表和缓存版本。参见 [翻译数据说明](translations/README.md)。
- `translations/upstream.json` 记录已构建的上游提交和待译数。
- CI 在检查通过后提交更新的缓存和状态，以 fast-forward 推送到 `main`。若远端已有更新，先保留校订产物，再从最新 `main` 重跑，避免发布旧构建。

手动续译时使用已安装依赖的虚拟环境。下面的命令会调用 Google。

```sh
.venv/bin/python scripts/sync.py \
  --import-cache translations/google.jsonl \
  --export-cache translations/google.jsonl \
  --provider google --workers 1 --delay 2 \
  --translate-limit 500 --translation-seconds 600
.venv/bin/python scripts/polish.py --apply
.venv/bin/python scripts/ci_gate.py --record
```

`scripts/sync.py --skip-translate` 复用缓存构建。`--no-fetch` 使用已有上游检出。`scripts/sync.py` 中的 `SEED` 用于校正常见标题。

要将 Fork 部署到 GitHub Pages，在 **Settings → Pages → Build and deployment** 选择 **GitHub Actions**，启用 **Sync Vulkan tutorial and publish Pages** 并在 `main` 手动运行一次，首次运行可勾选 `force_build`。Pages 产物来自 `public/`，阅读器兼容仓库子路径和自定义域名根路径。若 GitHub 因仓库长期无活动暂停定时工作流，可在 Actions 重新启用。

## Copilot 校订与进度恢复

Google 构建完成后，自动校订优先处理新增或变更的章节，其余时间继续处理存量。每次请求只校订一整篇，几篇之间串行处理。每轮最多 5 篇，手动运行可设 `polish_limit` 为 1–10 篇，仍受时间预算约束。仓库 Actions 变量 `POLISH_ENABLED=false` 可暂停新请求。

Copilot 按章节顺序对照英文和当前译文，只修明显不通顺或不准确的局部。返回的改动仍按文本块校验，保护术语、代码、链接、数字和关键条件。校验失败的改动保留原译。额度、权限或服务错误会暂停推理，已有有效校订仍可随站点发布。使用 GitHub 提供的 `GITHUB_TOKEN` 和 `copilot-requests: write`。个人仓库按所有者的 Copilot 额度计量，超额用量由账户预算控制。[GitHub 预算说明](https://docs.github.com/en/billing/how-tos/set-up-budgets)

- `translations/polish.json` 保存有效校订和已确认无需改动的结果。原文、基础译文或受保护内容变化时，对应旧记录自动失效。
- `translations/polish-state.json` 按章节内容记录完成进度、失败和冷却状态。英文或基础译文变化的章节重新排队。旧版按段的校订仍有效，但整篇校订以新的章节记录为准。
- **polish-progress-<运行编号>** 产物包含对照报告和校订缓存。Git 写回失败时，可按记录键核对并恢复有效条目。

人工抽查时，运行整章预览工作流，选择 `main`，填写章节 ID（例如 `01_Overview`，也可从 URL 的 `page=` 参数取得）。模型留空使用 Copilot Auto。该预览会消耗 Copilot 额度。下载 **polish-preview-<运行编号>**，参照 `review.json` 比对英文、译文和校订稿，根据 `cache_key` 将采纳的结果合并到最新的 `translations/polish.json`。[Polish translations preview](.github/workflows/polish.yml)

## 扩展术语

日常补充术语请编辑 `terminology.json` 的 `terms` 数组。下面以 `present mode` 为例。

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

## 反馈与许可

翻译问题请提供章节链接、英文原文、现有译文和建议译文。阅读器和构建工具采用仓库的 [MIT 许可](LICENSE)。教程译文、扩展与素材沿用对应上游许可，参见 [第三方内容说明](THIRD_PARTY_NOTICES.md)、[上游许可](LICENSES/UPSTREAM-LICENSE.txt)和各章原始版权声明。Vulkan 是 Khronos 的注册商标。本项目与 Khronos 无官方隶属关系。
