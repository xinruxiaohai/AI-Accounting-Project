# 40 · v0.13.4 邮箱验证码后端与东财搜索接入

## 需求背景

注册与找回密码原先只有短信占位（`sms-login` 返回 501），验证码没有真正的投递通道，也没有落库，
重启即失效、无法限次。投资标的搜索则只有一份本地 Mock 字典，收录不全，用户搜基金代码经常搜不到。
本版只做后端与接口：验证码走 QQ 邮箱 SMTP，搜索走后端代理东方财富免鉴权 search-api。

## 核心 Prompt（要点，非原文）

1. 新建表 `email_verifications (id, email, code_hash, purpose, attempts, expires_at, created_at)`；
   **验证码只存哈希**，有效期 5 分钟，尝试上限 5 次
2. `POST /api/auth/send-code`：收 `email` + `purpose`，**1 分钟防刷**，`secrets` 生成 6 位码，
   `smtplib.SMTP_SSL(465)` 发 **HTML** 邮件
3. `POST /api/auth/verify-code`：收 `email, code, purpose`，校验过期 / 超次 / 哈希匹配，成功即失效
4. 重写 `/api/invest/search`：后端代理东财 `search-api`，返回 `[{code, name, category, type}]`
5. **红线**：后端请求至少 **1 秒**最小间隔，防 IP 被东财封
6. 保留本地 Mock 字典：外部失败 / 超时 / 断网自动降级
7. 前端：搜索框 **500ms 防抖**；选中结果自动回填 `ticker`、`name`、`asset_type`（股票/基金/黄金）

## 方案简述

### 验证码落库
- `_migrate_email_verification()` 幂等建表 + `(email, purpose)` 索引，挂在 `init_db()` 第二段 DML 之前
- 哈希 = `sha256(f"{JWT_SECRET}:{code}")`，pepper 复用 `JWT_SECRET`（不引新配置，也不存明文）
- `save_email_code` 先删同 `(email, purpose)` 再插：一个用途同时只有一条有效码，避免多码并存
- `register_email_code_attempt()` 用 `attempts = attempts + 1` 原子自增；打满 5 次直接删行

### 发信语义
```python
delivered, err = _send_verification_email(email, code, purpose)
if not delivered and MAIL_CONFIGURED:      # 配了却发不出：作废 + 502
    database.consume_email_code(email, purpose)
    return jsonify(error="验证码邮件发送失败，请稍后重试"), 502
```
- 未配置 SMTP 时 `delivered=false` + 控制台打印，方便本地联调（前端据此提示"看后端日志"）
- `_build_verification_email()` 单独抽出：不发信也能断言主题 / 收件人 / `multipart/alternative` / HTML 含码

### 东财代理
- `https://searchapi.eastmoney.com/api/suggest/get?input=&type=14&count=`，免鉴权、无需 Referer
- 进程级 `threading.Lock` + `_last_request_at` 睡够 1 秒差额：**这是红线**，并发下也只有一个请求在飞
- `Classify`/`SecurityTypeName` → `stock/fund/bond/gold`，过滤指数 / 板块 / 期货 / 期权
- `search_or_fallback()` **只在异常/超时**回落本地字典；空结果按"真的搜不到"处理，不回落

## 踩坑结论

- `openHoldingModal()` 里 `investEnhanceSelects(modal)` 传的是 bootstrap `Modal` **实例**不是 DOM，
  `scope.querySelectorAll is not a function` 被 `await` 吞成 unhandled rejection —— 弹窗能开、但平台下拉
  从未被增强、平台列表也不加载。改为 `investHoldingModalEl()`。真实浏览器 console 里这条报错一直在，
  CDP 用例把它当"页面无 JS 异常"的硬断言才暴露出来。
- CDP 等待候选时不能直接 `return 空数组`：**空数组在 JS 里是 truthy**，`waitExpr` 会立刻"等到"，
  于是所有断言都跑在 500ms 防抖触发之前，表现为"0 请求 / 候选为空"的假红。判断条件必须是 `length > 0`。
- 浏览器会缓存 `static/invest-v0133.js?v=0.13.4`（版本串没变），改了 JS 必须换 profile 或清 SW 缓存，
  否则测的还是旧文件。
- `.env` 实测没有 `MAIL_*`，真实投递无法验收：接口层 502/429/哈希/过期全部可测，但"真的收到邮件"
  只能等凭据补齐后跑 `D:\Project\temp\test_v0134_send_real.py`。

---

## 补丁（v0.13.4-DEV，用户反馈「只输入名字搜不到」之后）

> 用户原话（m00564）：「搜索时只输入标的名字还是无法自动关联查询结果，需要修改一下。搜索不能依靠字典，而是使用api联网查找。字典留到以后设置一个自动补充的功能」

- **根因**：`investSearchSecurities()` 第一行是 `if (investMockEnabled()) return investMockSearch(...)`。浏览器 localStorage 里只要留着 v0.13.3 调试时写入的 `ai-accounting-invest-dev-mock="1"`，搜索就永远只读本地字典——那份字典收录不全，中文名自然搜不到。
- **定案**：搜索链路删掉 mock 分支，**永远**走 `/api/invest/search`；本地字典只做后端断网兜底，将来单独做「自动补全标的资料」。
- **降级可见**：`search_with_fallback_info()` 返回 `(items, fallback, reason)`；接口降级时回 `fallback:true` + `notice`，前端渲染在候选框顶部；搜索异常不再静默隐藏，改为「搜索失败，请检查网络后重试」。
- **缓存坑**：SW 静态资源是 stale-while-revalidate，发版后第一次刷新吃旧 JS。模板 `?v=0.13.4.1` + `CACHE_NAME=ai-accounting-v0.13.4-r2` 双 bump，URL 变了缓存键就失效。
- **验证**：搜索 21/21、真实 Chrome CDP 37/37（含「贵州茅台」「广发道琼斯」按名称搜索、`investMock=1` 残留标记回归、断网实例降级提示、console 0 error）。
