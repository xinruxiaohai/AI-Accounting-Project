# 28 · v0.12 多用户账号系统与账单导入

## 一、需求背景

记账应用一直只有一份数据：谁打开都是同一个账本。v0.12 要把它变成真正的多用户应用，
同时支持从微信/支付宝导出的 CSV/Excel 一次性迁移历史流水。

## 二、核心方案

### 1. 用户与 ID 预留

- users 表：id / email UNIQUE / password_hash / phone / created_at
- `UPDATE sqlite_sequence SET seq = 9 WHERE name = 'users'`（没有该行就 INSERT），
  让自增起点是 10，1-9 留给系统/未来机器人账号。
- 迁移脚本创建 id=1 超管：1937097795@qq.com / 123456（werkzeug generate_password_hash）。
- 核心表全部 ALTER ADD user_id INTEGER NOT NULL DEFAULT 1 并回填 1；
  accounts 由 name 单主键重建成 (user_id, name) 复合主键（SQLite 需整表重建）。

### 2. JWT 鉴权

- PyJWT HS256，payload 的 sub 必须转成字符串（PyJWT 2.15 严格要求）。
- POST /api/auth/register、/api/auth/login 返回 {token, user}，user 只含 id/email/phone/created_at。
- @login_required 装饰器 + 全局 before_request 身份守卫，未登录 /api/* 一律 401 auth_required。
- database 用 contextvars 保存当前用户，所有 records/accounts 读写强制 user_id 条件。

### 3. 账单导入

- /api/import/parse：pandas 读 CSV/Excel，编码 utf-8-sig → utf-8 → gb18030 → gbk；
  表头行自动探测，列名按关键词优先级识别（收/支 优先于 交易类型）。
- 判重：当前用户最近 10 天，时间 + 金额 + 商户三者重合 → is_duplicate。
- /api/import/confirm：只写未重复项，逐条 add_record 联动余额，写 import_history。

## 三、踩坑结论

1. add_record 的 INSERT 参数顺序写反（amount 与 user_id 互换）会让 user_id 变成金额，必须靠 E2E 断言兜住；
2. accounts 的 name 单主键在多用户下必然冲突，只能重建复合主键表；
3. 微信/支付宝导出 CSV 常见 GBK/GB18030，utf-8-sig 先试再退；
4. 导入确认必须复用 add_record，不能直接 INSERT，否则账户余额不会联动。
