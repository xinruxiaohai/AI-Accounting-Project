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
