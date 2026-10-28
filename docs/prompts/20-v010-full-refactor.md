v0.10-DEV Prompt 快照：AI 流式解析、PWA 骨架、账单页、全局气泡系统

一、需求背景

v0.09.2 封版后用户一次性提出 19 项积压改造，跨后端 AI、全站骨架、账单页、交互气泡、管理后台五块。核心诉求是让 AI 记账从「填表单」变成「说人话立刻有反馈」，同时把页面从长文档滚动改成 App 式固定骨架，并补齐账单检索与 AI 反馈闭环。要求先骨架后逻辑，后台连贯写完，遇到语法错误自行修复。

二、核心 Prompt

「你是记账助手，先判断用户这句话属于哪种操作：record（记账）、debt（借贷）、add_contact（添加联系人）、unknown（听不懂）。只返回 JSON，必须包含 action 字段。记账时同时判断是否为代买/报销场景：是则 is_reimbursable 为 true 并给出 contact_name（报销人/被代买人）。金额只提取带货币单位的数字（元、块、¥），绝不提取人名或电话号码里的数字。姓名必须原样保留，不得删字。」

前端补充约束：输入先本地正则拦截「今天/昨天 + 可选动词 + 分类 + 数字 + 元/块」的简单记账，命中即直写 /api/records；复杂或模糊语句才交给 SSE 流式接口，避免简单指令也等模型返回。

三、AI 方案简述

后端把 ai_service 的 SYSTEM_PROMPT 扩成 13 键结构化输出，parse_intent 负责分流，_normalize_record / _normalize_debt / _normalize_contact 各自清洗字段；报销账目在 _apply_ai_intent 里按 contact_name 查或建联系人，再把 is_reimbursable、total_reimbursement、reimbursement_contact_id 写入记录，失败回滚临时联系人。流式接口不重写解析逻辑，只在 parse_intent 前后插阶段事件，用 Response(stream_with_context(...), mimetype="text/event-stream") 推送 data: JSON，末尾发 done/unknown/error。

前端把气泡做成 DOM 队列（最多 4 条，column-reverse 从下往上排），每条气泡内嵌状态文本、思考圆点动画与进度条；打字机按字符定时追加，成功后换特殊标识并挂 data-record-id，点击直接开账单详情。倒计时 3 秒，鼠标进入或 window blur 时清掉定时器，恢复时重新计时。极速拦截用 aiQuickCommand 正则抽取金额、分类、日期偏移与账户，未写账户默认「现金」，随后直接 POST /api/records。

四、踩坑结论

1. Bootstrap Modal 在 show/hide 动画进行中会直接忽略 hide()，弹窗内的发送按钮常被连点导致关不掉；单次延时重试仍会撞上过渡期，最终改成 200ms 轮询直到 .show 消失，最多 15 次。
2. SSE done 事件的记录 id 在 payload.id，而报销信息在 payload.reimbursement，前端若只读 payload.record.id 会拿不到详情入口。
3. 流式接口的 unknown 是 HTTP 200 + status:"unknown"，不是 400；旧接口 /api/records/ai 仍返回 400 固定文案，两套判定必须分开，否则气泡会把「听不懂」当网络错误。
4. 模型会把姓名里的数字当成金额（如「测试乙41215」解析出 6607712.5），测试数据必须用干净姓名；Prompt 里补「金额只提取带货币单位的数字」后复测正常。
5. 极速拦截做账户匹配时不能用 indexOf，历史脏账户名「3」会命中「餐饮30」里的 30，需跳过纯数字账户名并取最长匹配。
6. 移动端 / 窄屏下径向悬浮球会顶到边缘，CSS 用 1024px 断点换了一套更小的位移与尺寸。
