# AI 记账管家

一个本地部署的个人记账应用：手动记账、AI 自然语言/截图识别入账、多账户与往来账、图表看板、多用户隔离。
后端 Flask + sqlite3，前端原生 JS/CSS + Bootstrap 5 + ECharts，无构建步骤，起服务即用。

## 快速开始

```bash
# 1. 装依赖（项目自带 venv）
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置 .env（AI 相关 Key 可选，缺了只是 AI 记账不可用）
#    .env 换 Key 后必须彻底结束旧 Flask 进程再启动，否则读的还是旧的

# 3. 起服务
.\venv\Scripts\python.exe app.py
```

打开 http://127.0.0.1:5000 。首次启动会自动建库 `records.db` 并写入默认分类。
该开源项目已接入服务器 网址：http://8.134.12.135/

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Flask + sqlite3（单文件 `records.db`）+ PyJWT |
| 前端 | 原生 JS/CSS + Bootstrap 5 + ECharts |
| 数据 | pandas / openpyxl（导入导出、统计） |
| 认证 | JWT HS256，7 天有效期；未登录统一 401 `auth_required` |
| PWA | `manifest.json` + `service-worker.js` |

**没有 npm、没有构建、没有打包**——改 `static/` 和 `templates/` 后刷新即可生效（注意静态资源带 `?v=` 版本号，大改动要同步 bump，否则浏览器吃旧缓存）。

## 目录结构

```
app.py                 Flask 路由（主入口）
database.py            全部 SQL 与表迁移（init_db 两段式：先 DDL 建表，再 DML 补种子）
ai_service.py          AI 记账 / 意图识别 / 截图识别
templates/
  index.html           主应用（五个页面都在这一份里，靠 .page 切换）
  admin.html           通知发布台
static/
  script.js            前端主逻辑（渲染、交互、状态管理）
  charts-v013.js       图表看板（独立脚本，切到该页才懒加载）
  auth-v012.js         JWT fetch 封装 + 登录遮罩
  style.css            全站样式（语义色令牌在 :root）
  service-worker.js    PWA 缓存
docs/                  见下
records.db             SQLite 数据库（不入库）
```

## 核心功能

- **记账**：手动 / AI 自然语言 / AI 截图识别，支持覆盖更新与纠错反馈（Few-Shot 记忆库）
- **分类**：两级分类，支出/收入严格隔离，可停用、可合并（合并只改分类，绝不动金额与余额）
- **账户**：分组管理、批量操作、合并、转账与手续费
- **往来与报销**：借入/借出、待报销/已报销进度
- **图表看板**：年/季/月/周四周期、趋势线、分类饼图、markLine 最高/最低/均值
- **多用户**：JWT 隔离，分类/账目/账户全部按 `user_id` 隔离；本机偏好（折叠、显隐）也按用户分开存
- **导入导出**：CSV / Excel，含截图与报销字段
- **通知中心**：草稿/发布 + 定时可见

## 开发纪律（很重要）

完整规则见 `docs/HANDOFF.md`，这里列最容易踩的几条：

1. **任何账单增删改都必须联动 `accounts.balance`**，只改 `records` 会让余额对不上
2. **改 UI 后必须同步改旧测试断言**——`temp/` 下的老测试会断言 HTML/CSS 字面量
3. **全站禁用 `alert()`**，统一 Toast；弹窗 Enter 提交、Esc 关闭；文案全中文
4. **CSS 同权重靠文件末尾覆盖**，深色主题补丁写在后面才生效
5. **测试脚本、截图一律放 `D:\Project\temp\`**，禁止写进项目目录，并在 `temp/index.md` 建索引
6. **自动化测试不得盲删真实数据**，用唯一备注定位测试数据并在结束后清理
7. 分类网格点击后**不要重建 DOM**（只切 `.is-active`），否则 `event.target` 被摘出文档，外部点击监听会误收浮层

## 自测

```bash
.\venv\Scripts\python.exe -m py_compile app.py database.py ai_service.py
node --check static/script.js
node --check static/charts-v013.js

# 接口级回归（脚本在 D:\Project\temp\）
.\venv\Scripts\python.exe D:\Project\temp\test_v0131_iso.py      # 分类隔离 49 项
.\venv\Scripts\python.exe D:\Project\temp\test_v0131_t05_api.py  # 停用/合并 67 项
```

界面级验证走真实 Chrome CDP（项目无 Playwright），范式见 `D:\Project\temp\final_common.py`
与 `D:\Project\temp\cdp_v0132_ui.py`。

## 文档

| 文件 | 用途 |
|---|---|
| `docs/HANDOFF.md` | **最高红线规则** + 数据模型 + API 速查 + 已知坑 |
| `docs/dev-log.md` | 每个版本的技术路径与测试结果 |
| `docs/archive/prd-v0131.md` | v0.13.1 增量需求（已归档） |
| `docs/archive/design-v0131.md` | v0.13.1 增量设计（含任务列表 T01–T05，已归档） |
| `docs/prompts/NN-*.md` | 每版的需求背景 / 核心 Prompt / 方案 / 踩坑结论 |
| `docs/video-script.md` | 演示视频剧本 |
| `docs/bugs-and-solutions/` | 历史 Bug 与解法 |

## 版本

当前 `v0.13.1-DEV`（已打 tag），其上的前端体验优化改动未发版、静态资源版本串为 `0.14.0`。
版本显示的优先级是 Git Tag > `APP_VERSION_FALLBACK`。

> 本机暂连不上 GitHub，网络恢复后需要 push main 与全部历史 tag。
