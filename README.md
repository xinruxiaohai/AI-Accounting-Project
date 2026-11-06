# 智汇账 (SmartLedger) - 基于多模态大模型的 AI 资产管家

一个本地部署的多用户资产管家：手动记账、AI 自然语言/截图识别入账、多账户与往来账、投资持仓、图表看板、多用户隔离。

后端 Flask + sqlite3，前端原生 JS/CSS + Bootstrap 5 + ECharts，无构建步骤，起服务即用。

> **在线体验网址**：http://8.134.12.135/
> **演示视频链接**：[点击前往 B站观看](https://www.bilibili.com/video/BV1aX4B6vEfx?vd_source=5914eac080f474acab298d78b3c7e61a)

## 🚀 10 分钟极速复现指南

### 1. 环境准备
- 确保已安装 **Python 3.10+** 及 **Git**。
- 准备一个智谱 AI 的 API Key（用于 AI 记账功能，选填）。

### 2. 克隆代码与安装依赖
打开终端，依次执行以下命令：

```bash
# 1. 克隆仓库
git clone https://github.com/xinruxiaohai/AI-Accounting-Project.git
cd AI-Accounting-Project

# 2. 创建并激活虚拟环境
python -m venv venv

# Windows 激活：
.\venv\Scripts\activate

# Mac/Linux 激活：
source venv/bin/activate

# 3. 安装依赖清单
pip install -r requirements.txt
```

### 3. 配置环境变量 (`.env` 模板)
在项目根目录新建 `.env` 文件（AI 相关 Key 可选，缺了只是 AI 记账不可用）：

```env
ZHIPU_API_KEY=你的智谱API_Key
# 如需邮箱验证码功能，请填入 SMTP 配置
MAIL_SERVER=smtp.qq.com
MAIL_PORT=465
MAIL_USER=你的邮箱@qq.com
MAIL_PASSWORD=你的邮箱授权码
```
**注意**：`.env` 换 Key 后必须彻底结束旧 Flask 进程再启动，否则读的还是旧的。

### 4. 启动与体验
打开终端，执行：

```bash
python app.py
```

打开浏览器访问 http://127.0.0.1:5000 。首次启动会自动建库 `records.db` 并写入默认分类。

---

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

```text
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
- **投资**：接入东方财富免鉴权 API 实现股票基金搜索，持仓联动总资产重算
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

界面级验证走真实 Chrome CDP（项目无 Playwright），范式见 `D:\Project\temp\final_common.py` 与 `D:\Project\temp\cdp_v0132_ui.py`。

## 文档

| 文件 | 用途 |
|---|---|
| `docs/HANDOFF.md` | **最高红线规则** + 数据模型 + API 速查 + 已知坑 |
| `docs/dev-log.md` | 每个版本的技术路径与测试结果 |
| `docs/tech-report.md` | **比赛技术报告 (架构设计与意图控制)** |
| `docs/archive/prd-v0131.md` | v0.13.1 增量需求（已归档） |
| `docs/archive/design-v0131.md` | v0.13.1 增量设计（已归档） |
| `docs/prompts/NN-*.md` | 每版的需求背景 / 核心 Prompt / 方案 / 踩坑结论 |
| `docs/video-script.md` | 演示视频剧本 |
| `docs/bugs-and-solutions/` | 历史 Bug 与解法 |

## 版本

当前 `v0.14.0-TST`（比赛交付版），静态资源版本串为 `0.14.0`。
版本显示的优先级是 Git Tag > `APP_VERSION_FALLBACK`。
