# 01 · Flask 骨架与健康检查（Prompt 快照）

> 快照时间：2026-10-25
> 对应提交：`chore: 初始化项目配置（虚拟环境与依赖声明）` + `feat: 首页与健康检查接口 + 内存版账目接口`（本快照只取其中骨架部分）

## 一、这一步要解决什么

继承项目时机器是空的：没有 Python、没有 `venv`、没有 `app.py`、没有 `.git`。
这一步只干一件事——**让一个 Web 服务先跑起来**，并且肉眼能确认三件事：

- 服务能启动、端口能访问；
- 框架、模板、JSON 全链路没问题；
- 中文不乱码（Windows 默认 GBK，这是最容易翻车的地方）。

因此只保留两个探针路由，不碰任何业务数据。

## 二、用户原始 Prompt（要点摘录）

以下为开场指令与《AI记账管家-会话启动包》第 1 步要求的概括（非逐字）：

> 「以 Python Flask 开发导师的身份带我做一个记账 Web 应用，分步走，每次只推进一小步。只给我代码、运行命令、验证命令，不要解释项目结构，也不要输出后续规划。」

> 「第 1 步：把 Flask 骨架搭起来，能在浏览器访问首页，中文不乱码。先能跑，再优化。」

技术栈在这一步被锁死：**Flask 单文件 + SQLite + 原生 HTML/CSS/JS**，明确排除工厂函数、Blueprint、SQLAlchemy 和任何额外依赖。

## 三、AI 给出的方案要点

### `app.py`（单文件，无工厂函数）

| 位置 | 写法 | 为什么 |
| --- | --- | --- |
| 应用实例 | `app = Flask(__name__)` | 模块级唯一实例，单文件阶段不需要 `create_app()` |
| 中文输出 | `app.json.ensure_ascii = False` | Flask 2.3+ 的写法，避免 `jsonify` 把中文转成 `\uXXXX`，便于肉眼核对 |
| 首页 | `GET /` → `jsonify(status="ok", project="AI记账管家")` | 探针：能看到项目名就说明服务活着、编码正确 |
| 健康检查 | `GET /health` → `jsonify(health="good")` | 给部署平台/监控轮询用的稳定契约，后续不改 |
| 启动 | `app.run(debug=True)` | 开发期热重载，改完代码自动重启 |

### `requirements.txt`

```
flask>=3.0
```

只用下界不用精确锁版本：开发期要能吃到补丁，比赛提交前再锁。

## 四、验证记录（实跑）

| 请求 | 返回 |
| --- | --- |
| `GET /` | `{"project": "AI记账管家", "status": "ok"}` |
| `GET /health` | `{"health": "good"}` |

关键断言：返回体里中文是原样汉字，没有出现 `\u8bb0\u8d26` 这类转义。

## 五、踩坑与结论

- **`python` 命令不可用**：装 Python 之前，`python` 指向 `C:\Users\19370\AppData\Local\Microsoft\WindowsApps\python.exe` 这个商店占位符，执行直接报 `Python was not found`。详见 `docs/bugs-and-solutions.md` 坑 3。
- **`curl` 不是 curl**：Windows PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，不支持 `-X`，写测试命令必须用 `curl.exe`。
- **`Invoke-WebRequest` 在本环境会抛异常**：非交互模式下 POST 报「Windows PowerShell 处于非交互模式」，所以后续所有接口验证统一走 `curl.exe`。
- 结论：先把「能访问、不乱码」这件事钉死，后面接数据库、接前端才有稳定的地板。
