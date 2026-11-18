# 提示词 55 · 主题跨设备同步 + 设置页历史登录设备（v0.15.4）

> 交付对象：后端 Agent / 前端 Agent / 验收部署 Agent
> 建立时间：2026-11-18
> 前置：v0.15.4 已上线（场外基金 K 线改净值折线），本轮业务版本仍钉死 v0.15.4
> 状态：已上线；备份 `/opt/backups/pre_themesync_20261118-164257.tgz`

---

## 一、需求背景

用户反馈：主题（皮肤 + 亮暗）只存在 localStorage，换设备/清站点数据后丢失；设置页看不到账号在哪些设备上登录过。目标是在**不改表结构、不改业务版本号、不动通知与账单数据**的前提下，让主题跟账号走，并给出一份只到城市粒度的登录设备只读列表。

---

## 二、核心 Prompt（可直接复用）

> 你是智汇账 v0.15.4 的主题同步与设备记录 Agent。开工前先读 `docs/HANDOFF.md`。
>
> 1. 后端零 DDL：只复用现有 `app_settings(key TEXT PRIMARY KEY, value TEXT)`，不得 CREATE TABLE / ALTER TABLE。新增 `GET/PUT /api/user/theme` 与 `GET /api/user/login-devices`，全部 `@login_required` + uid 隔离。
> 2. key 前缀硬性约定：`user_theme:<uid>` 存 `{"skin","mode"}`；`login_device:<uid>:<指纹16位>` 存 `{"device","browser","city","last_at"}`。指纹 = `sha1(device|browser|city)[:16]`，同指纹重复登录只刷新 `last_at`，最多保留 10 条。
> 3. 隐私红线：响应只回 `device/browser/city/last_at`；绝不带 IP、经纬度、UA 原文、token。城市靠 ip2region 离线库；内网 IP →「本机」，xdb 缺失/异常 →「未知地区」，任何异常都不得阻断登录。
> 4. 前端：首帧前注入服务端主题，避免「先白后暗」；本地写先生效，再 300ms 防抖回写；断网不发请求、不报错；登录/刷新后按账号拉取。设置弹窗「账户与密码」新增只读设备面板，正常 / 空 / 错误三态都要有中文人话，弹窗仍 920×680。
> 5. 版本规则：业务版本 `APP_VERSION_FALLBACK` 保持 `v0.15.4`，`/api/version` 必须仍返回 `v0.15.4`；资源指纹 `?v=` 从 `0.15.4.1` 全量升到 `0.15.4.2`（index / manifest / admin / invest-v0133.js），`ASSET_VERSION=0.15.4.2`，`CACHE_NAME` 保持 `ai-accounting-v0.15.4`。
> 6. 测试：禁止 `/register`；只用 `test@test.com/test1234`（本地 uid93、云端清洗后 uid3）与 `temp_cdp_v0140@example.com`（本地 uid90、云端 uid4），JWT `sub` 必须字符串；所有脚本、截图、隔离库放 `D:\Project\temp\theme-sync\`，`ZHZ_SQLITE_PATH` 指副本，主库 md5 必须恒为 `211d49e67eaf25c9383b2d6d116e18a7`。
> 7. 部署：先备份云端（排除 records.db 与 venv），只传改动文件并重启；核验版本/静态/登录/新接口/数据条数/日志；归档 HANDOFF、dev-log、本提示词与 temp/index.md，本地提交不 push。

---

## 三、方案简述

- **存储层**：`database.py` 新增 `THEME_SKINS/THEME_MODES`、key 构造、JSON 读写（脏数据一律回落默认）、`record_login_device()` / `list_login_devices()` 与超量裁剪；所有查询按 `uid` 前缀过滤，零 DDL。
- **接口层**：`app.py` 登录成功分支调 `_record_login_device(uid)`；三个新接口均带鉴权，`skin=rainbow` / `mode=neon` 返回 400；ip2region 惰性加载 + 进程内缓存，解析兼容 v2/v3 五段格式。
- **前端**：`templates/index.html` 内联主题预置 + 同步状态机，`static/login-devices-v0154.js` 独立加载设备面板；主题 PUT 防抖 5 连点只发 1 次，首帧前注入无闪烁。
- **部署**：11 个改动文件增量传输；`ip2region` 未安装，未传 xdb，城市降级为「未知地区」且登录不受影响。

---

## 四、验收结论

| 项目 | 结果 |
|---|---|
| 隔离库后端（正常 + 降级） | 26/26 + 4/4 全绿；表/索引零变动；uid93/90 主题隔离；`login_device:93:*` 同 UA 三次仍 1 条；响应无 IP/UA/token；无 xdb 时 city=未知地区 |
| 真实后端跨设备 CDP | 24/24 全绿；设备 A PUT 琥珀暗色、设备 B 全新 profile 自动套用、刷新首帧前落地；console 0 error、/static 0 个 4xx、两种视口零横向溢出、弹窗 920×680 |
| 设备列表三态 | 替身台 26/26；正常 5 条截断且首条「当前设备」、空态「暂无记录」、错误态「暂时无法获取」，均无 JS 报错 |
| 线上 | `/api/version=v0.15.4`；54 个静态资源全 200；登录 uid=3；主题/设备接口 200；通知 49、未删除账单 1962（另有 1 条软删除）；`0.15.4.1` 残留 0；重启 5 分钟日志零 error |
| 数据红线 | 主库 md5 全程 `211d49e67eaf25c9383b2d6d116e18a7`；云端只新增 app_settings 业务 key，未动通知与账单 |

---

## 五、踩坑结论（下次照抄）

1. PyPI 没有 `ip2region` 包，应装 `py-ip2region`；官方新版数据文件叫 `ip2region_v4.xdb`，raw 下载易断流要 `curl -C -` 续传。
2. 新版 xdb 是 v3 五段 `国家|省|市|ISP|国家码`，不能沿用老版 `中国|0|省|市|ISP` 的字段位置；按第 2 段是否 `0` 分派，否则城市取成省名。
3. `import app` 会执行既有 `init_db()` 迁移，给副本补 `image_hash/trade_no` 两列；「表结构未变」必须先以 init 后的副本为基准，再比对三个新接口调用前后。
4. Headless Edge 只能 `--headless`；关 SW 用 `delete Navigator.prototype.serviceWorker`，不能用 `Object.defineProperty(..., undefined)`。闪烁断言用 `performance.getEntriesByType('paint')` 与 MutationObserver 时间戳比对。
5. 版本号是两套口径：业务版本钉死 `v0.15.4`，资源指纹升 `0.15.4.2`，`CACHE_NAME` 不动。`static/invest-v0133.js` 内联的 `?v=` 最容易漏改，线上必须 grep 残留。
6. 云端 `records` 原始行 1963 = 1962 条未删除 + 1 条 `deleted_at` 非空；核验「1962 条账单」要带 `where deleted_at is null`，不要误判为数据被改动。
