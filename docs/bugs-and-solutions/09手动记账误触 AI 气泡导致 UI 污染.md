前端与交互-09-手动记账误触 AI 气泡导致 UI 污染

问题表现：

用户在记账弹窗里手动填金额、选分类、点保存，成功后右下角弹出一个气泡卡片：

```
记账成功
已记入 ¥32.50 · 餐饮 · 微信
哪里不对直接说，比如：改成微信   ← 输入框
```

问题是：用户根本没有用过「AI 快记」。这条输入框会让人以为「必须再跟 AI 说一句话才算完」，不少人真的在里面打字，把本来已经正确的账目又改了一遍；截图做演示时也显得这套系统「什么都要 AI 插一嘴」。

排查过程：

从「保存」按钮往回追 `saveRecord()`，成功分支里是：

```js
const created = await api("/api/records", jsonOptions("POST", payload));
// v0.13：手动记账成功也走右下角气泡，和 AI 记账保持同一套反馈
showRecordSuccessBubble(created, values);
```

`showRecordSuccessBubble()` 内部复用 AI 成功气泡的样式，并且**无条件** `bubbleAppendNote(bubble, "哪里不对直接说…")` + `attachBubbleRevise(bubble, recordId)`。

当初的设计意图是「让手动和 AI 手感一致」，但它混淆了两件事：

- 气泡是 **AI 交互的载体**（对话、修订、追问都发生在气泡里）；
- Toast 是 **操作结果的通知**（一次性、无输入、不占用注意力）。

手动填表属于后者。v0.13 把两者当成同一个东西，等于在手动的成功路径上强行插了一个对话入口——典型的**状态未隔离**：`showRecordSuccessBubble` 只判断「记账成功了」，没有判断「这条账是谁记的」。

解决方案：

1. 调用点直接改回普通 Toast，把气泡彻底让给 AI：

```js
await api("/api/records", jsonOptions("POST", payload));
// v0.14.0-TST：手动记账与 AI 气泡彻底解绑，气泡只属于「AI 快记」
toast("记账成功", "success");
resetPaging();
```

2. 给 `showRecordSuccessBubble()` 补上明确的弃用注释，写明「任何手动入口都不要再接它」，避免下一次重构又被「统一手感」说服着接回去：

```js
/**
 * v0.14.0-TST 起**手动记账不再调用本函数**：填表保存后只弹普通 Toast，
 * 气泡与修订输入框只属于「AI 快记」。
 */
```

3. 验证时不能只看「有没有弹提示」，要精确断言气泡容器为空：

```js
const bubbles = document.querySelectorAll("#bubble-stack .bubble").length;   // 期望 0
const revise  = !!document.querySelector(".bubble-revise-input");            // 期望 false
const hasHint = /哪里不对/.test(document.body.innerText);                    // 期望 false
```

顺带修掉一个相邻问题：记账成功后没有清空全局搜索词，如果之前搜过别的东西，近 7 天会按关键词过滤，新账看起来「没记上」。现在成功回调里统一 `clearSearchForNewRecord()` + `refreshRecentPanel()`。

教训：

1. 「操作成功的反馈」和「AI 对话的入口」是两类完全不同的 UI，共用组件可以，共用**触发条件**不行。判断标准很简单：这个控件有没有输入框？有就必须只出现在对话场景。
2. 复用视觉样式不等于复用交互语义。`showRecordSuccessBubble` 复用气泡样式是对的，无条件挂上修订表单是错的。
3. 状态隔离要落到调用点上，而不是在函数内部猜「这次是不是 AI 触发的」——调用点天然知道答案，函数内部只能靠猜。
4. 弃用函数的注释必须写清楚「谁来替代、为什么」，否则半年后一定会有人为了「统一手感」把它接回去。
