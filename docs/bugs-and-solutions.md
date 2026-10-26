# 踩坑与解决方案

> 记录今天真实卡住过的坑，格式统一为「问题表现 → 排查过程 → 解决方案」。
> 每条都附上能直接复制的命令，下次再遇到照抄即可。

---

## 坑 1：终端切盘失败（`cd` 与 `cd /d` 的区别）

**问题表现**

在命令提示符里执行 `cd D:\AI` 之后，提示符依然停在 `C:\Users\19370>`，
后续所有命令仍在 C 盘执行，于是报「系统找不到指定的路径」或者干脆把文件建到了错误位置。

**排查过程**

1. 先看提示符：`C:\Users\19370>` 说明当前是 **cmd.exe**，不是 PowerShell（PowerShell 长这样 `PS C:\Users\19370>`）。
2. 再单独测试：`cd D:\AI` 不报错，但 `cd` 单独执行后显示的仍是 `C:\Users\19370` —— 命令没生效却也不报错，是典型的「只切了盘内目录」。
3. 根因：cmd 的 `cd`（`chdir`）**只改当前驱动器的当前目录，不切换驱动器**，所以 `cd D:\AI` 实际被理解成「在当前盘找一个叫 `D:\AI` 的相对路径」，静默失败。

**解决方案**

```bat
:: cmd.exe：必须加 /d 才会换盘
cd /d D:\AI
```

```powershell
# PowerShell：cd 可以直接换盘，两条等价
cd D:\AI
Set-Location D:\AI
```

**记住的分辨方法**：看提示符有没有 `PS` 前缀。`cd /d` 只在 cmd 里合法，在 PowerShell 里会报「位置参数过多」。

---

## 坑 2：Git root-commit 导致 `HEAD~1` 报错死循环

**问题表现**

想撤销上一个提交重做，执行：

```
git reset --soft HEAD~1
fatal: ambiguous argument 'HEAD~1': unknown revision or path not in the working tree.
```

于是改用更暴力的 `git update-ref -d HEAD` 删掉引用，再想清暂存区：

```
git restore --staged .
fatal: could not resolve 'HEAD'
```

两个命令连环失败，仓库卡在「有暂存内容、没有 HEAD」的中间态，看起来怎么都退不回去。

**排查过程**

1. `git log --oneline` 只有一个提交 —— 这是仓库的**第一个提交（root commit）**，它没有父提交，所以 `HEAD~1` 天然不存在，报错是正常的，不是仓库坏了。
2. `git update-ref -d HEAD` 把 `refs/heads/main` 这个**引用本身**删了，此时 `HEAD` 指向一个不存在的分支，于是所有「相对 HEAD」的命令（`restore --staged`、`commit`、`diff`）全部失效。
3. 结论：root commit 阶段不存在「退回上一个提交」的概念，也不该用 `update-ref -d` 这种底层命令。

**解决方案**

方案 A（推荐，最省事）：仓库还不值钱时直接重来，历史最干净。

```powershell
Set-Location D:\Project\AI-Accounting-Project
Remove-Item -Recurse -Force .git
git init -b main
git add .gitignore requirements.txt
git commit -m "chore: 初始化项目配置（虚拟环境与依赖声明）"
# ……再按需要逐个提交
```

方案 B：只是想把文件从暂存区拿回来，不动提交历史（在 HEAD 正常情况下用这个）。

```powershell
git restore --staged .        # HEAD 正常时可用
git rm -r --cached .          # HEAD 被删掉、restore 报错时的替代方案
```

**教训**

- 想「把一个大提交拆成几个小提交」，正确做法是 `git reset --soft HEAD~1`（有父提交时）或**直接重开仓库**，不要用 `update-ref` 这类底层命令。
- 拆分提交前先确认 `git log --oneline` 里至少有 2 个提交，否则 `HEAD~1` 一定失败。

---

## 坑 3：Windows 商店占位符导致 `python` 找不到

**问题表现**

```
python -V
Python was not found; run without arguments to install from the Microsoft Store,
or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.
```

`python` 命令存在但不干活，`pip`、`python -m venv` 全部连带失效。

**排查过程**

1. `Get-Command python` 显示来源是 `C:\Users\19370\AppData\Local\Microsoft\WindowsApps\python.exe`。
2. 这个路径不是真的 Python，而是 Windows 的**应用执行别名（App Execution Alias）占位符**：0 字节的中转程序，作用是把命令转发给微软商店。
3. `Get-Command py` 同样不可用 → 机器上确实没装 Python，不是 PATH 顺序问题。
4. 装完之后仍然要注意：`Get-Command python` 在某些已经打开的终端里仍指向占位符，因为**进程的 PATH 是启动时继承的快照**，注册表改了它不会自动更新。

**解决方案**

1. 安装（用户级，不需要管理员）：

```powershell
winget install --id Python.Python.3.12 --scope user
```

2. 装好后**新开一个终端**再验证：

```powershell
python -V          # 期望 Python 3.12.10
py -V              # py launcher 也应可用
Get-Command python # Source 应为 ...\Programs\Python\Python312\python.exe
```

3. 如果还是指向占位符，两个选择：

```powershell
# 选择一：直接关掉商店别名占位（系统设置 → 应用 → 高级应用设置 → 应用执行别名 → 关闭 python.exe / python3.exe）
# 选择二：在旧终端里临时整体替换 PATH 后再验证
$env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
```

4. 项目内一律用 venv 里的解释器，绕开 PATH 问题：

```powershell
.\venv\Scripts\python.exe -V
.\venv\Scripts\python.exe app.py
```

**教训**

- 判断「Python 到底装没装」，看 `Get-Command python` 的 Source，不要只看 `python` 有没有报错。
- 装完软件必须新开终端，旧终端的 `$env:PATH` 不会刷新 —— 这一条对 Node、Java 同样成立。
- 项目里固定用 `venv\Scripts\python.exe`，可以彻底摆脱系统 PATH 的干扰。

---

## 坑 4：`<input type="number">` 存不下算式，输入像是「被吞了」

**问题表现**

想把金额框升级成「能敲 `15.5+20*2`、自动算出 55.5」，但只把 `<input type="number">` 拿来用，用户敲进去的 `+`、`*` 完全显示不出来，光标本该在框里闪，框里却是空的；`input.value` 读出来是 `""`。

**排查过程**

1. 不是 JS 清了值，也不是事件被拦：给框赋 `"55.5"` 能显示，赋 `"15.5+20*2"` 立刻变空。
2. 这是 HTML 规范的 **value sanitization algorithm**：`type="number"`（以及 `type="date"`）的 `value` 只保留「合法数字字符串」，赋一个不合法的字符串会被直接置为 `""`，不会报错、不会警告。
3. 同理，`min`/`max`/`step` 只在有合法数字时才生效，对算式毫无意义。

**解决方案**

1. 换成文本框，但用 `inputmode` 保住手机上的数字键盘：

```html
<input id="amount" type="text" inputmode="decimal" placeholder="25.50 或 15.5+20*2">
```

2. 计算交给 math.js，结果自己判类型与有限性（见坑 5）：

```javascript
const result = window.math.evaluate(expression);
if (typeof result !== "number" || !Number.isFinite(result) || result <= 0) {
  // 提示「算式算不出正数」
}
```

3. 纯数字时不进 math.js，直接用 `Number()`，避免 `0.1 + 0.2` 被算成 `0.30000000000000004` 这类浮点尾。

**教训**

- `type="number"` 不是「能输入数字的框」，而是「值必须是一个数的框」；要承载表达式、金额千分位、带单位的文本，一律用 `type="text"`。
- 只想要数字键盘时，`inputmode="decimal"` 是比 `type="number"` 更合适的手段。

---

## 坑 5：math.js 的 `evaluate("1/0")` 不抛错，返回 `Infinity`

**问题表现**

做了「算不出来就红字提示」的保护，`try/catch` 也写了，但 `1/0`、`0/0` 这类输入不会触发 catch，`= ¥Infinity` 直接显示出来；如果原样提交，`amount` 会变成 `Infinity`。

**排查过程**

在 Node 里直接试 math.js（13.2.3）：

```
evaluate("15.5+20*2")  → 55.5
evaluate("0.1+0.2")    → 0.30000000000000004
evaluate("alert(1)")   → throw: Undefined function alert
evaluate("1/0")        → Infinity        ← 不抛错
evaluate("0/0")        → NaN             ← 也不抛错
```

结论：math.js 的 `evaluate` 只保证「表达式能被解析成某个值」，**不保证这个值是合法金额**。除以零按 IEEE 754 得 `Infinity`，`0/0` 得 `NaN`。

**解决方案**

```javascript
let result;
try {
  result = window.math.evaluate(expression);
} catch (err) {
  return { ok: false, message: "算式写法有问题" };
}
if (typeof result !== "number" || !Number.isFinite(result) || result <= 0) {
  return { ok: false, message: "算式必须能算出一个大于 0 的金额" };
}
```

`Number.isFinite` 同时挡掉 `Infinity`、`-Infinity`、`NaN`（`isFinite(NaN)` 是 `false`），比 `!isNaN()` 更严。

**教训**

- 「没抛异常」不等于「结果可用」。计算类库的返回值必须再校验一次类型与取值范围。
- 用户输入进入后端之前，前端要把 `Infinity` / `NaN` 拦在本地 —— 它们能被 Python 的 `json.dumps` 输出成非标准 JSON（`Infinity` / `NaN`），前端 `JSON.parse` 会直接报 `Unexpected token`。

---

## 坑 6：自检脚本用 `records[0]` 定位「我刚创建的那条」，删掉了用户的真实账目

**问题表现**

前端自检脚本跑完，用户自己刚记的一条「早餐测试」（9.9 元、微信）消失了。删除接口本身没 bug，是脚本删错了对象。

**排查过程**

1. 脚本的写法是「POST 一条 → 拿 `GET /api/records` 的第一条当刚建的那条 → 断言字段 → DELETE 掉」。
2. 那一轮 POST 其实失败了（桩子里的单选按钮没有 `value`，类型传成空串，后端回 400），`records[0]` 于是指向**列表最上面那条真实账目**（id=31「早餐测试」）。
3. 断言碰巧通过（字段看着都正常），`DELETE` 就把用户的数据删了。

**解决方案**

1. 自检造的数据必须带唯一标记，并用标记找回自己那一条，永远不靠下标：

```javascript
const note = `__selftest_${Date.now()}`;
await api("/api/records", jsonOptions("POST", { ...payload, note }));
const mine = state.allRecords.find((r) => r.note === note);
```

2. POST 之后先断言状态码是 201、再断言 `mine` 存在，两者都成立才继续后面的删除步骤。
3. 已经删错了就立刻按原内容重建（这次是用原 `amount/category_id/account/date/note` 重新 POST 了一条，id 31 → 32），并在文档里写清楚。

**教训**

- 「列表第一条」在真实数据库上永远是别人的数据，不是你的测试数据。
- 会写数据库的自检脚本，等价于生产代码：定位、断言、清理三步都要按「数据可能不是我的」来设计。
