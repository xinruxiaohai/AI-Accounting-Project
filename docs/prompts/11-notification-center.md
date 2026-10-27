# 11 · 通知中心与开发者发布台（Prompt 快照）

## 一、这一步要解决什么

比赛作品需要让评委看到「产品在迭代」，但页面里没有任何告知渠道：版本更新、维护提醒、使用技巧都只能写在文档里。

要做的不是硬编码一条公告，而是一套最小可用的通知系统：

1. 开发者能在后台发布带标题、富文本正文、可选配图的公告。
2. 前台右上角信封图标能收到，未读时显示红点。
3. 图片能上传，且被安全地存到 `static/uploads/`。
4. 通知内容是富文本，插入页面前必须清洗，不能成为 XSS 入口。

## 二、用户原始 Prompt（摘录）

> 加一个通知中心。后台 /admin 给开发者用：标题、正文（能加粗、列表、插图）、可选的封面图、发布时间可留空（留空就现在）。
> 前台点信封从右侧滑出面板，倒序展示，图文混排；没读过显示红点，打开面板就算已读。
> 正文是富文本，注意别直接把 HTML 塞进页面。

（Prompt 为要点摘录，非逐字。）

## 三、AI 给出的方案要点

### 数据层（database.py）

| 项 | 实现 |
| --- | --- |
| 表 | `notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, image_url TEXT, publish_date TEXT)` |
| 接口 | `list_notifications()` 按 `publish_date DESC, id DESC`；`create_notification()`；`delete_notification()` |
| 种子 | `_seed_notifications()` 在空表时插一条上线通知，保证首次打开不是空白 |
| 迁移 | 新表用 `CREATE TABLE IF NOT EXISTS`，老库直接补表，不动已有账目 |

### 后端（app.py）

- `GET/POST /api/notifications`、`DELETE /api/notifications/<id>`。
- `POST /api/upload`：限制 png/jpg/jpeg/gif/webp、≤5MB，用 uuid 重命名后存 `static/uploads/`，返回相对 URL。
- `GET /admin` 渲染发布台；`admin.html` 与主站共用主题变量，但结构独立，不往用户端塞管理逻辑。

### 前台

- 信封按钮 → 右侧滑出 `.notification-panel`，倒序列表；未读红点用 `localStorage["ai-accounting-notify-read"]` 存已读 id 数组。
- 正文用 `sanitizeNoticeHtml()`：`DOMParser` 解析后走标签/属性白名单（p、br、strong、em、u、ul、ol、li、a[href]、img[src]），其余节点丢弃，再 `innerHTML` 插入。
- 图片懒加载，面板打开时才请求；配图固定宽度，不撑破侧栏。

### 发布台

- `contenteditable` 工具栏（加粗/斜体/下划线/列表/插图），标题实时字数统计。
- 发布时间留空则用当前时间；右侧列表可删除，删完即从面板消失。

## 四、结果

- 通知表种子 1 条；发布 → 上传 1×1 PNG → 前台看到图文 → 删除，全链路接口自测通过。
- 富文本清洗后 `<script>`、`onerror` 等均被丢弃，页面 0 报错。
