# v0.13.0 Prompt 快照：全局交互、可视化分类网格、图表看板

## 需求背景
用户希望产品从「能用」跃升到「专业」：原生 alert/confirm 破坏观感，记账分类下拉框体验老旧，缺少独立的图表分析页。

## 用户原话要点（精简）
1. 彻底移除所有 alert/confirm，危险操作统一高级自定义 Modal；设置图标点击 180° 旋转；主按钮按下缩放；悬浮球悬停立即展开、移出 3 秒收回；手动记账成功复用 AI 记账气泡。
2. 记账弹窗分类改大图标网格，支出/收入切换自动刷新；带二级的分类点开悬浮小卡片；点一级项本身即默认该一级；浮层提供「不细分（直接使用一级分类）」；无二级项直接高亮。
3. 侧栏新增【图表】Tab（选中项左侧橙色高亮竖线）；图表页左侧二级菜单、顶部年/季/月/周 + 左右切换；居中三列收支结余大数字；极值趋势图渐变填充 + 最大/最小/均值三条虚线，底部收支结余切换；汇总表日期/收入/支出/结余；深浅色适配；真实浏览器详测后 commit + tag v0.13.0-DEV。

## 方案简述
- 确认弹窗：#action-confirm-modal + confirmAction() 返回 Promise，pendingConfirm 防并发；仅函数内部保留一处原生 confirm 兜底。
- 分类网格：#category-grid/.cat-item（entityIconHtml 42px）+ #category-flyout 绝对定位浮层；隐藏 select #category/#sub-category 继续承载 selectedCategoryId 与 AI 回填，避免破坏既有解析逻辑；点击只改 .is-active（syncCategoryGridSelection），document 外部点击加 documentElement.contains 守卫。
- 图表页：templates 增加 #page-charts 骨架，static/charts-v013.js 负责周期分桶、聚合、ECharts option、汇总表与主题重绘；script.js 在 switchPage 中调用 window.renderChartsPage。
- 动效与气泡：CSS :active/旋转动画；saveRecord 新建成功后 showRecordSuccessBubble 复用 createBubble/attachBubbleRevise。

## 踩坑结论
- bash heredoc 写含中文补丁会因未终止/编码失败，统一改 write .py 再执行。
- 分类网格若在 click 里重建 DOM，event.target 会被摘出文档，document 监听器 picker.contains(target)=false 会把刚打开的浮层收起。
- 图表周期切换若在数据已缓存时仍走 async 加载，会闪「正在加载…」并丢弃连点；改为 recordsReady() 直接 renderAll()。
- CDP 读动画中间态需 sleep 260ms；Bootstrap Modal.show() 异步过渡，同一 evaluate 内立刻点按钮会竞争。
