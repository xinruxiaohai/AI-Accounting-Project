# 47 · v0.15.2 实体图标体系（账户 / 分类）· Agent F

> 交付对象：**Agent F**（沿用原 F 模块，不新开代号）。F 原任务「六主题 + 图标库 8→40+ + 可访问性」中的**应用图标部分作废**（55 款已有，够用），本轮只做「账户 + 分类」实体图标，六主题/可访问性顺带微调。
> 背景：D / G / F 三个并行 Agent 额度耗尽未交付；应用图标（侧边栏 55 款品牌底纹、PWA 图标）**已经够用，明确不要再动**。
> 用户原话：「生成新的账户还有分类图标就好了，原有的大部分太简陋了，可以直接使用微信或者支付宝的 logo。」

---

## 一、开工前必读

1. 先读 `docs/HANDOFF.md` 的「二、并行 Agent 协作声明」（白名单 / 串行 / 禁自行 bump 版本 / 测试隔离 / git 只 add 自己文件）。
2. 你是 **Agent F**，与 A（移动端交互重构）、B（AI 文本识别）、D（AI 图像识别）可能同时在跑。**冲突红线见第二节**。

## 二、白名单与红线

允许改：
- `static/script.js` —— **仅**图标区（约 8090–8240 行：`ICON_PATHS` / `CATEGORY_ICON_RULES` / `ACCOUNT_ICON_RULES` / `CATEGORY_TONES` / `ICON_ACCOUNT_COLORS` / `iconKeyOf` / `iconToneOf` / `iconVectorSvg` / `entityIconHtml` / `iconImgHtml`），以及**新增**的映射函数；其它区域一行都不许动。
- 新增 `static/icons/entity/**`（图标 SVG + `SOURCES.md`）。
- 新增 `static/entity-icons-v0152.css`（新样式全部写这里）。
- `templates/index.html` —— **只允许**在现有 CSS 引入块末尾加一行 `<link rel="stylesheet" href="/static/entity-icons-v0152.css?v=0.15">`，其它不动。

绝对禁止：
- `ai_service.py`、`app.py`、`database.py`、`invest_*.py`、表结构、任何 SQL。
- `static/icons/brand-*.svg`（48 个品牌底纹）、`static/images/logo-theme-*.png`（7 张应用图标）、侧边栏 55 款 logo 选择器、`manifest.json`、`service-worker.js`、PWA 图标 —— **这些就是"应用图标"，已明确不改**。
- 版本号（`APP_VERSION_FALLBACK` / 模板 `?v=` / `CACHE_NAME` / `ASSET_VERSION`）—— 统一由架构侧最后 bump。
- `docs/HANDOFF.md`、`git push`、`git add -A`。
- 用 AI 生图（ImageGen）做图标：logo 必须矢量、可无损缩放、离线可用。
- A 本轮新增的 `static/mobile-stack-v0152.js` / `.css`（移动端二级页）与你无关，**不要动、不要删、不要"顺手重构"**。

## 三、现状（已核实，含行号）

| 位置 | 现状 | 问题 |
|---|---|---|
| `static/script.js:8097` | `ICON_PATHS` 共 **21** 个 key，24×24 **单色描边** `<path>` | 简陋、单色、风格像线稿 |
| `ICON_PATHS.alipay` | 是 `<text>支</text>` 一个字 | 不是 logo |
| `ICON_PATHS.wechat` | 一个对话气泡 + 3 个点 | 不是微信 logo |
| `CATEGORY_ICON_RULES` | 44 条中文关键词 → key | 长尾分类全落到 `tag` |
| `ACCOUNT_ICON_RULES` | 11 条 | 「招商银行」「花呗」「京东」等未覆盖 |
| `CATEGORY_TONES` | 只 12 个 key 有配色 | 新 key 会掉到灰 `tag` |
| `ICON_ACCOUNT_COLORS` | 8 个品牌色 | 同上 |
| `entityIconHtml(kind,name,size,variant)` `script.js:8181` | 唯一出口：圆形底 + 内联 SVG，`variant="solid"` 用于账户 | 签名保持不变，只换内部实现 |
| `iconImgHtml` `script.js:8198` | 裸图标 | 同上 |
| 调用点 | `script.js:1382`（统计 Top 分类 42px）、`1684`（分类管理行 22px）、`2077`（资产页账户 34px solid）、`4186`（AI 结果气泡 38px）、`11288`（账单分类 26px）、`11293`（账单账户 26px）、`invest-v0133.js:14` 注释 | 7 处，全部走 `entityIconHtml` |
| 样式 | `style.css:9057 .entity-badge`；`9066 .entity-badge .entity-icon-svg{width:58%}`；`9071 .entity-badge img{width:100%;height:100%;object-fit:cover}`；`9077 .entity-badge.has-image`；`9481 .cat-item-icon .entity-badge` | 58% 留白是给描边图标的；logo 铺满才好看 |
| 用户自定义图标 | `iconFor(kind,name)` → `user_icon_settings` 表 | **优先级必须保留：用户上传图 > 内置图标** |
| 暗色 | `v0151-theme.css:18 [data-theme="dark"]`，另有 `midnight` 深色主题 | 浅色圆底（如 `#fff1e6`）在深色下要压暗 |

## 四、图标资源获取（已实测，不要重新摸索）

Iconify API 在本机可达，直连即可下载：
`curl -s https://api.iconify.design/{prefix}/{name}.svg`

**实测 200（可直接用）**
- 微信：`thesvg-color/wechat`（官方绿 `#07c160`，真 logo 双气泡）
- 支付宝：`thesvg-color/alipay`（官方蓝 `#1677ff`，真 logo 方形支字标）
- 银联 / 云闪付：`logos/unionpay`
- 卡组织：`thesvg-color/visa`、`thesvg-color/mastercard`、`logos/visa`、`logos/mastercard`
- 美团：`thesvg-color/meituan`；PayPal：`thesvg-color/paypal`
- 单色品牌：`simple-icons/tiktok`、`simple-icons/qq`、`simple-icons/visa`、`simple-icons/mastercard`
- 彩色分类集（多色、风格统一，优先选一套，不要混三套）：`twemoji/*`、`noto/*`、`fluent-emoji-flat/*`（如 `twemoji/pizza`、`noto/pizza`、`fluent-emoji-flat/hamburger`）

**实测 404（别再试）**：`logos/wechat`、`logos/wechat-pay`、`logos/alipay`、`thesvg-color/unionpay`、`thesvg-color/jd`、`thesvg-color/douyin`、`thesvg-color/wechat-pay`、`simple-icons/jd`、`simple-icons/douyin`、`simple-icons/unionpay`、`simple-icons/icbc`。

规则：
1. 全部**落地成本地 SVG 文件** `static/icons/entity/<key>.svg`，运行时不外链（PWA 离线 + 隐私）。
2. 归一化：去掉 `width`/`height` 属性、保留 `viewBox`（统一 `0 0 24 24`，不够就缩放 path 或用 `viewBox` 原值不改）、确保根 `<svg>` 带 `xmlns`、单文件 < 8KB。
3. 品牌 logo 找不到官方矢量的（京东、抖音、各银行行标），**不要硬画**：用同色系通用图标（钱包/银行卡/银行）+ 品牌主色，允许近似，禁止乱造。
4. 写 `static/icons/entity/SOURCES.md`：`key ← 上游 prefix:name ← 许可证`，并注明「品牌 logo 仅用于用户识别账户类型」。
5. 分类图标（多色 emoji 集）与账户（品牌 logo）视觉上不需要同源，但**同类之间**必须同源。

## 五、要做的事

### 5.1 账户图标（≥ 14 个 key，真 logo 优先）
`wechat`（微信零钱/微信支付）、`alipay`（支付宝/余额宝）、`unionpay`（云闪付/银联）、`bank`（储蓄卡/银行）、`creditcard`（信用卡）、`cash`（现金）、`wallet`（钱包/其他）、`coin`（理财/零钱通）、`fund`（基金）、`stock`（证券/股票）、`insurance`（保险/公积金/医保）、`meituan`（美团）、`paypal`、`qq`（QQ 钱包）、`tiktok`（抖音钱包）。
`ACCOUNT_ICON_RULES` 补齐关键词：招商/工商/建设/农业/中国银行/交通银行/邮储 → `bank`；花呗/借呗/白条 → `creditcard`；余额宝/零钱通/朝朝盈 → `coin`；证券/股票/场内 → `stock`；公积金/医保/社保 → `insurance`；京东 → `wallet`；美团/饿了么 → `meituan`。

### 5.2 分类图标（≥ 40 个 key）
覆盖并落规则：餐饮、早餐、午餐、晚餐、外卖、咖啡、奶茶、零食、生鲜、超市、交通、打车、地铁、公交、加油、停车、购物、服饰、数码、居住、房租、水电、燃气、物业、娱乐、游戏、电影、旅游、住宿、医疗、药品、健身、运动、学习、书籍、课程、人情、礼物、红包、工资、奖金、报销、投资、基金、退款、转账、手续费、税费、保险、宠物、母婴、美容、汽车、维修、装修、订阅会员、通讯话费、烟酒、捐赠（≥ 40 即可，优先覆盖用户库里真实存在的分类名）。

### 5.3 代码改造（保持签名，只换实现）
- 新增 `ENTITY_ICON_FILES = { account: {key: file}, category: {key: file} }` 与 `iconSrcOf(kind, key)`。
- `entityIconHtml(kind,name,size,variant)` 内部优先级：**用户上传图（`iconFor`）> 本地 SVG 文件 > 旧内联 SVG 兜底**（`ICON_PATHS` 保留作兜底，不要删，防止文件缺失白屏）。
- `entityIconHtml` 输出 `<img>` 时给 `.entity-badge` 加 `has-logo` 类（**不要复用 `has-image`**，那是用户上传图，`object-fit:cover` 会裁掉 logo）。
- `iconImgHtml` 同步走 `iconSrcOf`。
- `CATEGORY_TONES` / `ICON_ACCOUNT_COLORS` 补齐所有新 key，禁止回落成灰。
- `iconKeyOf` 保持返回 key 字符串的契约不变（`categories.icon_key` 语义不变，**不改表、不改迁移**）。

### 5.4 新增样式（只写 `static/entity-icons-v0152.css`）
- `.entity-badge.has-logo img { width:76%; height:76%; object-fit:contain; }`（logo 有留白，别铺满，别 cover）。
- 账户 `variant="solid"` + 真 logo 时**去掉品牌色圆底**：`.entity-badge.is-solid.has-logo { background:#fff !important; box-shadow: inset 0 0 0 1px rgba(15,23,42,.08); }`（logo 自带品牌色，再叠绿底会糊）。
- 深色/午夜主题压暗浅色底：`[data-theme="dark"] .entity-badge:not(.has-logo), [data-theme="midnight"] .entity-badge:not(.has-logo) { filter: brightness(.92) saturate(.9); }` —— 先按 `v0151-theme.css:18` 的实际选择器核对，别瞎写。
- 22px 小尺寸下 logo 细节会糊：`size <= 24` 时用 84% 铺满（`has-logo.is-tiny`）。

## 六、验收（必须给出数字，不接受"看起来好了"）

1. **断言脚本**（放 `D:\Project\temp\entity-icons\`，用 `venv` Python + `requests`/`urllib`）：
   - `ENTITY_ICON_FILES` 账户 key ≥ 14、分类 key ≥ 40，且每个对应文件存在、`<svg` 开头、含 `viewBox`、< 8KB → 逐条断言。
   - 22 个真实分类名 + 12 个真实账户名走 `iconKeyOf`，**100% 命中非兜底 key**（列出未命中清单）。
   - 断言旧 `ICON_PATHS` 21 个 key 仍然存在（兜底没被删）。
2. **真实浏览器 CDP**（`D:\Project\temp\entity-icons\cdp.mjs`，无头 Chrome + `Emulation.setDeviceMetricsOverride` 1440×900 与 390×844）：
   - 7 个渲染位逐一截图：首页卡片、首页流水、账单列表、资产页账户行、分类管理行、记账弹窗分类网格、统计 Top 分类。
   - Network 断言：`/static/icons/entity/*` **零 404**、页面 **零 console error**。
   - 尺寸断言：22/26/34/38/42 五个尺寸下 `<img>` 的 `naturalWidth>0`、渲染宽高差 ≤ 1px、不被裁切（`object-fit:contain` 生效）。
3. **数据零污染**：`records.db` 测前测后 md5 一致；测试库用 `ZHZ_SQLITE_PATH` 指向副本。
4. **测试账号铁律**：只用 `test@test.com`（本地 uid 93）与 `temp_cdp_v0140@example.com`（uid 90），JWT `sub` 必须是字符串；**严禁 `/register`**；测试产生的数据在 teardown 清理。
5. 视觉自检：截图里微信必须是绿双气泡、支付宝必须是蓝方块支字标 —— 如果出来还是线稿气泡，说明改了 `ICON_PATHS` 却没接上 `ENTITY_ICON_FILES`。

## 七、交付格式

1. 文件清单（新增/修改 + 行数）。
2. 断言统计：`账户 key N/14`、`分类 key M/40`、`分类名命中 22/22`、`404:0`、`console error:0`。
3. 截图路径清单（`D:\Project\temp\entity-icons\shots\*.png`）。
4. 遗留 / 风险（例如某品牌无官方矢量、22px 下细节取舍）。
5. `git add` 仅自己改的文件，**不要 push**，不要 bump 版本，提交信息 `feat(icons): v0.15.2 账户与分类图标体系（品牌 logo + 40+ 分类图标）`。
