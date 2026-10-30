# v0.12.5 Prompt 快照：密码弹窗化、图标选择器重排与 UID

## 需求背景
用户验收时 123456 登不进去（迁移后密码被测试改过）；设置页里平铺的改密三连输入框让浏览器自动填充旧密码，
既难看也危险；图标选择器被塞进 flex 行里宽度被压缩、文字重叠；侧边栏看不出自己是谁、也无法验证 1-9 预留。

## 核心 Prompt（用户原话摘要）
1. 强制把 1937097795@qq.com 密码重置为 123456（werkzeug 哈希写库）。
2. 删掉平铺的旧/新/确认密码输入框，只留【修改密码】按钮，点开独立 Modal，输入框加
   autocomplete="off"/"new-password" 禁止自动填充。
3. 重写图标个性化 UI：Grid/Flex 布局，格子大小一致、间距合理、文字不溢出，深浅色都好看。
4. 在设置页或侧栏昵称旁显示 UID（如 UID: 1），验证 1-9 号预留。
5. 详细汇报每处改动与操作路径。

## 方案简述
- 密码哈希直接用 werkzeug generate_password_hash 写库，绕开强密码校验（初始密码是系统预置）。
- 改密 Modal 用 Bootstrap；shown.bs.modal 时清空三个输入并清错误；旧密码框用 autocomplete=off + 随机 name
  双保险；成功后 bootstrap.Modal.getInstance().hide()。
- 图标选择器：HTML 从 .settings-inline 拆出，.icon-picker-row 用 grid 1fr 1fr；格子 grid-auto-rows 固定 82px，
  label 单行 ellipsis；深色用 [data-theme="dark"] 覆盖背景与边框。
- UID 用 user.id（auth-v012.js 的 getUser），侧栏 .sidebar-uid 胶囊，设置页拼进账号行。

## 踩坑结论
- 同权重 CSS 后写覆盖：.sidebar-user 早期颜色暗，必须把高对比规则放文件末尾。
- 旧测试断言了已删除的 DOM（settings-old-password），UI 重构要同步改测试，否则回归永远红。
- 图标格子被父级 flex 压缩是“文字重叠”的根因，单改 CSS 不够，必须把网格移出 flex 容器。
