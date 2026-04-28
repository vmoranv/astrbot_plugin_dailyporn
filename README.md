# 鸡把鹿炸了

定时触发多源热榜（3D / 2.5D / 真人）作为推荐，并支持在群聊中开关日报、手动触发与分区查询。

## 指令

- `/dailyporn on`：在当前群聊开启日报
- `/dailyporn off`：在当前群聊关闭日报
- `/dailyporn test`：手动触发一次日报（仅当前群聊）
- `/dailyporn <分区>`：返回对应分区不同源最热门的封面 + 信息（分区：3D / 2.5D / 真人）
- `/dailyporn hqporner|missav`：手动触发该源热榜（不参与日报排名）

## 配置

在管理面板中配置：

- `trigger_time`：日报触发时间（HH:MM）
- `mosaic_level`：封面打码程度
- `proxy`：代理地址
- `delivery_mode`：发送方式（`html_image`/`plain`）
- `render_backend`：渲染后端（`remote`/`local`）
- `render_template_name`：HTML 渲染模板
- `render_send_mode`：渲染图片发送方式（`file`/`url`/`base64`）
- `sources.*`：是否启用指定源（bool）

## 常见问题

### 中文渲染成方块/乱码

如果使用 `render_backend=remote`（HTML 截图）时中文显示为方块，通常是「实际执行渲染的环境」缺少中文字体或字体回退没有命中。

- 方案 1：改用 `render_backend=local`（PIL 本地渲染，不依赖浏览器字体回退）
- 方案 2：在渲染环境里安装中文字体并刷新缓存（示例：`fonts-wqy-microhei` / `fonts-noto-cjk`，然后执行 `fc-cache -f`）
