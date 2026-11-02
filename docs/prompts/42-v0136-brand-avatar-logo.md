# v0.13.6 需求快照：品牌化「智汇账」+ 头像大图 + Logo 多主题

## 需求背景

产品从「AI 记账管家」正式更名为「智汇账」，定位从"记账工具"抬到"AI 资产管家"。改名本身是字符串替换，但**侧边栏那块地方原来同时承载头像和名字**，一旦机械替换就会拼出「智汇账·心如小孩」这种低级错误——这是本轮唯一的红线。同时补两块体验短板：头像点开只能看 40px 小圆点，用户想保存原图没入口；品牌 Logo 只有一张，用户希望能在设置里挑风格。

## 核心 Prompt（下达给执行模型的要点）

1. 全局把「AI记账管家」替换成「智汇账」，网页 title 改「智汇账 - 您的 AI 资产管家」，PWA `manifest.json` 同步。
2. **渲染防呆（绝对红线）**：严禁把「智汇账」拼接在昵称或邮箱前面；侧边栏和个人中心必须严格读 `user.nickname`，为空才降级显示邮箱前缀。
3. 邮件发件人设成「智汇账 <小号邮箱>」，标题加【智汇账】前缀。
4. 点侧边栏/个人中心头像 → 全屏半透明 Lightbox，居中大图防溢出，点空白或右上角 X 关闭，底部「保存至本地」用 `<a download>`，文件名 `智汇账_我的头像.png`。
5. 「系统设置」新增「品牌图标主题」：读 `static/images/` 下 8 张图（`logo-main.png` + `logo-theme-1..7.png`），4×2 网格 48×48 圆角缩略图，选中绿色边框；选择存 localStorage，侧边栏与登录页动态替换，无缓存默认 `logo-main.png`；Favicon 与 PWA 固定 `logo-main.png`。
6. 设置弹窗 `.modal-body` 最大高度 75vh、`overflow-y:auto` + 自定义滚动条。
7. 真实浏览器详测：刷新后侧边栏只有纯净昵称、头像能点开与下载、Logo 切换刷新不丢、设置弹窗滚动顺滑；通过后精准 commit 并打 `v0.13.6-DEV` 标签（不覆盖 13.5）。

## 方案简述

- **侧边栏拆两段**：`#sidebar-brand`（Logo + 昵称）与 `.sidebar-tools`（头像 + 折叠钮）。`<span id="sidebar-brand-name">` 的 HTML 初值故意留空，只由 `updateSidebarUser()` 写；`displayName()` 的降级链是 `nickname → email 前缀 → 品牌名`，代码里没有任何字符串拼接品牌与昵称。头像从品牌行挪走的理由：140px 宽度塞不下 Logo + 长昵称 + 头像，昵称加 `ellipsis` 后反而更稳。
- **头像 Lightbox**：一个 `position:fixed inset:0` 的层，背板磨砂、面板与图片分别用 `92vw/92vh` 和 `86vw/68vh` 双限幅；关闭走统一 `data-avatar-lightbox-close` 标记 + Esc；`<a download>` 同源直下，没头像时禁用并给提示。个人中心的入口顺移到 Lightbox 的「个人中心」按钮。
- **Logo 主题**：`auth-v012.js` 里一组常量 + `applyBrandLogo()` 单点同步（侧边栏 `<img>` 与登录页 `<img>` 同源），`localStorage` 键 `ai-accounting-brand-logo`；`boot()` 与 `buildGate()` 各调一次，设置弹窗 `shown.bs.modal` 里重建网格。Favicon/PWA 图标固定 `static/icons/*`，不参与主题切换。
- **邮件**：`APP_BRAND_NAME` 常量 + `formataddr((品牌, MAIL_USER))`；主题 `【智汇账】注册验证码`。

## 踩坑结论

1. **Flask `--no-reload` 会缓存 Jinja 模板**：改完 `templates/*.html` 不重启进程，浏览器（以及 CDP 测试）拿到的还是旧 DOM。本次「X 按钮点不开」就是这个假象叠加真 Bug。
2. **X 按钮漏了关闭标记**：关闭逻辑统一挂在 `[data-avatar-lightbox-close]` 上，但最初只给背板加了这个属性，X 按钮没有 → 只有点空白能关。属性补齐后两路都通。
3. **`database.create_user()` 第二参是已哈希密码**：直接传明文建号，登录必然 401（表现为"邮箱或密码不正确，还可尝试 N 次"）。测试造号要 `generate_password_hash()`。
4. **CSS 类名对不上**：网格选中态在 CSS/JS 里是 `.is-active`，测试却断言 `.is-selected`，会报"默认选中 0 个"这种假红。
5. **Logo 原图偏大**：8 张单图 800KB~1.2MB，设置网格一次性拉 ~7MB。当前可接受，后续该出 128px 缩略图。
