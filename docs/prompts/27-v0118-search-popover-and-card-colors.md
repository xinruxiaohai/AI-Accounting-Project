# 27 · v0.11.8 账户余额卡品牌渐变与全局搜索浮窗

## 一、需求背景

1. 资产页右侧「账户余额」卡永远是一套黄色渐变，微信、支付宝、银行卡长得一模一样；
2. 全局搜索只在首页过滤已加载列表，切到别的页面就用不了，而且结果混在列表里，点不进详情。

## 二、核心方案

- **余额卡渐变**：accountCardKind(name) 用正则把账户归成 wechat / alipay / bank / cash /
  invest / default，renderAccountBalanceCard 切换 `is-card-*` 类名，CSS 每个类一套渐变 + 投影。
- **搜索接口**：GET /api/search?q=&limit= → database.search_records，
  对 note / category / account / to_account / CAST(amount) LIKE，转义 % 与 _，上限 500。
- **搜索浮窗**：#search-popover 动态创建，fixed 定位、宽度取搜索框 rect、z-index 4000、
  max-height 400px 独立滚动；首屏 10 条，IntersectionObserver 观察底部 sentinel 追加下一批；
  底部灰色小字显示「已加载 N / 共 M 条结果」。
- **点结果开详情**：openRecordDetail 拆出 showRecordDetail(record)，
  搜索点击直接把整条记录塞进详情弹窗，不要求它出现在首页 state.records 里。

## 三、踩坑结论

1. LIKE 不转义 `%`，输入一个百分号就能把整库拉出来；
2. 浮窗用 absolute 会被 sticky topbar 裁剪，改 fixed 并在 scroll/resize 时重算 rect；
3. IntersectionObserver 的 root 必须是浮窗滚动容器，否则 sentinel 一直可见会一次灌进全部结果；
4. 搜索结果不在 state.records 中，详情入口必须能直接接收整条 record。
