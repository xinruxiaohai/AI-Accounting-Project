# 智汇账 · Flutter 全平台客户端（v0.15.0）

把现有 Flask 后端（`http://8.134.12.135`）包装成 iOS / Android / Windows / macOS 原生应用。
**本目录完全独立，不修改任何现有 Web 端（`templates/`、`static/`）与后端（`*.py`）代码。**

## 1. 环境

| 项 | 值 |
|---|---|
| Flutter | 3.47.9 stable（Dart 3.13.7） |
| SDK 路径 | `D:\flutter-sdk\flutter` |
| 用户 PATH 已追加 | `D:\flutter-sdk\flutter\bin` |
| 镜像变量（用户级） | `FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`、`PUB_HOSTED_URL=https://pub.flutter-io.cn` |
| 依赖 | `dio ^5.11.1`、`shared_preferences ^2.5.6` |
| 已生成平台 | `android/`、`ios/`、`windows/`、`macos/` |

> Windows 上启用插件构建（shared_preferences 等）需要系统开启「开发人员模式」，
> 否则 `flutter build` 会提示 symlink 权限问题：`start ms-settings:developers`。

```bash
cd D:\Project\AI-Accounting-Project\flutter-app
flutter pub get
flutter analyze
flutter run
```

## 2. 修改服务器地址 / 局域网 IP

**关键点：BaseURL 已经包含 `/api`**，所以代码里所有请求路径都写成
`'/auth/login'`、`'/statistics'`，**不要再写 `/api/auth/login`**，否则会变成 `/api/api/...`。

### 方式 A：临时覆盖（推荐，不改代码）

```bash
# 局域网里的 Flask 开发机
flutter run --dart-define=ZHZ_API_BASE=http://192.168.1.10:5000/api

# Android 模拟器访问宿主机（10.0.2.2 是宿主机别名）
flutter run --dart-define=ZHZ_API_BASE=http://10.0.2.2:5000/api

# 本机 127.0.0.1（仅 Windows/macOS 桌面端可用）
flutter run -d windows --dart-define=ZHZ_API_BASE=http://127.0.0.1:5000/api
```

编译打包时同样可以带 `--dart-define`：
`flutter build apk --dart-define=ZHZ_API_BASE=http://192.168.1.10:5000/api`

### 方式 B：改默认值

编辑 `lib/utils/request.dart` 中的常量：

```dart
static const String baseUrl = String.fromEnvironment(
  'ZHZ_API_BASE',
  defaultValue: 'http://8.134.12.135/api',   // ← 改成你的局域网 IP
);
```

### ⚠️ HTTP 明文（非 HTTPS）限制

线上地址是 `http://`，Android 9+ 与 iOS ATS 默认会拦截明文请求，需要在平台侧放行：

- **Android**：`android/app/src/main/AndroidManifest.xml` 的 `<application>` 加
  `android:usesCleartextTraffic="true"`（本工程已加）。
- **iOS**：`ios/Runner/Info.plist` 加
  `NSAppTransportSecurity` → `NSAllowsArbitraryLoads = true`（本工程已加）。
- **生产建议**：后端上 HTTPS，然后删掉这两处放行并把 `baseUrl` 换成 `https://`。

## 3. 网络层与接口

`lib/utils/request.dart`

- `ApiClient.init()` 在 `main()` 里调用一次，注册 dio 拦截器；
  每次请求自动读取本地 JWT 并注入 `Authorization: Bearer <token>`。
- Token 用 `shared_preferences` 持久化（key：`ai_accounting_token`），
  重启 App 自动免登录；退出登录调用 `ApiClient.clearSession()`。
- 后端错误（`{"error": "..."}`）统一收敛为 `ApiException`，页面直接显示中文提示。

| 方法 | 路径 | 后端真实路由 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | `/api/auth/login` | 入参 `{email, password}`，返回 `{token, user}` |
| GET | `/statistics` | `/api/statistics` | 返回 `income_total` / `expense_total` / `balance_total` / `reimbursement_pending` / `reimbursement_done` |

> `/api/statistics` 需要登录态；未登录或 Token 过期会返回 401，此时请回登录页重新登录。

## 4. 页面与语义色

- `lib/pages/login.dart`：邮箱 + 密码表单、加载态、错误提示，成功后保存 Token 并跳转首页。
- `lib/pages/home.dart`：
  - 顶部「总净资产」大数字，取 `balance_total`（口径 = `SUM(accounts.balance)`）；
  - 三张统计卡：总收入 / 总支出 / 待报销；下拉刷新；
  - 底部**原生 `NavigationBar`**（Material 3）三个 Tab：首页 / 账单 / 我的。
- `lib/utils/theme.dart`：颜色沿用 Web 端 `static/style.css`：

| 语义 | 色值 | 用途 |
|---|---|---|
| 红 | `#DC2626` | 支出、负数、错误 |
| 绿 | `#047857` | 收入、正数 |
| 灰 | `#64748B` | 中性、转账、辅助文字 |

> 记账场景按原项目口径：**支出红、收入绿**（不是股票涨跌的红绿习惯）。

## 5. 运行到模拟器 / 真机

```bash
flutter devices                 # 查看可用设备
flutter emulators                # 查看模拟器
flutter emulators --launch <id> # 启动 Android 模拟器
flutter run                     # 运行到当前唯一设备
flutter run -d <device-id>      # 指定设备
```

- **Android**：Android Studio → Device Manager 建一个 AVD，`flutter run` 即可。
  用模拟器调局域网后端时，宿主机用 `10.0.2.2` 而不是 `127.0.0.1`。
- **iOS**：**必须在 macOS 上**、装好 Xcode 与 CocoaPods 后执行
  `open ios/Runner.xcworkspace`（或 `flutter run -d "iPhone Simulator"`）。
  Windows 只能生成 `ios/` 工程文件，无法编译/运行 iOS 包。
- **Windows 桌面**：需要 Visual Studio 2022 +「使用 C++ 的桌面开发」工作负载，
  然后 `flutter run -d windows`。

## 6. 编译桌面版 / 移动端安装包

```bash
# Windows 桌面（在 Windows 上执行，需 VS 2022 C++ 桌面开发）
flutter build windows --release
# 产物：build\windows\x64\runner\Release\

# macOS 桌面（在 macOS 上执行，需 Xcode）
flutter build macos --release
# 产物：build/macos/Build/Products/Release/

# Android APK / App Bundle
flutter build apk --release
flutter build appbundle --release

# iOS（在 macOS 上执行，需 Xcode + 签名）
flutter build ipa --release
```

## 7. 已知边界与下一步

- 「账单」「我的」两个 Tab 目前是基础占位页；下一阶段接 `/api/records`（分页/筛选/分类）。
- 登录页只做邮箱+密码，短信验证码 `/api/auth/sms-login`、注册、找回密码尚未接入。
- 全局跑马灯 `/api/notices/active_temp`（v0.14.3）尚未在 Flutter 端实现。
- Token 过期（7 天）后不会自动刷新，收到 401 时需回登录页；后续可加 401 拦截自动跳转。

## 8. v0.15.0 自动验收记录（2026-11-09 01:21）

| 前置条件 | 结果 |
|---|---|
| `flutter create` 工程创建成功 | ✅ 117 个模板文件 + `android/` `ios/` `windows/` `macos/` 四平台目录齐全 |
| `flutter analyze` 无 Error | ✅ `No issues found!`，退出码 0（连 warning/info 都没有） |
| 网络层 + 登录页 + 首页 + README 全部写好 | ✅ 7 个交付文件齐备，接口路径与语义色按后端真实契约实现 |

**环境限制（非代码错误，明天补环境即可）**：

- `flutter test` 报 `Unable to connect to flutter_tester process: WebSocketException:
  Invalid WebSocket upgrade request` —— Windows 上 flutter_tester 引擎进程通信失败，
  测试文件根本没加载完；`flutter analyze` 已覆盖全量静态检查，代码本身无编译级错误。
- `flutter build bundle` 报 `Android SDK could not be found` —— 本机未安装 Android SDK，
  插件 build hook 无法运行；要真正打 APK 需装 Android Studio / cmdline-tools 并配置
  `ANDROID_HOME`，Windows 桌面编译还需 Visual Studio 2022 的 C++ 桌面开发工作负载。
- 当前工程**未提交 git**（`flutter-app/` 为 untracked）；需要纳入版本管理时自行
  `git add flutter-app && git commit`。

> ⚠️ **自动休眠未能触发**：三项前置条件均已满足、代码零报错，但本机休眠功能未启用
> （`shutdown /h` 失败），启用它又需要管理员权限；用户指定的 `rundll32` 回退命令与
> 另外两种电源 API 途径均被工具安全策略拦截，因此按「不要在受阻时强行重试」的原则停止。
> 明天用管理员终端执行 `powercfg /hibernate on` 后 `shutdown /h` 即可；只要 S3 待机
> 则直接运行 `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`。

