# Google 翻译数据

`google.jsonl` 是可持久化的 Google 译文，文件首行为 schema/provider 元数据，其余条目按键稳定排序。请通过 `scripts/sync.py --import-cache ... --export-cache ...` 更新，不要提交 SQLite 数据库或其他服务的缓存。

`upstream.json` 记录已构建的官方 Git 提交和待译数，用于低频 Actions 判断是否需要继续工作。

译文遵循对应教程原文的许可，详见根目录 `THIRD_PARTY_NOTICES.md`。程序的 MIT 许可不覆盖这些译文。
