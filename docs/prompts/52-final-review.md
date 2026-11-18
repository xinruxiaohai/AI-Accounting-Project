# 52 · v0.15.3 终审（只读自动化）· 2026-11-18 02:00

> 执行方式：定时任务自动运行，**只读 + 截图汇报**，禁止任何代码修改。
> 本文件为完整版规格，定时任务的提示词已内联同样的红线，不依赖本文件也能跑。

---

## 〇、绝对红线（违反即视为失败）

| 禁止 | 说明 |
|---|---|
| 修改项目内任何文件 | 禁止 Edit / Write / 删除 / 移动 `D:\Project\project01 AI-Accounting` 下任何文件（含 docs、静态资源、模板） |
| git 写操作 | 禁止 `add` / `commit` / `push` / `checkout` / `restore` / `reset` / `stash` / `branch -f`；只允许 `status` / `diff` / `log` / `show` 等只读命令 |
| 改数据库 | 禁止写 `records.db`、禁止任何 `ALTER` / `INSERT` / `UPDATE` / `DELETE`；起服务必须用 `ZHZ_SQLITE_PATH` 指向 temp 下的副本 |
| 云端变更 | 禁止 `systemctl restart`、禁止部署上传、禁止改云端配置；只允许 `curl` 只读探测 |
| 自行修复 | 发现缺陷只记录，**不修复**，不改代码、不改配置、不调参数 |

**唯一允许写入的位置**：`D:\Project\temp\final-review\`（报告、脚本、隔离库副本、截图）。

---

## 一、项目地址（必须标注清楚）

| 项 | 值 |
|---|---|
| 本地项目根 | `D:\Project\project01 AI-Accounting` |
| 本地主库 | `D:\Project\project01 AI-Accounting\records.db`，md5 必须保持 `211d49e67eaf25c9383b2d6d116e18a7` |
| 云端 | `8.134.12.135`，目录 `/opt/zhihuizhang`，systemd 服务 `zhihuizhang` |
| 云端端口 | gunicorn `127.0.0.1:5000`，nginx 反代 80（**不是 8000**） |
| SSH 私钥 | `<SSH_KEY_PATH>`（本地路径，不随包分发），必须带 `-o StrictHostKeyChecking=accept-new` |
| 产物目录 | `D:\Project\temp\final-review\`（报告 + 截图，唯一可写） |
| 隔离服务启动器 | `D:\Project\temp\entity-icons\serve.py`（已设 `ZHZ_SQLITE_PATH`，端口 5077） |
| CDP 参考脚本 | `D:\Project\temp\entity-icons\cdp.mjs`（登录注入 + 视口 + 截图，59/59 跑通） |
| 测试令牌 | `D:\Project\temp\biz-v0151\token_v0151.txt`（uid 93） |
| 测试用户 | `D:\Project\temp\biz-v0151\user_v0151.json` |
| uv Python | `C:/Users/19370/AppData/Roaming/uv/python/cpython-3.12.14-windows-x86_64-none/python.exe` |
| Edge | `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`，必须 `--headless` |

**测试账号铁律**：只用 `test@test.com`（本地 uid 93）与 `temp_cdp_v0140@example.com`（uid 90），JWT `sub` 必须是字符串，**严禁调用 `/register`**。

---

## 二、审查清单 A · 静态一致性（只读 grep / git）

1. **版本串一致性**：以下必须同一个版本号，逐处报出实际值与不一致项
   - `D:\Project\project01 AI-Accounting\app.py` 的 `APP_VERSION_FALLBACK`
   - `D:\Project\project01 AI-Accounting\static\service-worker.js` 的 `CACHE_NAME` 与 `ASSET_VERSION`
   - `D:\Project\project01 AI-Accounting\templates\index.html` 的 `?v=`（统计数量）
   - `D:\Project\project01 AI-Accounting\static\manifest.json`
   - `D:\Project\project01 AI-Accounting\docker-compose.yml`
2. **模板签名完整性**（缺一个即为文件被覆盖事故）：
   `templates\index.html` 必须同时包含 `mobile-stack-v0152`、`biz-v0151-root`、`entity-icons-v0152`、`v0151-theme.css` 四个签名。
3. **实体图标资源**：`static\icons\entity\account\*.svg` 与 `category\*.svg` 的数量；坏文件判定 = 不以 `<svg` 开头 / 无 `viewBox` / 超过 8KB。
4. **品牌图标数量**：`static\icons\brand-*.svg` 应为 8 个（用户要求只保留第一行前 8 个原有主题）。
5. **秘密泄露**：项目内（排除 venv / .git）grep 硬编码 API Key / 密码 / `sk-` / `.env` 内容；确认 `.env` 未被 git 跟踪。
6. **管理员信息泄露（安全项，最高优先）**：用户端 `templates\index.html` 与 `static\*.js` 中 `权限管理` 是否仍有命中 —— 用户明确要求用户端不得出现管理员相关内容。
7. **数据库红线**：全项目 grep `Base.metadata.create_all`，应为 0 命中（venv 除外）。
8. **迁移备份路径硬编码**：`database.py` 的 `MIGRATION_BACKUP_DIR` 是否为 `D:\Project\temp\db-backup`（Linux 云端会失效，属已知坑）。
9. **未提交改动**：`git status --short` 与 `git diff --stat` 全量清单（**只报告，不处理、不回滚**）。

---

## 三、审查清单 B · 真实浏览器（隔离库，只读验收）

起隔离服务（`ZHZ_SQLITE_PATH` 指向 temp 副本，端口 5077），Edge `--headless` + CDP，注入 uid 93 令牌，双视口 **390×844（dsf 2）** 与 **1440×900** 截图。

| 检查项 | 判定标准 |
|---|---|
| 五个主页面 | 首页 / 账单 / 资产 / 图表 / 我的 均能渲染，无空白页 |
| 设置页 · 外观模式 | 亮/暗 × 主题色可切，至少 2 张代表图（暗色 + 任一彩色主题） |
| 设置页 · 权限管理 | **用户端不存在**「权限管理」tab 或面板 |
| 设置弹窗定尺 | 切换 2 个以上 tab，弹窗外框 `getBoundingClientRect().height` 差值 = 0 |
| 记账弹窗分类 | 一级网格 ≥20 个可见；某个一级的二级菜单展开后每项带图标 |
| 账户图标 | 微信必须是**绿色双气泡 `#07c160`**、支付宝必须是**蓝色方块 `#1677ff`**，非线稿兜底 |
| 移动端二级页 | 点账户后 `.assets-right` 的 rect = `{0,0,390,844}`（±1）且 `position:fixed`；`history.back()` 后恢复 |
| K 线 · 基金 005827 | 日线打开后**底部不得出现 `0 / 0.5 / 1` 刻度**，`getOption().yAxis.length === 1` |
| K 线 · ETF 510300 | `yAxis.length === 2`、`yAxis[1].axisLabel.show === false`，成交量柱肉眼可见 |
| 全局断言 | console error = 0；`/static/*` 404 = 0；双视口横向溢出 = 0 |

---

## 四、审查清单 C · 云端只读探测

全部只读，**不得重启、不得部署**：

| 探测 | 期望 |
|---|---|
| `curl http://8.134.12.135/api/version` | 返回当前版本号（与本地一致） |
| `/static/mobile-stack-v0152.js` | 200 |
| `/static/icons/entity/account/wechat.svg` | 200 |
| `/api/biz/monthly-settlement` | 401（路由存在、鉴权正常，不是 404） |
| `/api/invest/kline` | 401 |
| `systemctl is-active zhihuizhang` | `active` |

---

## 五、输出物

1. **报告**：`D:\Project\temp\final-review\REPORT-20261118.md`
   - 结论表：每项 PASS / FAIL / 未测 + 证据（命令输出、断言数字、截图文件名）
   - **阻断级问题单列**（会导致用户可见故障的，如页面白屏、图标 404、管理员信息泄露、K 线刻度错乱）
   - 主库 md5 测前测后各一次（必须相同）
   - 一句话总裁决：`可发版` / `有条件发版` / `不可发版`
2. **截图**：`D:\Project\temp\final-review\shots\`，命名 `{mobile|desktop}-{序号}-{页面}.png`
3. **回报给用户**：报告路径 + 总裁决 + 阻断项数量 + 阻断项一句话摘要

---

## 六、遇到这些情况要照实记录，不要自作判断

- **工作区有未提交改动**（其他 agent 在跑）→ 记录为「审查时快照」，注明改动文件清单，**不判定为失败、不回滚**
- **隔离服务起不来**（venv base Python 已移除）→ 用 uv Python + `PYTHONPATH=venv/Lib/site-packages`；仍失败则该项记「未测」并写明原因
- **CDP 连不上**（`--headless=new` 会立刻退出）→ 必须用 `--headless`，且服务与浏览器与 node 脚本写在**同一次 shell 调用**里
- **某接口 5xx** → 记录状态码与响应体前 200 字符，不尝试修复
