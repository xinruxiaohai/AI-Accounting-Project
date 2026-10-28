# 21 · AI 截图记账闭环与截图相册（v0.11）

## 需求背景

v0.10 的悬浮球「AI 截图识别」只弹了「将在下一版接入」的假提示，用户要求一次性实装完整闭环：截图记账（后端视觉模型解析入库 + 前端真文件选择）、图片持久化与相册管理（账单详情看原图、我的页相册网格、删图双删）、以及悬浮球交互修复（提示不被遮挡、收回逻辑改为「鼠标离开才 3 秒倒计时」）。

## 核心 Prompt（视觉解析）

> 你是账单识别助手。读取这张消费/支付截图，只输出严格 JSON：
> {"action":"record|unknown","amount":数字,"type":"expense|income|transfer","category":"中文分类","account":"支付账户名","date":"YYYY-MM-DD HH:MM","note":"商户","is_reimbursable":布尔,"contact_name":"代买/报销人"}
> 金额只取实付金额，不要取余额、订单号、优惠前金额；分类按商户性质（餐饮/交通/购物/其他）；时间从小票或支付时间提取，没有就用 __NOW__（今天 __TODAY__）；不是账单截图就返回 {"action":"unknown"}。

## AI 方案简述

- ai_service 新增 `parse_image`：图片转 Base64 dataURL 放进多模态 content 数组（图片块 + 文字块），走 glm-4v-flash（超时 45s），返回 JSON 后复用文本版 `_normalize_intent` 做字段校验与归一化，保证与文本记账同契约。
- 后端 `POST /api/records/ai/image`：校验 Base64/大小 → 视觉解析 → 复用 `_apply_ai_intent` 入账 → 压缩图落盘 `static/uploads/` 并写 `records.image_path`；新增相册列表与删图接口。
- 前端 Canvas 压缩（最长边 800px、JPEG 0.82）→ 复用非阻塞气泡展示「识别中 → 成功可点」；相册/预览弹窗复用既有 Modal 与 Toast 体系。

## 踩坑结论

1. 视觉 Prompt 自带 JSON 花括号，`str.format` 注入时间会 KeyError，必须用 `__NOW__`/`__TODAY__` 占位符 + replace。
2. 图片要发 Base64 dataURL，不能用裸 Base64（模型收不到）。
3. 前端必须压缩，1600px 原图直传会显著变慢；压到 800px 后识别质量不受影响。
4. 相册项要同时挂 `data-album-open`（按钮）与 `data-record-id`（item），否则测试与后续联动取不到 id。
5. 删图必须「清库字段 + 删本地文件」，只软删账目会留下孤儿文件。
6. 悬浮球 tooltip 原在图标上方会被主球/屏幕边缘裁切，改到图标左侧竖排居中并用 `::after` 统一定位，实测估算框不越界、不压主球。
