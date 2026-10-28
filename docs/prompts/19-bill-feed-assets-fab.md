# Prompt 快照 19：全站账单流 + 资产页与悬浮球重构（v0.09.2）

## 需求背景

v0.09.1 之后资产页和列表还是表格 + 卡片混排：金额颜色混乱，借款、转账也被染成红绿；首页账单、日历明细、资产页流水三处各写一套 <table>，手机上横向挤压严重；净资产卡太宽、四个统计卡松散、账户列表用卡片块；右下角悬浮球还挂着预算面板，不像记账 App 的主入口。

## 核心 Prompt

模块一（底层逻辑）：全站金额颜色统一，只有 type="income" 绿色、type="expense" 红色，借款 / 贷款 / 转账等资金流转一律正文深灰；修复 /api/records/ai 识别为 debt 后不联动账户余额的问题并测试；ECharts 加 window resize 自适应；侧栏锁 140px、缩按钮 padding、绝不截断文字。

模块二（去表格化）：首页账单、资产页流水、日历明细全部废弃 <table>，改 App 列表流——最外层月份表头（2026年10月 + 当月收支汇总），第二层每日表头（25日，大字体，全局省略年份），交易行左侧灰色时间（21:48）、中间分类/备注、右侧金额 + 当时余额快照。

模块三（资产页）：净资产卡保留渐变但暗色降饱和、加小眼睛隐藏金额、加自定义背景图（注释留云端同步 TODO）、宽度收窄让右侧放统计；借入/借出/待报销/已报销四卡紧凑合并并可点开明细；账户列表改列表流、左侧平台彩色圆标、金额按语义变色。

模块四（悬浮球）：主图标改蓝色钢笔，点击径向弹出普通记账 / AI 文本快记 / AI 截图识别；悬停 0.5s 出文字 Tooltip；点功能后 3 秒无操作或再点钢笔自动收回。先骨骼后逻辑，不能破坏旧功能。

## AI 方案简述

金额颜色收敛到 amt-income / amt-expense / amt-neutral 三个类，日历、首页、资产页统一走 amountCellHtml / feedAmountHtml。列表流抽成 feedRowHtml / feedGroupsHtml / feedEmptyHtml，后端不用改；余额快照用 balanceSnapshots 从账户当前余额倒推（expense 加回、income 减掉、transfer 反向处理 from/to），老数据也能显示当时余额。资产页 HTML 改为 .assets-top（左 4 成 hero + 右 6 成统计）与 .assets-split；小眼睛用 state.amountHidden 控制 assetMoney；背景图把用户图片等比缩到 1600px 转 JPEG 存 localStorage 并给 .assets-hero.has-bg 加暗色遮罩，代码里标注了后续上传对象存储做多端同步的 TODO。统计四卡改成按钮，点击按 kind 拉 /api/debts?status=unpaid 或从 state.allRecords 的报销字段算明细，弹 #stat-detail-modal。悬浮球保留 #fab-ball，新增 #fab-actions 三个 button[data-fab-action]，CSS 用 translate 做径向弹出，::after 做 0.5s 延迟 Tooltip，JS 用 3 秒定时器自动 closeFab。AI 借贷余额确认无需改后端：database.create_debt 已经在事务内调用 _apply_effects(_debt_effects(...))。

## 踩坑结论

1. Bootstrap 弹窗 / 悬浮球的「点完立刻收起」要留意动画期；悬浮球这次用独立定时器 fabAutoTimer 做 3 秒自动收回，不依赖 hover。
2. 测试姓名千万别带数字：真实联调「借给测试乙41215」被模型解析成 6607712.5，数字污染了金额，回归测试必须用干净姓名。
3. 余额快照是倒推出来的，只覆盖账单里的流水；借贷表本身没有账单行，所以借贷变动不会体现在首页那条余额上，这是当前数据模型的已知口径。
4. 列表行用 div[role=button] 而不是 <button>，否则 onRowClick 里对 button 的排除逻辑会把账单行点击吞掉。
5. AI 截图识别这版只留入口（file input + 提示），真正接视觉模型放到下一版，避免把未验证的 OCR 塞进封版。
