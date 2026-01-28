# Changelog

## v0.1.1 (2026-01-27)

- 新增：日报与分区热榜支持 HTML 模板渲染为图片（Pornhub 黄黑风格），并在渲染失败时自动回退
- 新增：渲染相关配置 `delivery_mode` / `render_template_name` / `render_*`
- 修复：Beeg/MissAV/NoodleMagazine/Sex.com 信息源热榜抓取与封面链接，保证全量测试脚本可通过
- 调整：移除 Playwright 抓取；对 Cloudflare/反爬导致的 403 源（如 SpankBang/91Porn）改为提示配置代理或禁用，并在测试脚本中默认计为 Skipped（可用 `--fail-on-skipped` 强制失败）

## v0.1.0 (2026-01-27)

- 新增：`/dailyporn on|off` 在当前群聊开关日报
- 新增：`/dailyporn test` 手动触发一次日报（仅当前群聊）
- 新增：`/dailyporn <分区>` 返回该分区不同源热门封面+信息（3D / 2.5D / 真人）
- 新增：定时触发 `trigger_time`，按 star/views 计算推荐并推送到已开启群聊
- 新增：封面打码 `mosaic_level`、代理 `proxy`、各信息源开关 `sources.enable_*`
