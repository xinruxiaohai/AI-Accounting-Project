# 53 · 评委演示数据灌注（云端 uid 3）· 只写数据，禁止改代码

> 执行对象：新 Agent（代号不限，建议叫「演示数据 Agent」）。
> **权限边界：可以调用接口写数据、可以 SSH 备份数据库；绝对不许改任何项目代码、表结构、配置。**

---

## 〇、开工第一句必须自报

> 「我是演示数据 Agent，本轮任务是在云端给 test@test.com（UID 3）写入约 300 条演示账单并上传 6-8 张真实截图，不修改任何项目代码。」

只要输出里出现 `Edit app.py`、`改表结构`、`CREATE TABLE`、`git commit`，立即停下——越权了。

---

## 一、环境与地址

| 项 | 值 |
|---|---|
| 云端服务器 | `8.134.12.135` |
| 云端目录 | `/opt/zhihuizhang` |
| 服务 | systemd `zhihuizhang`（gunicorn `127.0.0.1:5000`，nginx 反代 80） |
| SSH | `ssh -i "<SSH_KEY_PATH>" -o StrictHostKeyChecking=accept-new root@8.134.12.135` |
| 对公网 API | `http://8.134.12.135` |
| 演示账号 | `test@test.com` / `test1234`，云端 **UID = 3**（体验官） |
| 真实截图源 | `D:\Project\temp\ai-qa-v0152-vision\inbox\`（31 张：微信/支付宝/银行短信/退款/无关图） |
| 产物目录 | `D:\Project\temp\demo-seed\`（脚本、manifest、日志、截图） |

**云端只允许影响 UID 3**。同库还有 uid 1「心如小孩」、uid 2「满穗」、uid 4「CDP测试」三个真实账号，任何写入都不能碰到它们（用 uid3 的 token 走接口即可天然隔离，禁止直接 SQL 批量 INSERT）。

---

## 二、权限红线（违反即终止）

1. **禁止修改任何项目代码**：`app.py` / `database.py` / `ai_service.py` / `templates/**` / `static/**` / `docs/**` 一律只读。
2. **禁止改表结构**：不许 `ALTER` / `CREATE TABLE` / 建索引 / 加外键。
3. **禁止 git 任何写操作**（`add` / `commit` / `push`）。
4. **禁止 `systemctl restart`**（唯一例外：回滚数据库后需要重启让连接重新打开）。
5. **禁止 `/register`**、禁止改密码、禁止改 `.env`、禁止删除任何用户数据。
6. **禁止直连 SQLite 批量写账单**——必须走 HTTP 接口，否则账户余额与账单不平账。
7. 写入前**必须备份云端数据库**，备份文件缺失不许开始。

---

## 三、第 0 步：备份（不做就别往下走）

```bash
ssh -i "<SSH_KEY_PATH>" -o StrictHostKeyChecking=accept-new root@8.134.12.135 \
  "cp /opt/zhihuizhang/records.db /opt/backups/records_pre_seed_$(date +%Y%m%d-%H%M%S).db && \
   ls -lh /opt/backups/records_pre_seed_*.db | tail -1 && md5sum /opt/zhihuizhang/records.db"
```

记下：备份文件路径、md5、以及 `SELECT COUNT(*) FROM records`（用 `sqlite3` 或 python 只读查询均可）。
**回滚命令**要写进交付说明：`cp <备份文件> /opt/zhihuizhang/records.db && systemctl restart zhihuizhang`。

---

## 四、第 1 步：登录拿 token，确认账号与 UID

```bash
curl -s -X POST http://8.134.12.135/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test1234"}'
```

断言：
- 返回里有 `token`；
- `user.id == 3` 或 `user.uid == 3`（若字段名不同，打印整个 `user` 对象确认）；
- 用该 token 调 `GET /api/accounts` 与 `GET /api/categories`，把账户名与分类名清单**原样记下来**（后面造数据只能用这些真实存在的名字，不许自造）。

如果密码不对，**停下来问用户**，不要尝试爆破或改密码。

---

## 五、第 2 步：造账单（核心）

### 接口

`POST /api/records`，`Content-Type: application/json`，`Authorization: Bearer <token>`

字段（以 `app.py:915 _parse_record` 为准，先用 1 条测试确认再批量）：

| 字段 | 说明 |
|---|---|
| `amount` | 数字，**必须 > 0**（布尔值会被拒） |
| `type` | `expense` / `income` / `transfer`（借贷走 `debt`，若接口不支持就跳过，别硬造） |
| `account` | 账户名，必须是 `/api/accounts` 里真实存在的 |
| `category` | 分类名（expense/income 必填其一），必须是 `/api/categories` 里该类型下的真实名字 |
| `date` | 日期时间字符串，先用 1 条试格式（如 `2026-11-15 12:30:00`；被拒就试 `2026-11-15T12:30`） |
| `note` | 备注，**统一带前缀 `[DEMO-20261118]`**，用于幂等与清理 |
| `to_account` | 仅 transfer 必填，且不能等于 `account` |
| `fee` | 仅 transfer，默认 0 |

### 数据要求

- **时间跨度**：`2026-05-18` ~ `2026-11-17`，覆盖近 6 个月（图表页要看得出趋势）。
- **总量**：**260 ~ 320 条**（含 6-8 条截图账单）。别超过 400，演示列表刷太长反而乱。
- **构成（每月）**：
  - 固定：房租 1 笔（2800~3200，居住）、工资薪酬 1 笔（12000~15000，income）、话费 1 笔（39~99）、会员订阅 2~3 笔（15~68）
  - 高频：餐饮 8~12 笔（15~120）、交通 6~10 笔（3~50）、外卖 4~6 笔（18~65）
  - 中频：购物 4~6 笔（50~800）、娱乐 2~4 笔（30~300）、人情 1~2 笔（100~1000）、医疗 0~2 笔（20~500）
  - 低频：旅行 0~1 笔（800~4000）、教育 1~2 笔（100~2000）、宠物/运动/美容 各 0~2 笔
  - 转账：每月 2~3 笔（微信 → 储蓄卡 或 储蓄卡 → 支付宝，金额 500~3000，`fee` 0 或 1）
- **金额与商户要像真的**：`note` 写具体商户或用途（如「星巴克 中杯拿铁」「永辉超市 生鲜」「滴滴 快车 到公司」「地铁 通勤」），不要「测试1」「test」这种。
- **时间要分散**：同一天最多 4 笔，时段落在 07:00~22:00；不要在最后一天堆几百条。
- **分布要能看出对比**：某月支出略高（比如 10 月有旅行），让图表有起伏。
- **不要每条都整数金额**，用 12.50 / 38.00 / 268.40 这种两位小数。
- 每天/每月顺序无所谓，但**每条都要 `note` 前缀一致**。

### 幂等

脚本开头先 `GET /api/records`（分页拉全，或按关键字搜）统计已存在 `[DEMO-20261118]` 的条数：
- 已存在 > 0 → **不再插入**，直接进第 3 步，并在报告里写明「检测到已有 N 条，跳过插入」。
- 等于 0 → 正常插入。
每插入成功一条，往 `D:\Project\temp\demo-seed\manifest.jsonl` 追加一行（id / 金额 / 类型 / 日期 / 分类）。

---

## 六、第 3 步：上传 6-8 张真实截图

用 `D:\Project\temp\ai-qa-v0152-vision\inbox\` 里的真实截图（**不要用 AI 生成图**），走：

`POST /api/records/ai/image`，JSON：`{"image": "<base64，可带 dataURL 前缀>", "mime": "image/jpeg"}`

挑选建议（覆盖不同平台，且金额互不相同）：

| 类型 | 用途 |
|---|---|
| 微信支付成功页 1~2 张 | 演示「截图记账」主场景 |
| 支付宝付款成功 1~2 张 | 展示蓝色支付宝图标与分类识别 |
| 银行短信截图 1 张 | 展示无单号兜底 |
| 退款截图 1 张 | 展示方向判定（退款记 income，不是 expense） |
| 无关图（风景照）1 张 | **不要上传**，仅用于说明「无关图会判 unknown 不建账」 |

注意：
- 该接口有 **sha256 去重（L1）**，同一张图二次上传会返回 `duplicate: "exact"`，属正常，不要加 `force` 绕过。
- 每次上传会真实调用一次视觉模型（有成本），**严格控制在 8 张以内**。
- 上传后记下返回的 `record.id` 与 `image_path`，写进 manifest。

---

## 七、第 4 步：验收（必须交数字）

| 检查 | 标准 |
|---|---|
| 总条数 | `GET /api/records` 统计，比备份前多 260~320 条 |
| 时间跨度 | 最早 ≥ 2026-05-18，最晚 ≤ 2026-11-17 |
| 类型分布 | expense / income / transfer 三类都有，income 每月至少 1 笔 |
| 分类分布 | 一级分类命中 ≥ 12 个（不要只堆在餐饮） |
| 账户分布 | 至少 3 个账户有流水 |
| **平账** | 每个账户「当前余额」与「初始余额 + 收入 − 支出 ± 转账」一致（用 `/api/accounts` 与账单汇总交叉核对，差额必须为 0） |
| 截图账单 | ≥ 6 条记录的 `image_path` 非空，且 `GET` 该路径返回 200 |
| 其他用户未受影响 | uid 1 / 2 / 4 的账单条数与备份前一致 |
| 云端库 md5 | 变化是正常的（写了数据），但要记录前后值 |

另外人工看三张页面（截图存 `D:\Project\temp\demo-seed\shots\`）：
- 首页：本月支出/收入/结余卡片有数字，近 7 天有流水；
- 图表页：月度趋势有 6 个月柱子、分类占比有多色扇区；
- 账单页：列表有内容，分类图标与账户图标正常（微信绿、支付宝蓝）。

---

## 八、交付

1. 写入统计：总条数、expense/income/transfer 各多少、时间跨度、涉及账户数、一级分类命中数。
2. 截图账单：8 张以内清单（原图名 → record id → image_path）。
3. 平账核对表：每个账户 初始/收入/支出/当前余额 四项，差额 0。
4. 截图 3 张：`D:\Project\temp\demo-seed\shots\`（首页 / 图表页 / 账单页）。
5. 备份与回滚：备份文件路径、md5（前后）、回滚命令。
6. 幂等说明：manifest 路径、二次运行的行为。
7. 一句话确认：**未修改任何项目代码**（列出执行过的所有 sed / 写文件操作，正常应只有 `D:\Project\temp\demo-seed\` 下的脚本与 manifest）。

---

## 九、已知坑（照做省时间）

- 云端 gunicorn 监听 **5000**，公网走 nginx 80；测试用公网 `http://8.134.12.135` 即可。
- 接口要求 `Content-Type: application/json`，不带会拿到 `请求体必须是 JSON 对象`。
- `amount` 传字符串会被拒，必须数字；`amount <= 0` 也会被拒。
- `transfer` 必须带 `to_account` 且与 `account` 不同，转账没有分类（后端自动用「转账」）。
- 截图接口的 base64 长度上限约 `MAX_UPLOAD_BYTES * 2`，超过返回 413；大图先缩到长边 1600 再传。
- 云端数据库是 `/opt/zhihuizhang/records.db`，**部署脚本不会覆盖它**，但备份仍然必须做。
- 若发现 `records` 表里已有 `[DEMO-` 前缀的旧数据，先报给用户，不要自行删除别人的演示数据。
