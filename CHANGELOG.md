# Changelog

## v0.1.10 (2026-01-28)

- 修复：封面缓存目录路径拼接，兼容 get_astrbot_data_path 返回 str/Path

## v0.1.9 (2026-01-28)

- 修复：部分环境 get_astrbot_data_path 返回字符串导致的路径拼接异常

## v0.1.8 (2026-01-28)

- 修复：XFreeHD 详情页观看数解析（使用页面 big-views 区块）
- 修复：封面缓存目录路径在部分环境下的 Path 处理

## v0.1.7 (2026-01-28)

- 新增：渲染图片发送方式配置（file/url/base64）
- 调整：HTML 渲染根据发送方式返回 URL/文件/BASE64

## v0.1.6 (2026-01-28)

- 调整：HTML 渲染图片改为 URL 发送，降低本地上传带宽占用
- 调整：封面缓存目录迁移至 data/plugin_data/astrbot_plugin_dailyporn/cache/covers

## v0.1.5 (2026-01-28)

- 优化：日报渲染完成后用 PIL 压缩图片，降低发送体积
- 调整: 分离fallback渲染模板到templates里

## v0.1.4 (2026-01-28)

- 修复：xvideos 详情页视图/投票解析与分月榜抓取
- 修复：hentaigem 改为 top-rated 今日榜并补全投票解析
- 调整：日报推荐排序日志输出位置（INFO 级别）

## v0.1.3 (2026-01-28)

- 调整：排行榜改为 views*0.7 + star*0.3 加权
- 调整：HQPorner/MissAV 仅支持手动触发，日报与测试默认排除
- 调整：XVideos/XHamster/XNXX/Porntrex/NoodleMagazine/HentaiGem/Rule34Video 采用指定日榜/筛选逻辑并随机取样
- 修复：3DPorn/EPorner/Rule34Video/NoodleMagazine/XVideos/XXXPorn 等详情页统计解析
- 增强：日报渲染前输出最终推荐日志，便于排查渲染失败
- 文档：补充手动触发命令说明

## v0.1.2 (2026-01-28)

- 移除：Smutba 信息源（非视频站点，不符合“视频日报”定位）
- 调整：HQPorner/MissAV 默认关闭，且仅支持手动触发（不参与定时推荐）
- 修复: 一堆源抓取信息逻辑问题

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
