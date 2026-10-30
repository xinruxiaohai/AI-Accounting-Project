# 26 · v0.11.7 AI 纠错完整表单、Ctrl 批量、设置弹窗与通知双时间

## 一、需求背景

三处验收痛点：

1. 详情「AI 纠错」只能改分类，金额/账户/日期错了改不了；
2. 批量管理只是摆设，没有 Ctrl 多选语义；
3. 「我的」页内嵌设置卡片太挤，想要独立大弹窗；
4. 通知发布时间有 Bug，且没有「定时生效」能力——排到明天的通知今天就露出去了。

## 二、核心方案

- **AI 纠错完整表单**：弹窗收集金额/分类/账户/备注/日期，POST /api/records/<id>/ai-revise；
  该接口检测到结构化字段就跳过 AI 解析，直接构造完整 parsed 走 _apply_ai_correction，
  全量 UPDATE + 跨账户余额回滚 + 审计日志一次完成。
- **Ctrl 批量**：批量态普通点击单选、Ctrl/Command 点击追加、Ctrl+A 全选、Esc 退出；
  批量删除/改分类复用 v0.11.6 的 /api/records/batch/* 与 /api/accounts/batch/delete。
- **设置弹窗**：把原设置卡内容搬进 #settings-modal（复用原 id），
  「我的」页与顶栏齿轮都改为打开弹窗；保存后自动收起。
- **通知双时间**：notifications 新增 visible_at；publish_date 只做展示；
  后台表单新增「定时发布时间」；POST/PUT 双写；GET 严格 `visible_at <= now` 过滤。

## 三、踩坑结论

1. 表单金额是字符串，必须先 float 归一 + >0 校验，否则 500；
2. update_record 会把日期补成「00:00」，断言按前 10 位比较；
3. publish_notification 不能再无脑把 publish_date 刷成现在，否则排好的定时展示时间被吃掉；
4. 老库迁移必须回填 visible_at = publish_date，否则历史通知全员不可见。
