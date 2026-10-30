# 25 · v0.11.6 账户编辑、AI 跨账户纠错与批量管理

## 一、需求背景

v0.11.5 之后仍然有三类体验问题：

1. 资产页只能新增账户，名字/余额写错就得删了重建，也没有「当前账户余额」的显眼卡片；
2. 气泡改账时跨账户（微信 → 支付宝）余额不对，AI 说出库里没有的账户时只会记到一个奇怪名字；
3. 账单/账户没有批量操作，主题只有浅色/深色两种，PWA 装到桌面后顶栏右侧被系统窗口按钮挡住。

## 二、核心方案

- **账户编辑**：PUT /api/accounts/<name> 新增 new_name；database.rename_account 在同一事务里改
  accounts 主键 + records.account + records.to_account + debts.account；右栏顶部金色渐变余额卡。
- **跨账户回滚**：复用 update_record 的「先撤旧账 → 校验新账 → 落新账」，无需额外代码；
  测试用「微信 30 改支付宝 50」验证旧账户 +30、新账户 -50。
- **AI 自动建户**：app._ensure_ai_account 在入库前检查库中账户，不存在就建空账户；
  响应带 is_new_account / new_account_name；POST /api/accounts/merge 合并（余额相加 + 账目迁移）。
- **批量管理**：POST /api/records/batch/delete、PUT /api/records/batch/category、
  POST /api/accounts/batch/delete；前端 Ctrl 多选 + 底部批量栏。
- **设置中心**：首页卡片显示/隐藏（localStorage）、主题三态（浅色/深色/跟随系统 + matchMedia）。
- **PWA 兜底**：standalone / window-controls-overlay 下 .topbar 强制 padding-right 140px + top 30px；
  service worker CACHE_NAME 升版本，旧缓存自动清理。

## 三、踩坑结论

1. ensure_category 只返回分类字典、失败抛 RecordError，批量接口不能按 (dict, error) 解包；
2. 账户改名必须同步 to_account，否则转账记录的旧账户名会变成幽灵账户；
3. 合并账户后账目与借贷要一起迁，余额相加才能保证总资产不跳变；
4. PWA 缓存不升 CACHE_NAME 的话，用户装到桌面永远看到旧页面。
