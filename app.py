import base64
import datetime
import difflib
import functools
import hashlib
import hmac
import io
import json
import os
import random
import re
import secrets
import smtplib
import subprocess
import time
import uuid

import jwt
from flask import (
    Flask,
    Response,
    g,
    jsonify,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
)
from dotenv import load_dotenv
from email.message import EmailMessage
from email.utils import formataddr
# v0.14.1：密码哈希统一收口到 security.py（Werkzeug 加盐哈希 + 老哈希兼容升级）。
# check_password_hash 这个名字故意保留，让下面 4 处调用一行都不用动，
# 但实际指向兼容版 verify_password —— 老 SHA256 账号也能正常登录并被静默升级。
import security

generate_password_hash = security.generate_password_hash
check_password_hash = security.verify_password

import ai_service
import cache_ext
import database
import invest_eastmoney
import invest_mock
import sqlalchemy_db

app = Flask(__name__)

# 让 jsonify 直接输出中文，而不是 \uXXXX 转义，方便浏览器里肉眼检查
app.json.ensure_ascii = False

# v0.14.1：SimpleCache 进程内缓存，必须在第一个请求之前 init_app
cache_ext.init_cache(app)

# 通知里的配图统一存这里，用 /static/uploads/<uuid>.<ext> 访问
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
# 用户头像独立子目录：与账单截图 / 通知配图隔离，避免被截图清理逻辑误删
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)

# .env 必须在这里显式加载：MAIL_* 等配置要在读取前就位，
# 不依赖 ai_service 导入时的副作用（否则调整 import 顺序就会静默变回未配置）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

# 启动就建表 / 升级表结构。表已存在时 CREATE TABLE 会跳过，缺列时自动补列
database.init_db()

# ---------------- 全站访问密码（v0.11.1） ----------------

# 这些接口在没验证密码时也要能访问：问配置、交密码换 token
ACCESS_PUBLIC_PATHS = {"/api/access/config", "/api/access/verify"}

# v0.11.3：密码只管后台。用户端（首页 / 资产 / 账单 / 我的）的读写接口全部免密，
# 只有下面这些后台接口才要求 token：
#   /api/access/*        设置面板（config / verify 除外）
#   /api/upload          后台发通知时传封面图
#   /api/notifications*  写操作与 ?include=drafts 的草稿列表（已发布列表对用户公开）
ACCESS_PROTECTED_PREFIXES = (
    "/api/access/",
    "/api/notifications",
    "/api/upload",
    # v0.11.4：AI 记忆库属于后台管理数据，只有管理端看得到
    "/api/ai-memory",
    # v0.11.5：AI 纠错审计日志同样只在后台「纠错与反馈中心」展示
    "/api/ai-correction-log",
)


def _needs_access(path, method):
    """这个接口是否需要访问密码。只保护后台，用户端一律放行。"""
    if path in ACCESS_PUBLIC_PATHS:
        return False
    if path.startswith("/api/notifications"):
        # 用户端只看已发布列表；草稿与增删改都属于后台
        if method == "GET" and "include" not in request.args:
            return False
        return True
    return any(path.startswith(prefix) for prefix in ACCESS_PROTECTED_PREFIXES)

# 改密码 / 删密码 / 调超时，要求最近 5 分钟内验证过密码
ACCESS_REAUTH_MINUTES = 5


def _request_access_token():
    return (request.headers.get("X-Access-Token") or "").strip()


def _fresh_admin_check(data):
    """敏感设置的安全校验：刚输过密码才放行。

    顺序：没设密码直接放行 → 请求里带了 fresh_password 就现场比对 →
    否则看 X-Access-Token 的年龄是不是在 5 分钟以内。
    返回 None 表示放行，否则返回 (jsonify, status) 错误响应。
    """
    config = database.get_access_config()
    if not config["protected"]:
        return None

    fresh = data.get("fresh_password") if isinstance(data, dict) else None
    if isinstance(fresh, str) and fresh:
        if database.verify_access_password(fresh):
            return None
        return jsonify(error="当前密码不正确", code="access_denied"), 401

    if database.check_access_session(_request_access_token(), ACCESS_REAUTH_MINUTES):
        return None
    return jsonify(error="为了安全，请先重新输入当前密码", code="reauth_required"), 401


@app.before_request
def _access_guard():
    """v0.11.3：设了密码也只拦后台接口；用户端页面完全免密。"""
    if request.method == "OPTIONS":
        return None

    path = request.path
    if not path.startswith("/api/") or not _needs_access(path, request.method):
        return None

    config = database.get_access_config()
    if not config["protected"]:
        return None

    if database.check_access_session(_request_access_token(), config["timeout_minutes"]):
        return None

    return jsonify(error="需要输入访问密码", code="access_required"), 401


# ---------------- 多用户账号与 JWT 鉴权（v0.12） ----------------

def _resolve_jwt_secret():
    """签名密钥：环境变量 > 本地持久化的随机强密钥（v0.14.0-TST 安全加固）。

    不再硬编码默认值。未配置 JWT_SECRET 时首次启动用 secrets.token_hex(32)
    生成并原子写入 .jwt_secret（已被 .gitignore 忽略），保证 Gunicorn 多
    worker 与服务重启后密钥一致，已签发的登录态不会集体失效。
    """
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if env_secret:
        return env_secret
    secret_file = os.path.join(BASE_DIR, ".jwt_secret")
    try:
        with open(secret_file, "r", encoding="utf-8") as fh:
            saved = fh.read().strip()
        if saved:
            return saved
    except OSError:
        pass
    generated = secrets.token_hex(32)
    try:
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(generated)
    except FileExistsError:
        try:
            with open(secret_file, "r", encoding="utf-8") as fh:
                return fh.read().strip() or generated
        except OSError:
            return generated
    except OSError:
        return generated
    return generated


JWT_SECRET = _resolve_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_SECONDS = 7 * 24 * 3600

# 登录/注册本身和访问密码查询不要求 JWT；已发布通知允许游客看
AUTH_PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/sms-login",
    "/api/auth/send-code",
    "/api/auth/verify-code",
    "/api/auth/reset-password",
    "/api/access/config",
    "/api/access/verify",
    "/api/version",
}


def _bearer_token():
    """从 Authorization: Bearer <token> 里取 JWT，没有就返回空串。"""
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def _issue_token(user):
    """签发 JWT：sub 是用户 id，7 天有效；绝不把密码哈希放进 Token。"""
    now = datetime.datetime.utcnow()
    payload = {
        # PyJWT 2.15 要求 sub 必须是字符串，解码后再转回 int
        "sub": str(int(user["id"])),
        "email": user["email"],
        "iat": now,
        "exp": now + datetime.timedelta(seconds=JWT_EXPIRES_SECONDS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _user_from_token(token):
    """解 JWT 并回表取用户；过期/伪造/用户已删都返回 None。"""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return database.get_user(user_id)


def _public_user(user):
    """对外只暴露 id / email / phone / created_at，绝不带 password_hash。"""
    if not user:
        return None
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "phone": user.get("phone") or "",
        "nickname": user.get("nickname") or "",
        "avatar": user.get("avatar") or "",
        "created_at": user.get("created_at") or "",
    }


@app.before_request
def _identity_guard():
    """v0.12：所有 /api/* 默认必须带合法 JWT，白名单除外。

    这里同时把 user_id 注入 database 的 contextvar，后面所有 SQL 都自动按用户隔离。
    """
    if request.method == "OPTIONS":
        return None

    path = request.path
    user = _user_from_token(_bearer_token())
    g.current_user = user

    # 游客看已发布通知：按 1 号管理员的通知列表展示（通知只有后台能写）
    if user is None and path == "/api/notifications" and request.method == "GET":
        database.set_current_user(1)
        return None

    if path in AUTH_PUBLIC_PATHS:
        # 登录/注册接口不需要身份；但上下文保持 0，避免误读他人数据
        database.set_current_user(user["id"] if user else 0)
        return None

    if path.startswith("/api/") and user is None:
        database.set_current_user(0)
        return jsonify(error="请先登录", code="auth_required"), 401

    database.set_current_user(user["id"] if user else 1)
    return None


def login_required(view):
    """装饰器版保护：路由内部再确认一次，防止被绕过 before_request。"""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("current_user") is None:
            return jsonify(error="请先登录", code="auth_required"), 401
        return view(*args, **kwargs)

    return wrapped


def _normalize_email(value):
    return (value or "").strip().lower()


def _password_strength_error(password):
    """v0.12.2 强密码：至少 6 位，且数字 / 字母 / 标点里至少占两种。返回错误文案或 None。"""
    if not isinstance(password, str) or len(password) < 6:
        return "密码至少 6 位"
    kinds = 0
    if re.search(r"[0-9]", password):
        kinds += 1
    if re.search(r"[A-Za-z]", password):
        kinds += 1
    if re.search(r"[^0-9A-Za-z]", password):
        kinds += 1
    if kinds < 2:
        return "密码需包含数字、字母、标点中的至少两种"
    return None


def _register_password_error(password):
    """v0.13.5 注册专用强校验：至少 8 位，且必须同时含字母和数字（纯数字直接拒绝）。

    刻意与 _password_strength_error 分开：改密 / 找回密码沿用旧规则，
    登录侧完全不校验强度，保证历史账号（初始口令见环境变量）能正常登录。
    """
    if not isinstance(password, str) or len(password) < 8:
        return "注册密码至少 8 位"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "注册密码不能是纯数字，需同时包含字母和数字"
    return None


# ---------------- v0.13.4：注册邮箱验证码（真实 SMTP + 数据库哈希） ----------------

EMAIL_CODE_TTL_SECONDS = 300          # 验证码 5 分钟过期
EMAIL_SEND_INTERVAL_SECONDS = 60      # 同一邮箱同一用途 1 分钟只能发一次（防刷）
EMAIL_CODE_MAX_ATTEMPTS = 5           # 尝试上限，超了作废须重新发

MAIL_SERVER = (os.getenv("MAIL_SERVER") or "smtp.qq.com").strip()
try:
    MAIL_PORT = int(os.getenv("MAIL_PORT") or 465)
except ValueError:
    MAIL_PORT = 465
MAIL_USER = (os.getenv("MAIL_USER") or "").strip()
MAIL_PASSWORD = (os.getenv("MAIL_PASSWORD") or "").strip()
# 是否真正配置了发信账号：决定「未配置→控制台兜底」还是「配置了却发不出去→报错」
MAIL_CONFIGURED = bool(MAIL_USER and MAIL_PASSWORD)

# v0.13.6：全局品牌名（邮件发件人显示名与标题前缀；页面文案在模板/前端里）
APP_BRAND_NAME = "智汇账"

# 验证码哈希加盐（pepper）：即使 DB 泄漏，也反推不出 6 位明文码
_EMAIL_HASH_PEPPER = JWT_SECRET


def _hash_email_code(code):
    """验证码只存哈希，永不存明文。"""
    return hashlib.sha256(
        ("%s:%s" % (_EMAIL_HASH_PEPPER, code)).encode("utf-8")
    ).hexdigest()


def _build_verification_email(email, code, purpose="register"):
    """拼装验证码邮件：纯文本 + HTML 双版本（HTML 用于邮件客户端渲染）。

    单独抽出来是为了不发信也能自测邮件结构（真实发信依赖 SMTP 凭据）。
    """
    action = "注册" if purpose == "register" else "找回密码"
    msg = EmailMessage()
    msg["Subject"] = "【%s】%s验证码" % (APP_BRAND_NAME, action)
    # 发件人显示名走 formataddr，否则中文显示名会被邮件客户端显示成乱码或整串丢弃
    msg["From"] = formataddr((APP_BRAND_NAME, MAIL_USER)) if MAIL_USER else APP_BRAND_NAME
    msg["To"] = email
    msg.set_content(
        "%s：您的%s验证码是 %s，%d 分钟内有效，请勿泄露给他人。"
        % (APP_BRAND_NAME, action, code, EMAIL_CODE_TTL_SECONDS // 60)
    )
    msg.add_alternative(
        '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
        "<h2>%s · %s验证码</h2>"
        "<p>您的验证码是：</p>"
        '<p style="font-size:28px;font-weight:bold;letter-spacing:6px">%s</p>'
        "<p>%d 分钟内有效，请勿泄露给他人。若非本人操作请忽略本邮件。</p></div>"
        % (APP_BRAND_NAME, action, code, EMAIL_CODE_TTL_SECONDS // 60),
        subtype="html",
    )
    return msg


def _send_verification_email(email, code, purpose):
    """用 QQ 邮箱 SMTP(465, SSL) 发 HTML 验证码邮件。返回 (是否发出, 错误信息)。

    MAIL_USER / MAIL_PASSWORD 未配置时降级为控制台打印（便于开发期自测），前端不回传明文。
    """
    if not MAIL_CONFIGURED:
        print(
            "[v0.13.4][邮箱验证码][未配置SMTP，仅控制台] %s -> %s（%d 秒内有效，用途=%s）"
            % (email, code, EMAIL_CODE_TTL_SECONDS, purpose),
            flush=True,
        )
        return False, "邮箱服务未配置（缺 MAIL_USER/MAIL_PASSWORD）"
    try:
        msg = _build_verification_email(email, code, purpose)
        with smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            server.login(MAIL_USER, MAIL_PASSWORD)
            server.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001 - 由调用方决定如何处置（已配置却失败会作废验证码并回 502）
        return False, str(exc)


def _verify_email_code(email, code, purpose="register"):
    """校验邮箱验证码并一次性消费，返回 (是否通过, 错误信息)。

    v0.13.4：改为数据库存储（哈希值），校验过期 / 次数超限 / 哈希匹配，成功即失效。
    v0.12.2：验证码带用途（register 注册 / reset 找回密码），拿注册码去改密会被拒绝。
    """
    row = database.get_email_code(email, purpose)
    if row is None:
        return False, "请先获取邮箱验证码"
    if time.time() > row["expires_at"]:
        database.consume_email_code(email, purpose)
        return False, "验证码已过期，请重新获取"
    if not code or not isinstance(code, str):
        return False, "验证码不正确"
    if not hmac.compare_digest(_hash_email_code(code.strip()), row["code_hash"]):
        attempts = database.register_email_code_attempt(email, purpose)
        if attempts >= EMAIL_CODE_MAX_ATTEMPTS:
            return False, "验证码错误次数过多，请重新获取"
        return False, "验证码不正确"
    database.consume_email_code(email, purpose)
    return True, None


@app.route("/api/auth/send-code", methods=["POST"])
def auth_send_code():
    """发送邮箱验证码（真实 SMTP）：6 位随机码，存哈希，5 分钟有效，1 分钟防刷。"""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="请输入正确的邮箱"), 400
    purpose = "reset" if (data.get("purpose") or "").strip() == "reset" else "register"
    exists = database.get_user_by_email(email) is not None
    if purpose == "register" and exists:
        return jsonify(error="该邮箱已注册，请直接登录"), 409
    if purpose == "reset" and not exists:
        return jsonify(error="该邮箱还没有注册"), 404

    # 防刷：同一邮箱同一用途 1 分钟内只能发一次
    if database.email_code_recent(email, purpose, EMAIL_SEND_INTERVAL_SECONDS):
        return jsonify(error="发送太频繁，请 1 分钟后再试"), 429

    code = "%06d" % secrets.randbelow(1000000)
    database.save_email_code(email, _hash_email_code(code), purpose, EMAIL_CODE_TTL_SECONDS)
    delivered, send_error = _send_verification_email(email, code, purpose)
    if not delivered and MAIL_CONFIGURED:
        # 配了 SMTP 却发不出去：别留一条用户永远收不到的码，先作废再如实报错
        database.consume_email_code(email, purpose)
        app.logger.warning("[v0.13.4][邮箱验证码][发送失败] %s: %s", email, send_error)
        return jsonify(error="验证码邮件发送失败，请稍后重试"), 502
    return jsonify(
        ok=True,
        expires_in=EMAIL_CODE_TTL_SECONDS,
        delivered=delivered,
        purpose=purpose,
    )


@app.route("/api/auth/verify-code", methods=["POST"])
def auth_verify_code():
    """校验邮箱验证码：过期 / 次数超限 / 哈希匹配，成功即失效（一次性）。"""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    code = (data.get("code") or "").strip() if isinstance(data.get("code"), str) else ""
    purpose = "reset" if (data.get("purpose") or "").strip() == "reset" else "register"
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="请输入正确的邮箱"), 400
    if not code:
        return jsonify(error="请输入验证码"), 400
    code_ok, code_error = _verify_email_code(email, code, purpose)
    if not code_ok:
        return jsonify(error=code_error), 400
    return jsonify(ok=True, message="验证码校验通过")


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    """注册：邮箱唯一、密码至少 6 位；id 由 users 表的自增序列决定（从 10 开始）。"""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    phone = (data.get("phone") or "").strip() if isinstance(data.get("phone"), str) else ""

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="请输入正确的邮箱"), 400
    strength_error = _register_password_error(password)
    if strength_error is not None:
        return jsonify(error=strength_error), 400
    if len(phone) > 30:
        return jsonify(error="手机号太长了"), 400
    nickname = (data.get("nickname") or "").strip() if isinstance(data.get("nickname"), str) else ""
    if len(nickname) > 20:
        return jsonify(error="昵称最多 20 个字"), 400

    code = (data.get("code") or "").strip() if isinstance(data.get("code"), str) else ""
    code_ok, code_error = _verify_email_code(email, code)
    if not code_ok:
        return jsonify(error=code_error), 400

    user, error_message = database.create_user(
        email, generate_password_hash(password), phone, nickname
    )
    if error_message is not None:
        return jsonify(error=error_message), 400

    database.seed_default_accounts_for(user["id"])
    # v0.13.1 A5：注册成功后立刻给新用户补齐默认分类模板（显式传 uid，绝不依赖 _uid()）。
    # A6b：注册是主流程，补齐失败只留控制台痕迹，不影响注册结果
    try:
        database.ensure_category_templates(user["id"])
    except Exception as exc:  # noqa: BLE001 - 静默兜底，注册本身必须成功
        print("[v0.13.1] 注册补齐默认分类失败（用户 %s）：%s" % (user["id"], exc), flush=True)
    return (
        jsonify(token=_issue_token(user), user=_public_user(user)),
        201,
    )


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """登录：校验邮箱 + 密码，成功返回 JWT 与用户信息（永不返回密码哈希）。"""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password") if isinstance(data.get("password"), str) else ""

    locked, locked_until, retry_after = database.get_login_lock(email)
    if locked:
        minutes = max(1, int((retry_after + 59) // 60))
        return (
            jsonify(
                error="密码错误次数过多，账号已锁定，请 %d 分钟后再试" % minutes,
                code="account_locked",
                locked_until=locked_until,
                retry_after=retry_after,
            ),
            423,
        )

    user = database.get_user_by_email(email)
    if user is None or not check_password_hash(user.get("password_hash") or "", password):
        fails, lock_until = database.record_login_failure(email)
        if lock_until:
            return (
                jsonify(
                    error="密码连续输错 %d 次，账号已锁定 %d 分钟"
                    % (database.LOGIN_MAX_FAILS, database.LOGIN_LOCK_MINUTES),
                    code="account_locked",
                    locked_until=lock_until,
                    retry_after=database.LOGIN_LOCK_MINUTES * 60,
                ),
                423,
            )
        remain = max(1, database.LOGIN_MAX_FAILS - fails)
        return jsonify(error="邮箱或密码不正确，还可尝试 %d 次" % remain, code="bad_password"), 401

    database.clear_login_failures(email)
    # v0.14.1：兼容策略 —— 老用户若仍是旧的简单 Hash（SHA256 等），
    # 在「登录成功」这一刻静默转成 Werkzeug 加盐哈希并落库。
    # upgrade_if_needed 内部吞掉所有异常，升级失败绝不阻断登录。
    security.upgrade_if_needed(
        user["id"],
        user.get("password_hash") or "",
        password,
        database.update_user_password,
    )
    return jsonify(token=_issue_token(user), user=_public_user(user))


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def auth_change_password():
    """登录态改密：校验旧密码 → 强密码校验 → 更新哈希并清空失败计数。"""
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password") if isinstance(data.get("old_password"), str) else ""
    new_password = data.get("new_password") if isinstance(data.get("new_password"), str) else ""
    confirm = data.get("confirm_password")

    # g.current_user 来自 get_user（故意不带密码哈希），校验旧密码要单独回表取
    user = database.get_user_by_email(g.current_user["email"])
    if user is None:
        return jsonify(error="用户不存在"), 404
    if not check_password_hash(user.get("password_hash") or "", old_password):
        return jsonify(error="旧密码不正确"), 400
    strength_error = _password_strength_error(new_password)
    if strength_error is not None:
        return jsonify(error=strength_error), 400
    if confirm is not None and confirm != new_password:
        return jsonify(error="两次输入的新密码不一致"), 400
    if check_password_hash(user.get("password_hash") or "", new_password):
        return jsonify(error="新密码不能和旧密码相同"), 400

    if not database.update_user_password(user["id"], generate_password_hash(new_password)):
        return jsonify(error="用户不存在"), 404
    database.clear_login_failures(user["email"])
    return jsonify(ok=True, message="密码已更新，请用新密码登录")


@app.route("/api/auth/reset-password", methods=["POST"])
def auth_reset_password():
    """忘记旧密码：邮箱验证码直接改密（验证码用途必须是 reset）。"""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    code = (data.get("code") or "").strip() if isinstance(data.get("code"), str) else ""
    new_password = data.get("new_password") if isinstance(data.get("new_password"), str) else ""
    confirm = data.get("confirm_password")

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="请输入正确的邮箱"), 400
    user = database.get_user_by_email(email)
    if user is None:
        return jsonify(error="该邮箱还没有注册"), 404
    strength_error = _password_strength_error(new_password)
    if strength_error is not None:
        return jsonify(error=strength_error), 400
    if confirm is not None and confirm != new_password:
        return jsonify(error="两次输入的新密码不一致"), 400
    code_ok, code_error = _verify_email_code(email, code, "reset")
    if not code_ok:
        return jsonify(error=code_error), 400

    if not database.update_user_password(user["id"], generate_password_hash(new_password)):
        return jsonify(error="用户不存在"), 404
    database.clear_login_failures(email)
    return jsonify(ok=True, message="密码已重置，请用新密码登录")


@app.route("/api/auth/profile", methods=["PUT"])
@login_required
def auth_update_profile():
    """改昵称（侧边栏展示用）；空值回退成邮箱前缀。"""
    data = request.get_json(silent=True) or {}
    nickname = data.get("nickname") if isinstance(data.get("nickname"), str) else ""
    if len(nickname.strip()) > 20:
        return jsonify(error="昵称最多 20 个字"), 400
    user = database.update_user_nickname(g.current_user["id"], nickname)
    if user is None:
        return jsonify(error="用户不存在"), 404
    return jsonify(user=_public_user(user))


@app.route("/api/auth/avatar", methods=["PUT"])
@login_required
def auth_update_avatar():
    """个人中心上传头像：先调 /api/upload 拿到 URL，再把 URL 记到当前用户。"""
    data = request.get_json(silent=True) or {}
    url = data.get("avatar") if isinstance(data.get("avatar"), str) else ""
    url = url.strip()
    if url and not url.startswith("/static/uploads/"):
        return jsonify(error="头像地址不合法"), 400
    user = database.update_user_avatar(g.current_user["id"], url)
    if user is None:
        return jsonify(error="用户不存在"), 404
    return jsonify(user=_public_user(user))


@app.route("/api/auth/avatar/upload", methods=["POST"])
@login_required
def auth_upload_avatar():
    """个人中心直接上传头像；不走受后台访问密码保护的 /api/upload。"""
    old_avatar = (g.current_user or {}).get("avatar") or ""
    url, error = _save_avatar_image(request.files.get("file"))
    if error:
        return jsonify(error=error), 400
    user = database.update_user_avatar(g.current_user["id"], url)
    if user is None:
        return jsonify(error="用户不存在"), 404
    # 上传成功后再清理旧头像文件，避免删了旧文件新文件却没落库
    if old_avatar and old_avatar != url:
        _delete_avatar_file(old_avatar)
    return jsonify(url=url, user=_public_user(user)), 201


@app.route("/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    """当前登录用户信息；前端路由守卫用它验 Token 是否还有效。"""
    return jsonify(user=_public_user(g.current_user))


@app.route("/api/auth/sms-login", methods=["POST"])
def auth_sms_login():
    """短信登录占位：接口先占住，等接短信服务商后再实现。"""
    return jsonify(error="短信登录即将上线，先用邮箱密码登录", code="not_implemented"), 501


def _parse_datetime(value):
    """把请求里的日期时间统一成「YYYY-MM-DD HH:MM」，返回 (字符串, 错误信息)。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), None

    if not isinstance(value, str):
        return None, "date 必须是字符串"

    text = value.strip()

    # 只有日期：补 00:00
    if len(text) == 10:
        try:
            parsed = datetime.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None, "date 不是合法日期，应形如 2026-10-26"
        return parsed.strftime("%Y-%m-%d %H:%M"), None

    # 带时间：四种常见写法都收，统一输出成「空格 + 到分钟」
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m-%d %H:%M"), None

    return None, "date 格式必须是 YYYY-MM-DD HH:MM（或只给 YYYY-MM-DD）"


def _resolve_category(data):
    """把请求里的分类解析成 (分类名, category_id, 错误响应)。

    两种写法都收：
    - 传 category_id：以分类表为准，名字由后端填（推荐，前端选二级分类时用这个）
    - 只传 category 文本：兼容老前端；分类表里没有这个名字就自动建成一级分类
    """
    category_id = data.get("category_id")
    if category_id is not None:
        # bool 是 int 的子类，先排掉 True/False
        if isinstance(category_id, bool) or not isinstance(category_id, int):
            return None, None, (jsonify(error="category_id 必须是整数"), 400)
        category = database.get_category(category_id)
        if category is None:
            # v0.13.1 A4：get_category 带 user_id 过滤，别人的分类在这里等价于「不存在」
            return None, None, (
                jsonify(error="category_id 对应的分类不存在或不属于当前用户"),
                400,
            )
        return category["name"], category["id"], None

    category = data.get("category")
    if not isinstance(category, str) or not category.strip():
        return None, None, (
            jsonify(error="category 必须是非空字符串，或者改传 category_id"),
            400,
        )
    category = database.ensure_category(
        category.strip(), "income" if data.get("type") == "income" else "expense"
    )
    return category["name"], category["id"], None


def _parse_formula(value):
    """公式只做留存（结果由前端用 math.js 算好后一起提交），这里只校验类型和长度。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "", None
    if not isinstance(value, str):
        return None, "formula 必须是字符串"
    text = value.strip()
    if len(text) > database.MAX_FORMULA_LENGTH:
        return None, "formula 最多 %d 个字符" % database.MAX_FORMULA_LENGTH
    return text, None


def _parse_record(data):
    """把请求体校验成一份干净的记录字段。POST 和 PUT 共用这一份规则。

    三种类型走不同分支：
    - expense / income：必须有分类（category_id 或 category 文本二选一）
    - transfer：不要分类，必须有 to_account 和 fee，金额从转出账户扣「金额 + 手续费」
    """
    # 客户端必须带 Content-Type: application/json，否则这里拿到的是 None
    if not isinstance(data, dict):
        return None, (jsonify(error="请求体必须是 JSON 对象"), 400)

    amount = data.get("amount")
    # bool 是 int 的子类，先单独排掉 True/False，否则 isinstance 检查会放过它
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return None, (jsonify(error="amount 必须是大于 0 的数字"), 400)

    # 类型只认这三种，其他一律拒绝，不猜
    record_type = data.get("type", database.DEFAULT_TYPE)
    if record_type not in database.RECORD_TYPES:
        return None, (
            jsonify(error="type 只能是 expense / income / transfer"),
            400,
        )

    # 账户允许自定义，前端不传时给默认值"现金"；转账时它就是转出账户
    account = (data.get("account") or database.DEFAULT_ACCOUNT).strip()

    formula, formula_error = _parse_formula(data.get("formula"))
    if formula_error is not None:
        return None, (jsonify(error=formula_error), 400)

    fee = 0
    to_account = ""
    if record_type == "transfer":
        to_account = (data.get("to_account") or "").strip()
        if not to_account:
            return None, (jsonify(error="转账必须指定 to_account（转入账户）"), 400)
        if to_account == account:
            return None, (jsonify(error="转出账户和转入账户不能相同"), 400)

        raw_fee = data.get("fee", 0)
        # 手续费可以不传（默认 0），传了就必须是不小于 0 的数字，负数等于反向偷钱
        if isinstance(raw_fee, bool) or not isinstance(raw_fee, (int, float)) or raw_fee < 0:
            return None, (jsonify(error="fee 必须是不小于 0 的数字"), 400)
        fee = round(float(raw_fee), 2)

        # 转账没有分类概念，固定存「转账」且不挂任何分类 id
        category, category_id = database.TRANSFER_CATEGORY, None
    else:
        category, category_id, error = _resolve_category(data)
        if error is not None:
            return None, error

    # 时间精确到分钟：老前端只给日期也能收，统一成 2026-10-26 14:30 这种形态
    date, date_error = _parse_datetime(data.get("date"))
    if date_error is not None:
        return None, (jsonify(error=date_error), 400)

    payload = {
        "amount": amount,
        "category": category,
        "category_id": category_id,
        "note": (data.get("note") or "").strip(),
        "date": date,
        "account": account,
        "type": record_type,
        "formula": formula,
        "to_account": to_account,
        "fee": fee,
    }
    return payload, None


@app.route("/", methods=["GET"])
def index():
    """首页路由：返回记账页面，顺便把分类和账户选项注入模板，下拉框不用再发一次请求。"""
    return render_template(
        "index.html",
        # 旧模板只吃「名字列表」，这里仍然给一级分类名，保证 v0.04 的页面还能正常打开
        categories=database.get_all_categories(),
        accounts=database.get_all_accounts(),
        today=datetime.date.today().isoformat(),
        # 给前端的 datetime-local 一个默认值，格式正好是它要的「YYYY-MM-DDTHH:MM」
        now=datetime.datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/health", methods=["GET"])
def health():
    """健康检查路由：给部署平台或监控探针轮询，正常时固定返回 good。"""
    return jsonify(health="good")


@app.route("/api/records", methods=["POST"])
def create_record():
    """接收前端提交的一笔账，写进 SQLite 并联动余额，把入库后的完整记录返回给前端。"""
    payload, error = _parse_record(request.get_json(silent=True))
    if error is not None:
        return error

    new_id, error_message = database.add_record(
        payload["amount"],
        payload["category"],
        payload["note"],
        payload["date"],
        payload["account"],
        payload["type"],
        payload["category_id"],
        payload["formula"],
        payload["to_account"],
        payload["fee"],
    )
    if error_message is not None:
        # 余额不足、账户不存在这类业务校验失败是「参数/状态不对」，400
        return jsonify(error=error_message), 400

    # v0.14.1：新增账单后立刻清缓存（全局 after_request 还会再兜一次）
    cache_ext.invalidate_record_caches()

    # 201 表示"已创建"
    return jsonify(id=new_id, **payload), 201


def _find_or_create_contact(name):
    """借贷按姓名找联系人：已有就直接用，没有就建一个空资料的联系人。

    返回 (联系人, 是否新建, 错误信息)；新建后借贷写库失败要回滚，避免留孤儿。
    """
    name = (name or "").strip()
    if not name:
        return None, False, "借贷对象姓名不能为空"
    for contact in database.list_contacts():
        if contact["name"] == name:
            return contact, False, None
    contact, error = database.create_contact(name)
    if error is not None:
        return None, False, error
    return contact, True, None


# AI 各意图落库成功后的提示语，SSE 的 done 事件与前端 Toast 共用同一套说法
AI_ACTION_MESSAGES = {
    "record": "记账成功",
    "debt": "借贷已记录",
    "add_contact": "联系人已添加",
}

# ---------------- v0.11.4：AI 记忆库 / 补充修改 / 防重 ----------------


def _ai_account_names():
    """库里真实存在的账户名（v0.11.5）：注入 Prompt，并在 AI 返回后做 difflib 纠正。"""
    try:
        return [item["name"] for item in database.list_accounts() if item.get("name")]
    except Exception:  # noqa: BLE001 - 账户读失败不能影响 AI 解析本身
        return []


def _ai_invest_account_names():
    """库里**投资账户**的账户名（v0.13.3）。

    注入 Prompt 让模型在 invest_buy 时正确归属账户，同时回传给前端确认卡做账户下拉；
    没有投资账户时返回空数组（前端据此提示「先去账户管理切换账户类型」）。
    读库失败一律吞掉——AI 解析不该因为账户读不到就整体失败。
    """
    try:
        return [
            item["name"]
            for item in database.list_accounts()
            if item.get("name") and item.get("type") == database.INVESTMENT_ACCOUNT_TYPE
        ]
    except Exception:  # noqa: BLE001 - 账户读失败不能影响 AI 解析本身
        return []


def _ai_contact_names():
    """库里真实存在的联系人姓名，用于借贷/报销对象的模糊匹配。"""
    try:
        return [item["name"] for item in database.list_contacts() if item.get("name")]
    except Exception:  # noqa: BLE001
        return []


def _ensure_ai_account(name):
    """AI 识别出的账户在库里不存在就自动建一个空账户（v0.11.6）。

    返回 (最终账户名, 是否新建)。建户失败不阻断记账，退回默认账户并保持不新建。
    """
    name = (name or "").strip()
    if not name:
        return database.DEFAULT_ACCOUNT, False
    try:
        existing = [item["name"] for item in database.list_accounts() if item.get("name")]
    except Exception:  # noqa: BLE001
        return name, False
    if name in existing:
        return name, False
    try:
        account, error_message = database.create_account(name, database.DEFAULT_GROUP, 0)
    except Exception:  # noqa: BLE001
        return name, False
    if error_message is not None or account is None:
        return name, False
    return name, True


def _memory_hints(text):
    """按用户这次说的话，从 ai_memory 里挑最相关的 3 条当 few-shot（v0.11.5 RAG）。

    读库失败就退化成「没有记忆」，绝不能因为记忆库坏了导致记不了账。
    """
    try:
        return database.search_ai_memories(text, 3)
    except Exception:  # noqa: BLE001
        try:
            return database.list_recent_ai_memories(3)
        except Exception:  # noqa: BLE001
            return []


# ---------------- AI 纠错审计日志（v0.11.5） ----------------

# 审计对比只保留用户看得懂的字段，余额、内部 id 之类的噪音不写进日志
AUDIT_FIELDS = (
    "amount",
    "type",
    "category",
    "account",
    "to_account",
    "fee",
    "date",
    "note",
    "is_reimbursable",
    "reimbursement_contact_name",
)


def _record_snapshot(record):
    """把一条账单裁成审计用的「改前/改后」快照；None 原样返回。"""
    if not record:
        return None
    snapshot = {}
    for key in AUDIT_FIELDS:
        if key in record:
            snapshot[key] = record.get(key)
    return snapshot


def _log_ai_correction(record_id, before, text, source, parsed=None):
    """写一条纠错审计日志；写失败只影响后台展示，不影响已经成功的账单更新。"""
    try:
        fresh = database.get_record(record_id)
    except Exception:  # noqa: BLE001
        fresh = None
    try:
        database.add_ai_correction_log(
            record_id,
            _record_snapshot(before),
            _record_snapshot(fresh),
            original_text=text or "",
            source=source,
            confidence=(parsed or {}).get("confidence"),
            auto_corrected_msg=(parsed or {}).get("auto_corrected_msg") or "",
        )
    except Exception:  # noqa: BLE001
        pass


def _attach_auto_corrected(body, parsed):
    """把模糊纠正结果挂到响应体上，前端据此在气泡里显示灰色小字提示。"""
    if not isinstance(body, dict):
        return body
    body["auto_corrected"] = parsed.get("auto_corrected") or []
    body["auto_corrected_msg"] = parsed.get("auto_corrected_msg") or ""
    return body


def _previous_record(data):
    """取请求里 previous_record_id / record_id 指向的原账单，返回 (账单, 错误信息)。"""
    raw = data.get("previous_record_id", data.get("record_id"))
    if raw in (None, "", 0, "0"):
        return None, None
    try:
        record_id = int(raw)
    except (TypeError, ValueError):
        return None, "previous_record_id 必须是账目 id"
    record = database.get_record(record_id)
    if record is None:
        return None, "原账单不存在（可能已被删除），请刷新后重试"
    return record, None


def _duplicate_candidate(parsed, account="", note="", exclude_id=None):
    """记账前查最近 10 分钟内金额相同、商户相似的账目；命中返回那一条。"""
    if parsed.get("action") != "record":
        return None
    return database.find_recent_duplicate(
        parsed.get("amount"),
        account=account or parsed.get("account") or database.DEFAULT_ACCOUNT,
        note=note if note else (parsed.get("note") or ""),
        exclude_id=exclude_id,
    )


def _apply_ai_correction(previous_record, parsed, text, source="ai"):
    """AI 补充修改原账单（v0.11.5 全量覆盖）：按 AI 返回的完整 JSON 覆盖更新，并回滚/重算余额。

    和 v0.11.4 的区别：
    - AI 这次拿到的是原账单**完整** JSON，要求没提到的字段继承原值、返回完整 JSON；
    - 这里按完整 JSON 做全量 UPDATE（含报销字段），不再只更新分类/金额两三个字段；
    - 余额由 database.update_record 内部「先撤旧账 → 校验新账 → 落新账」保证，
      「微信 → 微信零钱」「30 → 50」时两个账户的余额都会被正确回滚/扣除；
    - 更新前后各拍一张快照写进 ai_correction_log，后台可以看改前/改后对比。
    """
    record_id = previous_record["id"]
    record_type = parsed.get("type") or previous_record.get("type") or database.DEFAULT_TYPE

    amount = parsed.get("amount")
    if amount is None:
        amount = previous_record.get("amount")

    category = parsed.get("category") or previous_record.get("category") or "其他"
    category_id = previous_record.get("category_id")
    if record_type in ("expense", "income"):
        try:
            category_id = database.ensure_category(
                category, "income" if record_type == "income" else "expense"
            )["id"]
        except database.RecordError:
            category_id = None
    else:
        category_id = None

    date = parsed.get("date") or previous_record.get("date")
    note = parsed.get("note")
    if note is None:
        note = previous_record.get("note")
    account, is_new_account = _ensure_ai_account(
        parsed.get("account") or previous_record.get("account") or database.DEFAULT_ACCOUNT
    )
    to_account = parsed.get("to_account")
    if to_account is None:
        to_account = previous_record.get("to_account")
    fee = parsed.get("fee")
    if fee is None:
        fee = previous_record.get("fee") or 0

    # 报销字段：AI 提到就按它的，没提就继承原账单（不允许一句话把报销标记弄丢）
    if "is_reimbursable" in parsed:
        is_reimbursable = bool(parsed.get("is_reimbursable"))
    else:
        is_reimbursable = bool(previous_record.get("is_reimbursable"))
    contact_name = (parsed.get("contact_name") or "").strip()
    if not contact_name:
        contact_name = (previous_record.get("reimbursement_contact_name") or "").strip()
    contact_id = previous_record.get("reimbursement_contact_id")
    warnings = []
    created_contact = None
    if record_type == "expense" and is_reimbursable:
        if contact_name:
            contact, created, error_message = _find_or_create_contact(contact_name)
            if error_message is not None:
                return {"error": error_message}, 400
            if created:
                created_contact = contact
            contact_id = contact["id"]
        elif not contact_id:
            # 想报销但原账单也没报销人：先按普通记账更新，明确告诉用户去补报销人
            is_reimbursable = False
            warnings.append("没有识别到报销人，这笔账先按普通支出处理，可在详情里补设报销人")
    else:
        is_reimbursable = False
        contact_id = None

    updated, error_message = database.update_record(
        record_id,
        amount,
        category,
        note or "",
        date,
        account,
        record_type,
        category_id,
        previous_record.get("formula") or "",
        to_account or "",
        fee or 0,
    )
    if error_message is not None:
        if created_contact is not None:
            database.delete_contact(created_contact["id"])
        return {"error": error_message}, 400
    if not updated:
        if created_contact is not None:
            database.delete_contact(created_contact["id"])
        return {"error": "原账单不存在（可能已被删除）"}, 404

    # 报销是独立的一张表字段，update_record 不碰它，这里单独同步
    try:
        if record_type == "expense" and is_reimbursable and contact_id:
            already = float(previous_record.get("reimbursed_amount") or 0)
            database.set_record_reimbursement(
                record_id,
                True,
                contact_id,
                total_reimbursement=amount,
                reimbursed_amount=min(already, float(amount)),
            )
        else:
            database.set_record_reimbursement(record_id, False)
    except database.RecordError as exc:
        warnings.append("报销信息未更新：%s" % exc)

    # 分类被纠正了就写进记忆库：下次遇到同样说法的商户，AI 会按新分类来
    if (
        record_type in ("expense", "income")
        and (previous_record.get("category") or "") != category
    ):
        try:
            database.add_ai_memory(
                text,
                previous_record.get("category") or "",
                category,
                note="AI 补充修改自动记录",
            )
        except database.RecordError:
            pass

    _log_ai_correction(record_id, previous_record, text, source, parsed)

    fresh = database.get_record(record_id)
    body = {
        "id": record_id,
        "source": "ai",
        "action": "record",
        "updated": True,
        "text": text.strip(),
        "record": fresh,
        "confidence": parsed.get("confidence"),
    }
    body = _attach_auto_corrected(body, parsed)
    if is_new_account:
        body["is_new_account"] = True
        body["new_account_name"] = account
    if warnings:
        body["warnings"] = warnings
    return body, 200


def _apply_ai_intent(parsed, text):
    """把 AI 解析出的意图真正落库，返回 (响应体 dict, HTTP 状态码)。

    /api/records/ai 与 /api/records/ai/stream 共用这一份写库逻辑：
    分类补建、联系人查找/创建、余额联动、失败回滚全部只写一遍，
    保证普通接口与 SSE 流式接口落库行为完全一致。
    unknown 由调用方处理（普通接口返回 400，SSE 推 status=unknown），这里不该收到。

    v0.13.3 保险丝（设计 D10 / §8）：`invest_buy` **绝不在这里写库**。
    投资建仓的唯一入账口是 `POST /api/invest/holdings`（AI 确认卡、手动弹窗、CSV 导入共用）。
    这里拦一道是防止未来有人给 invest_buy 加了分支、或模型吐出意外 action 时，
    钱被按普通账目写进 records —— 那会让「买入 1000」凭空变成一笔支出。
    """
    action = parsed.get("action")

    if action == "invest_buy":
        return {"error": "invest_buy 不在此处写库，请走 POST /api/invest/holdings"}, 400

    if action == "record":
        category = parsed.get("category") or "其他"
        record_type = parsed["type"]

        category_id = None
        if record_type in ("expense", "income"):
            try:
                category_id = database.ensure_category(
                category, "income" if record_type == "income" else "expense"
            )["id"]
            except database.RecordError:
                category_id = None

        # 代买 / 垫付（v0.10）：
        # - 支出 + 有报销人姓名：一并写报销字段（is_reimbursable=1、报销人、应报金额=账目金额）
        # - 支出 + 没提报销人：按普通记录入库（DB is_reimbursable 保持 0），只在响应里带
        #   is_reimbursable=true，让前端提示用户补报销人后再走 PUT /reimbursement 设置
        # - 收入 / 转账不参与报销：set_record_reimbursement 也只允许支出账目
        add_extra = {}
        reimbursement = None
        created_contact = None
        if parsed.get("is_reimbursable") and record_type == "expense":
            contact_name = parsed.get("contact_name") or ""
            if contact_name:
                contact, created, error_message = _find_or_create_contact(contact_name)
                if error_message is not None:
                    return {"error": error_message}, 400
                if created:
                    created_contact = contact
                add_extra = {
                    "is_reimbursable": 1,
                    "reimbursement_contact_id": contact["id"],
                    "reimbursed_amount": 0,
                    "total_reimbursement": parsed["amount"],
                }
                reimbursement = {
                    "is_reimbursable": True,
                    "contact_id": contact["id"],
                    "contact_name": contact["name"],
                    "total_reimbursement": parsed["amount"],
                    "reimbursed_amount": 0,
                }
            else:
                reimbursement = {
                    "is_reimbursable": True,
                    "contact_id": None,
                    "contact_name": "",
                    "total_reimbursement": parsed["amount"],
                    "reimbursed_amount": 0,
                    # pending_contact=true：这笔账已经记下，但还没指定报销人，前端可提示补录
                    "pending_contact": True,
                }

        # v0.11.6：AI 识别出的账户库里没有就自动建户，并在响应里告诉前端
        account_name, is_new_account = _ensure_ai_account(
            parsed.get("account") or database.DEFAULT_ACCOUNT
        )
        new_id, error_message = database.add_record(
            parsed["amount"],
            category,
            parsed.get("note", ""),
            parsed["date"],
            account_name,
            record_type,
            category_id,
            "",
            parsed.get("to_account", ""),
            parsed.get("fee", 0),
            **add_extra,
        )
        if error_message is not None:
            # 报销人是为了这笔账临时建的，账没写成就不该留下空联系人
            if created_contact is not None:
                database.delete_contact(created_contact["id"])
            return {"error": error_message}, 400

        body = {
            "id": new_id,
            "source": "ai",
            "action": "record",
            "text": text.strip(),
            "record": {key: value for key, value in parsed.items() if key != "action"},
        }
        body = _attach_auto_corrected(body, parsed)
        if is_new_account:
            body["is_new_account"] = True
            body["new_account_name"] = account_name
        if reimbursement is not None:
            body["reimbursement"] = reimbursement
        return body, 201

    if action == "debt":
        contact, created, error_message = _find_or_create_contact(parsed["contact_name"])
        if error_message is not None:
            return {"error": error_message}, 400

        debt, error_message = database.create_debt(
            contact["id"],
            parsed["amount"],
            debt_type=parsed["type"],
            account=parsed.get("account") or database.DEFAULT_ACCOUNT,
            date=parsed["date"],
            status="unpaid",
        )
        if error_message is not None:
            # 联系人是为了这笔借贷临时建的，借贷没写成就不该留下空联系人
            if created:
                database.delete_contact(contact["id"])
            return {"error": error_message}, 400

        return {
            "id": debt["id"],
            "source": "ai",
            "action": "debt",
            "text": text.strip(),
            "contact": contact,
            "debt": debt,
        }, 201

    if action == "add_contact":
        contact, error_message = database.create_contact(
            parsed["name"], parsed["identity"], parsed["phone"], parsed["wechat"]
        )
        if error_message is not None:
            status = 409 if "已存在" in error_message else 400
            return {"error": error_message}, status
        return {
            "id": contact["id"],
            "source": "ai",
            "action": "add_contact",
            "text": text.strip(),
            "contact": contact,
        }, 201

    # 理论上到不了这里；真到了就按听不懂处理，不猜
    return {"error": "AI 无法理解您的指令"}, 400


@app.route("/api/records/ai", methods=["POST"])
def create_record_by_ai():
    """一句话先交给 AI 判断意图（记账 / 借贷 / 加联系人），再按 action 分流写库。

    模型只负责理解与抽字段，金额/类型/日期到本地还会再校验一遍；写库统一走
    _apply_ai_intent，和流式接口 /api/records/ai/stream 用的是同一份逻辑。

    v0.11.4：带 previous_record_id 时是「补充修改原账单」，覆盖更新而不是新建；
    保存前会查 10 分钟内相似账目，命中返回 409，前端确认后带 force=true 重发。
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="先输入一句话，比如「昨天打车花了 30」"), 400

    previous_record, error_message = _previous_record(data)
    if error_message is not None:
        return jsonify(error=error_message), 400

    try:
        parsed = ai_service.parse_intent(
            text,
            previous_record=previous_record,
            memories=_memory_hints(text),
            accounts=_ai_account_names(),
            contacts=_ai_contact_names(),
            invest_accounts=_ai_invest_account_names(),
        )
    except ai_service.AIServiceError as exc:
        # 密钥失效、网络超时、模型胡说都算上游失败，502 便于前端提示重试
        return jsonify(error=str(exc)), 502

    if parsed["action"] == "unknown":
        return jsonify(error="AI 无法理解您的指令"), 400

    # v0.13.3：投资意图**在路由层就短路**，回 200 + need_confirm，与 SSE 那条字段逐字一致。
    # 前端 SSE 失败时会走 fallbackAiRequest() 打这条非流式接口，而 api() 对非 2xx 直接抛错，
    # 回 400 会让投资指令被吞成「AI 无法理解您的指令」——所以这里必须是 200。
    # 位置：必须在防重之前（_duplicate_candidate 对 invest_buy 会误判），
    # 也必须在 _apply_ai_intent 之前（那里对 invest_buy 是 400 保险丝）。
    if parsed["action"] == "invest_buy":
        parsed["invest_accounts"] = _ai_invest_account_names()
        return (
            jsonify(
                status="need_confirm",
                action="invest_buy",
                msg="请确认建仓信息",
                message="请确认建仓信息",
                parsed=parsed,
                candidates=invest_eastmoney.search_or_fallback(
                    parsed.get("invest_name") or "", 4
                ),
            ),
            200,
        )

    if previous_record is not None:
        body, status = _apply_ai_correction(previous_record, parsed, text)
        return jsonify(body), status

    if not data.get("force"):
        duplicate = _duplicate_candidate(parsed)
        if duplicate is not None:
            return (
                jsonify(
                    duplicate=True,
                    message="10 分钟内有一笔金额相同、商户相似的账目，请先确认是否重复记账",
                    candidate=duplicate,
                    parsed=parsed,
                ),
                409,
            )

    body, status = _apply_ai_intent(parsed, text)
    if status < 400:
        body["confidence"] = parsed.get("confidence")
        body = _attach_auto_corrected(body, parsed)
    return jsonify(body), status


@app.route("/api/records/ai/stream", methods=["POST"])
def create_record_by_ai_stream():
    """SSE 版的一句话记账：分阶段推流，最后把真实落库结果放进 done 事件。

    和 /api/records/ai 的区别只有「推流提示 + 不再用 HTTP 400 表示听不懂」：
    - unknown 也回 200，推 {"status":"unknown"} 事件
    - 任何异常都推 {"status":"error"} 事件，绝不让流断在半路
    - 写库仍走 _apply_ai_intent，落库字段与普通接口一致
    - v0.11.4：带 previous_record_id 时覆盖更新原账单；命中防重时推 duplicate 事件
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="先输入一句话，比如「昨天打车花了 30」"), 400

    previous_record, error_message = _previous_record(data)
    if error_message is not None:
        return jsonify(error=error_message), 400
    force = bool(data.get("force"))

    def event(payload):
        # SSE 规定每条事件以空行结束；ensure_ascii=False 让中文在 curl 里可读
        return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    def generate():
        try:
            yield event({"status": "thinking", "msg": "正在理解您的指令..."})

            try:
                parsed = ai_service.parse_intent(
                    text,
                    previous_record=previous_record,
                    memories=_memory_hints(text),
                    accounts=_ai_account_names(),
                    contacts=_ai_contact_names(),
                    invest_accounts=_ai_invest_account_names(),
                )
            except ai_service.AIServiceError as exc:
                yield event({"status": "error", "action": "unknown", "msg": str(exc), "message": str(exc)})
                return

            action = parsed["action"]
            if action == "unknown":
                # SSE 已经 200 了，听不懂用事件表达，不用 HTTP 400；
                # 同时带 action="unknown" / message，方便前端和 error 事件同一套分支处理
                yield event({
                    "status": "unknown",
                    "action": "unknown",
                    "msg": "AI 无法理解您的指令",
                    "message": "AI 无法理解您的指令",
                })
                return

            # v0.13.3：投资意图**只推确认卡，不落库**（设计 D10）。
            # 必须放在防重分支**之前**：_duplicate_candidate 按「金额 + 商户相似」比对 records，
            # 对 invest_buy 会误判成重复记账，把确认卡整个吞掉。
            # 事件序列与设计 §660 一致：thinking → extracting_amount → resolving_invest → need_confirm
            if action == "invest_buy":
                yield event({"status": "extracting_amount", "msg": "正在识别买入金额..."})
                yield event({"status": "resolving_invest", "msg": "正在匹配标的..."})
                # 账户候选回传给前端确认卡：少了它用户改不了账户，会退化成纯文本展示
                parsed["invest_accounts"] = _ai_invest_account_names()
                yield event({
                    "status": "need_confirm",
                    "action": "invest_buy",
                    "msg": "请确认建仓信息",
                    "message": "请确认建仓信息",
                    "parsed": parsed,
                    "candidates": invest_eastmoney.search_or_fallback(
                        parsed.get("invest_name") or "", 4
                    ),
                })
                return

            # 补充修改原账单：覆盖更新，不再走「新建 + 防重」
            if previous_record is not None:
                yield event({"status": "extracting_amount", "msg": "正在识别修改内容..."})
                yield event({"status": "resolving_category", "msg": "正在匹配分类..."})
                yield event({"status": "saving", "msg": "正在更新原账单..."})
                body, status_code = _apply_ai_correction(previous_record, parsed, text)
                if status_code >= 400:
                    message = body.get("error", "更新失败")
                    yield event({"status": "error", "msg": message, "message": message})
                    return
                yield event(
                    {
                        "status": "done",
                        "action": "record",
                        "updated": True,
                        "message": "已更新原账单",
                        "payload": body,
                        "confidence": parsed.get("confidence"),
                    }
                )
                return

            # 防重复：保存前查最近 10 分钟相似账目，前端弹窗确认后带 force=true 重发
            if not force:
                duplicate = _duplicate_candidate(parsed)
                if duplicate is not None:
                    yield event({
                        "status": "duplicate",
                        "action": action,
                        "message": "10 分钟内有一笔金额相同、商户相似的账目，请先确认",
                        "candidate": duplicate,
                        "parsed": parsed,
                    })
                    return

            # 字段在 parse_intent 里已经本地校验过，这里的分阶段提示对应真实处理顺序：
            # 金额/分类在 _apply_ai_intent 里补建分类时用到，saving 之后才真正写库
            yield event({"status": "extracting_amount", "msg": "正在识别金额..."})
            yield event({"status": "resolving_category", "msg": "正在匹配分类..."})
            yield event({"status": "saving", "msg": "正在保存账目..."})

            body, status_code = _apply_ai_intent(parsed, text)
            if status_code >= 400:
                message = body.get("error", "保存失败")
                yield event({"status": "error", "msg": message, "message": message})
                return

            body["confidence"] = parsed.get("confidence")
            yield event(
                {
                    "status": "done",
                    "action": action,
                    "message": AI_ACTION_MESSAGES.get(action, "处理完成"),
                    "payload": body,
                    "confidence": parsed.get("confidence"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 流一旦开始就不能崩，兜底转成 error 事件
            yield event({"status": "error", "msg": str(exc), "message": str(exc)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------- 截图记账（v0.11）：Base64 图片 -> 视觉模型 -> 落盘 + 入库 ----------------

# 常见图片 MIME 与落盘后缀的对应关系；前端 Canvas 压缩后基本都是 image/jpeg
AI_IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _decode_ai_image(image_base64, mime):
    """把前端传来的 Base64（可带 dataURL 前缀）解成 (bytes, 真实 MIME, 错误信息)。"""
    data = image_base64.strip()
    if data.startswith("data:"):
        header, _, data = data.partition(",")
        if ";" in header:
            mime = header[5:].split(";")[0] or mime
    try:
        raw = base64.b64decode(data, validate=False)
    except (ValueError, TypeError):
        return None, mime, "图片数据不是合法的 Base64"
    if not raw:
        return None, mime, "图片内容是空的，请重新选择截图"
    if len(raw) > MAX_UPLOAD_BYTES:
        return None, mime, "图片不能超过 5MB，请压缩后再试"
    return raw, mime, None


def _save_ai_image_to_disk(raw, mime):
    """把截图落盘到 static/uploads/，返回 (访问路径, 错误信息)。"""
    mime = (mime or "").lower()
    if not mime.startswith("image/"):
        return None, "只支持图片文件（jpg / png / webp / gif）"
    extension = AI_IMAGE_MIME_EXTENSIONS.get(mime)
    if extension is None:
        return None, "不支持的图片格式，请用 jpg / png / webp / gif"
    # 时间戳 + 随机串：既能按时间排序，也绝不会撞名互相覆盖
    filename = (
        "shot_"
        + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
        + extension
    )
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as handle:
        handle.write(raw)
    return "/static/uploads/" + filename, None


def _remove_saved_image(image_path):
    """删除 static/uploads/ 下的截图；只认已知前缀，绝不接受任意路径。

    # TODO(v0.12+): 接入云存档后，这里要同时删除云对象，并改由云端返回永久 URL
    """
    if not image_path or not isinstance(image_path, str):
        return
    prefix = "/static/uploads/"
    if not image_path.startswith(prefix):
        return
    target = os.path.join(UPLOAD_DIR, os.path.basename(image_path))
    if os.path.isfile(target):
        try:
            os.remove(target)
        except OSError:
            # 文件被占用/已被删都不影响数据库状态，下次再清
            pass


@app.route("/api/records/ai/image", methods=["POST"])
def create_record_by_ai_image():
    """截图记账：前端 Canvas 压缩后的 Base64 -> 视觉模型识别 -> 原图落盘 + 账目入库。

    请求体 {"image": "data:image/jpeg;base64,..."}（也可只传裸 Base64 + mime）。
    成功返回与 /api/records/ai 同构的 201，额外带 image_path，前端据此显示「查看原图」。
    """
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if not isinstance(image, str) or not image.strip():
        return jsonify(error="没有收到图片，请重新选择截图"), 400

    # Base64 相对原图膨胀约 4/3，先按编码长度粗筛，别把超大图读进内存再报错
    if len(image) > MAX_UPLOAD_BYTES * 2:
        return jsonify(error="图片太大，请重新选择或裁剪后再试"), 413

    mime = data.get("mime") if isinstance(data.get("mime"), str) else None
    raw, mime, error_message = _decode_ai_image(image, mime)
    if error_message is not None:
        return jsonify(error=error_message), 400

    try:
        parsed = ai_service.parse_image(
            image,
            mime or ai_service.IMAGE_MIME_FALLBACK,
            memories=_memory_hints(""),
            accounts=_ai_account_names(),
            contacts=_ai_contact_names(),
        )
    except ai_service.AIServiceError as exc:
        # 密钥失效 / 超时 / 模型返回坏 JSON 都算上游失败，502 让前端提示重试
        return jsonify(error=str(exc)), 502

    if parsed["action"] == "unknown":
        return jsonify(error="无法识别该截图，请换一张清晰的账单截图"), 422
    if parsed["action"] != "record":
        # 截图里是借贷/联系人信息：v0.11 只闭环「记账」，明确告知而不是静默丢弃
        return jsonify(
            error="这张截图看起来是借贷或联系人信息，截图记账暂时只支持消费/收入账单"
        ), 422

    # 防重复：跟一句话记账同一套判断，前端确认后带 force=true 重发
    if not data.get("force"):
        duplicate = _duplicate_candidate(parsed)
        if duplicate is not None:
            return (
                jsonify(
                    duplicate=True,
                    message="10 分钟内有一笔金额相同、商户相似的账目，请先确认是否重复记账",
                    candidate=duplicate,
                    parsed=parsed,
                ),
                409,
            )

    # 先落盘再入库：图片路径要跟着账目一起写，避免「账记了、图丢了」
    image_path, error_message = _save_ai_image_to_disk(raw, mime)
    if error_message is not None:
        return jsonify(error=error_message), 400

    text = parsed.get("note") or "截图记账"
    body, status = _apply_ai_intent(parsed, text)
    if status >= 400:
        _remove_saved_image(image_path)
        return jsonify(body), status

    # 账目已写成，再把图片挂上去；挂失败就撤销账目并删图，保持要么都有要么都没有
    if not database.set_record_image(body["id"], image_path):
        database.delete_record(body["id"])
        _remove_saved_image(image_path)
        return jsonify(error="截图保存失败，请重试"), 500

    body["source"] = "ai_image"
    body["image_path"] = image_path
    body["record"]["image_path"] = image_path
    # 相册/详情直接拿这个地址渲染 <img>，前端省一次拼接
    body["record"]["image_url"] = image_path
    body["confidence"] = parsed.get("confidence")
    return jsonify(body), status


@app.route("/api/records/images", methods=["GET"])
def list_record_images():
    """相册列表：所有带截图的账目（金额/分类/时间/图片路径一次给全）。"""
    records = database.list_records_with_images()
    return jsonify(count=len(records), records=records)


@app.route("/api/records/<int:record_id>/image", methods=["DELETE"])
def delete_record_image(record_id):
    """相册里「删除图片」：数据库清空 image_path + 删本地文件，账目本身保留。"""
    record = database.get_record(record_id)
    if record is None:
        return jsonify(error="账目不存在（可能已被删除）"), 404
    image_path = (record.get("image_path") or "").strip()
    if not image_path:
        return jsonify(error="这条账目没有截图"), 404
    if not database.set_record_image(record_id, ""):
        return jsonify(error="图片记录清理失败，请重试"), 500
    _remove_saved_image(image_path)
    return jsonify(removed=True, record_id=record_id)


# ---------------- AI 反馈与记忆库（v0.10） ----------------
# 用户发现 AI 解析错了就记一条反馈，后续可以拿来改 Prompt / 攒样本；
# 页面上的「标记已处理」把 status 从 pending 改成 processed，列表默认看全部。


@app.route("/api/feedback", methods=["POST"])
def create_feedback():
    """记录一条 AI 反馈：raw_text 必填，parsed / corrected 可传对象或 JSON 字符串。

    source 用来区分来源（如 admin / 记账页），不认识的值按普通文本存；
    返回 201 {id}，方便前端拿到新建记录的 id。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    raw_text = data.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return jsonify(error="raw_text 必须是非空字符串"), 400

    try:
        feedback = database.add_feedback(
            raw_text,
            parsed_json=data.get("parsed", data.get("parsed_json")),
            corrected_json=data.get("corrected", data.get("corrected_json")),
            source=data.get("source"),
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(id=feedback["id"]), 201


@app.route("/api/feedback", methods=["GET"])
def list_feedback():
    """反馈列表，支持 ?status=pending / processed 筛选；返回 {items, total}。"""
    status = (request.args.get("status") or "").strip()
    if status and status not in database.FEEDBACK_STATUSES:
        return jsonify(error="status 只能是 pending / processed"), 400
    items = database.list_feedback(status or None)
    return jsonify(items=items, total=len(items))


@app.route("/api/feedback/<int:feedback_id>", methods=["PUT"])
def update_feedback(feedback_id):
    """更新反馈状态（body：{"status": "processed"}），成功返回更新后的整条记录。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        return jsonify(error="status 必须是非空字符串"), 400

    feedback, error_message = database.update_feedback_status(feedback_id, status)
    if error_message is not None:
        return jsonify(error=error_message), 400
    if feedback is None:
        return jsonify(error="反馈不存在"), 404
    return jsonify(feedback)


@app.route("/api/records/<int:record_id>/correction", methods=["POST"])
def correct_record_category(record_id):
    """详情弹窗【AI 纠错】：把账单分类改成用户选的分类，并记一条 AI 记忆。

    body {"corrected_category": "餐饮", "original_text": "可选原话",
          "raw_category": "可选 AI 原来错的分类", "note": "可选备注"}
    记忆写入 ai_memory，之后解析相似商户时会当 few-shot 带上。
    """
    record = database.get_record(record_id)
    if record is None:
        return jsonify(error="账目不存在（可能已被删除）"), 404
    if (record.get("type") or "") == "transfer":
        return jsonify(error="转账账目没有分类，请直接编辑账单"), 400

    data = request.get_json(silent=True) or {}
    corrected = data.get("corrected_category")
    if not isinstance(corrected, str) or not corrected.strip():
        return jsonify(error="corrected_category 必须是非空字符串"), 400
    corrected = corrected.strip()

    try:
        category = database.ensure_category(
            corrected, "income" if record.get("type") == "income" else "expense"
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400

    raw_category = data.get("raw_category")
    if not isinstance(raw_category, str) or not raw_category.strip():
        raw_category = record.get("category") or ""
    original_text = data.get("original_text")
    if not isinstance(original_text, str) or not original_text.strip():
        original_text = record.get("note") or ""

    try:
        memory = database.add_ai_memory(
            original_text,
            raw_category,
            category["name"],
            note=(data.get("note") if isinstance(data.get("note"), str) else "") or "详情弹窗 AI 纠错",
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400

    updated, error_message = database.update_record(
        record_id,
        record["amount"],
        category["name"],
        record.get("note") or "",
        record["date"],
        record.get("account") or database.DEFAULT_ACCOUNT,
        record.get("type") or database.DEFAULT_TYPE,
        category["id"],
        record.get("formula") or "",
        record.get("to_account") or "",
        record.get("fee") or 0,
    )
    if error_message is not None:
        return jsonify(error=error_message), 400
    if not updated:
        return jsonify(error="账目不存在（可能已被删除）"), 404

    _log_ai_correction(
        record_id,
        record,
        original_text,
        "detail",
        {"category": category["name"], "raw_category": raw_category},
    )
    return jsonify(memory=memory, record=database.get_record(record_id))


@app.route("/api/records/<int:record_id>/ai-revise", methods=["POST"])
def revise_record_by_ai(record_id):
    """气泡里继续聊：「改成微信零钱，金额 50」。

    v0.11.5 的多轮纠错彻底方案：
    - 把原账单**完整** JSON 交给 AI，明确要求「未提到的字段继承原值、返回完整 JSON」；
    - 后端按 AI 返回的完整 JSON 全量 UPDATE，账户余额由 update_record 先撤旧账再落新账，
      「微信 -> 微信零钱」时两个账户的余额都会被正确回滚 / 扣除；
    - 和 /correction 的分工：/correction 是详情弹窗里用户直接选标准分类，
      这里是自然语言改任意字段。
    """
    record = database.get_record(record_id)
    if record is None:
        return jsonify(error="账单不存在（可能已被删除）"), 404

    data = request.get_json(silent=True) or {}

    # v0.11.7：详情弹窗的「完整表单」直接走结构化字段，不经自然语言模型；
    # 仍复用 _apply_ai_correction 做全量 UPDATE + 跨账户余额回滚 + 审计日志
    field_keys = ("amount", "category", "account", "note", "date")
    if any(key in data for key in field_keys):
        amount_value = data.get("amount")
        if amount_value in (None, ""):
            amount_value = record.get("amount")
        # 表单金额可能是字符串 / 带逗号的写法，这里统一成数字并拦截非法值，
        # 否则会一路传到余额计算里抛 TypeError（500）
        try:
            amount_value = round(float(str(amount_value).replace(",", "").replace("¥", "").strip()), 2)
        except (TypeError, ValueError):
            return jsonify(error="金额必须是数字"), 400
        if amount_value <= 0:
            return jsonify(error="金额必须大于 0"), 400
        parsed = {
            "action": "record",
            "confidence": None,
            "type": record.get("type") or database.DEFAULT_TYPE,
            "amount": amount_value,
            "category": data.get("category") or record.get("category") or "其他",
            "account": data.get("account") or record.get("account") or database.DEFAULT_ACCOUNT,
            "to_account": data.get("to_account", record.get("to_account") or ""),
            "fee": data.get("fee", record.get("fee") or 0),
            "date": data.get("date") or record.get("date"),
            "note": data.get("note", record.get("note") or ""),
            "is_reimbursable": record.get("is_reimbursable") or False,
            "contact_name": record.get("reimbursement_contact_name") or "",
            "auto_corrected": [],
            "auto_corrected_msg": "",
        }
        account, is_new = _ensure_ai_account(parsed["account"])
        parsed["account"] = account
        text = data.get("text") or (
            "手动修改：%s %s · %s"
            % (parsed["account"], parsed.get("category") or "", parsed.get("note") or "")
        )
        body, status = _apply_ai_correction(record, parsed, text.strip(), source="detail")
        if status >= 400:
            return jsonify(body), status
        body["is_new_account"] = bool(is_new)
        body["new_account_name"] = account if is_new else ""
        return jsonify(body), 200

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="先说说要改成什么，比如「改成微信零钱，金额 50」"), 400

    try:
        parsed = ai_service.parse_intent(
            text.strip(),
            previous_record=record,
            memories=_memory_hints(text),
            accounts=_ai_account_names(),
            contacts=_ai_contact_names(),
        )
    except ai_service.AIServiceError as exc:
        return jsonify(error=str(exc)), 502

    if parsed["action"] != "record":
        return jsonify(error="没听懂要改成什么，请直接说「改成微信零钱，金额 50」"), 400

    body, status = _apply_ai_correction(record, parsed, text, source="bubble")
    if status >= 400:
        return jsonify(body), status
    return jsonify(body), 200


@app.route("/api/records/duplicate-check", methods=["GET"])
def check_record_duplicate():
    """手工记账保存前的防重预检：?amount=30&account=支付宝&note=滴滴&exclude_id=5

    返回 {duplicate, candidate}；candidate 为最近 10 分钟内金额相同、商户相似的账目。
    前端命中后弹自定义「仍然记账」确认框，确认了再正常 POST /api/records。
    """
    raw_amount = request.args.get("amount", "")
    try:
        amount = round(float(raw_amount), 2)
    except (TypeError, ValueError):
        return jsonify(error="amount 必须是数字"), 400

    raw_exclude = request.args.get("exclude_id", "")
    exclude_id = None
    if raw_exclude not in ("", None):
        try:
            exclude_id = int(raw_exclude)
        except (TypeError, ValueError):
            return jsonify(error="exclude_id 必须是整数"), 400

    candidate = database.find_recent_duplicate(
        amount,
        account=request.args.get("account", ""),
        note=request.args.get("note", ""),
        exclude_id=exclude_id,
    )
    return jsonify(duplicate=candidate is not None, candidate=candidate)


# ---------------- 账单导入（v0.12）：CSV / Excel 解析、去重预览、批量入库 ----------------

IMPORT_MAX_BYTES = 8 * 1024 * 1024
IMPORT_MAX_ROWS = 2000
IMPORT_DUPLICATE_DAYS = 10

# 微信 / 支付宝导出表的表头各自不同，按关键词找列，别写死列序号
IMPORT_TIME_KEYWORDS = ("交易时间", "交易创建时间", "付款时间", "创建时间", "时间")
IMPORT_AMOUNT_KEYWORDS = ("金额(元)", "交易金额", "金额")
IMPORT_MERCHANT_KEYWORDS = ("交易对方", "对方", "商户", "商家", "交易对象")
IMPORT_TYPE_KEYWORDS = ("收/支", "收支", "交易类型", "类型")
IMPORT_NOTE_KEYWORDS = ("商品说明", "商品名称", "商品", "备注")
IMPORT_STATUS_KEYWORDS = ("交易状态", "当前状态", "状态")
IMPORT_PAY_KEYWORDS = ("支付方式", "收/付款方式", "付款方式", "账户")


def _import_pick_column(columns, keywords):
    """按关键词优先级挑列：先找 收/支，再退到 交易类型，避免把「商户消费」当收支。"""
    for keyword in keywords:
        for column in columns:
            if keyword in str(column):
                return column
    return None


def _import_decode_csv(raw):
    """微信导出常见 GBK，支付宝常见 UTF-8；逐个编码试，失败返回 None。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _import_dataframe(upload):
    """把上传的 CSV / Excel 读成 DataFrame，返回 (frame, 错误信息)。"""
    import pandas as pd

    filename = upload.filename or ""
    extension = os.path.splitext(filename)[1].lower()
    raw = upload.read()
    if not raw:
        return None, "文件是空的，请重新导出"
    if len(raw) > IMPORT_MAX_BYTES:
        return None, "文件太大了（上限 8MB），请按月导出"

    if extension in (".xlsx", ".xls"):
        try:
            frame = pd.read_excel(io.BytesIO(raw), dtype=str)
        except Exception as exc:  # noqa: BLE001 - 解析失败统一提示
            return None, "Excel 解析失败：%s" % exc
        return frame, None

    text = _import_decode_csv(raw)
    if text is None:
        return None, "无法识别 CSV 编码，请用 UTF-8 或 GBK 重新导出"

    # 微信/支付宝导出的 csv 前面常有几行说明文字，找到真正的表头再交给 pandas
    lines = text.splitlines()
    header_index = 0
    for index, line in enumerate(lines[:40]):
        if "交易时间" in line and ("金额" in line or "收/支" in line):
            header_index = index
            break
    csv_text = "\n".join(lines[header_index:])
    try:
        frame = pd.read_csv(io.StringIO(csv_text), dtype=str, on_bad_lines="skip")
    except Exception as exc:  # noqa: BLE001
        return None, "CSV 解析失败：%s" % exc
    return frame, None


def _import_amount(value):
    """把「¥1,234.50」「1,234.50」这类金额统一成两位小数。"""
    if value is None:
        return None
    text = str(value).replace("¥", "").replace("￥", "").replace(",", "").strip()
    if not text or text in ("-", "/", "--"):
        return None
    try:
        return round(abs(float(text)), 2)
    except (TypeError, ValueError):
        return None


def _import_date(value):
    """只保留日期部分（YYYY-MM-DD）；解析不了返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _import_type(value):
    """收/支列：收入 → income，支出 → expense，不计收支返回 None。

    预览接口返回的是已归一化的 expense / income，确认时原样再传回来，也要认。
    """
    text = str(value or "").strip()
    if text in ("expense", "income"):
        return text
    if "收入" in text:
        return "income"
    if "支出" in text:
        return "expense"
    return None


def _import_category(merchant, note):
    """用同义词表给导入流水猜分类，猜不出归「其他」。"""
    text = "%s %s" % (merchant or "", note or "")
    for keyword, category in ai_service.CATEGORY_MAPPING.items():
        if keyword and keyword in text:
            return category
    # 导入最常见的是吃饭：AI 同义词表没覆盖的小店名/菜名，用餐饮关键词兜底
    for keyword in ("面", "饭", "餐", "早餐", "午餐", "晚餐", "夜宵", "烧烤", "火锅", "奶茶", "咖啡"):
        if keyword in text:
            return "餐饮"
    return "其他"


def _import_account(pay_text, accounts):
    """按「支付方式 / 收付款方式」匹配用户自己的账户，匹配不到就用第 1 个账户。"""
    text = str(pay_text or "")
    for name in sorted(accounts, key=len, reverse=True):
        if name and name in text:
            return name
    for alias, name in (
        ("零钱通", "微信"),
        ("零钱", "微信"),
        ("微信", "微信"),
        ("余额宝", "余额宝"),
        ("余额", "支付宝"),
        ("支付宝", "支付宝"),
        ("银行", "银行卡"),
    ):
        if alias in text and (name in accounts or not accounts):
            return name
    return accounts[0] if accounts else database.DEFAULT_ACCOUNT


def _import_similar(left, right):
    """商户相似度：一方包含另一方，或 difflib 相似度 >= 0.6。"""
    left = re.sub(r"\s+", "", left or "")
    right = re.sub(r"\s+", "", right or "")
    if not left or not right:
        return False
    return left in right or right in left or difflib.SequenceMatcher(None, left, right).ratio() >= 0.6


def _import_recent_records():
    """取当前用户最近 10 天的账目，用于导入去重。"""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=IMPORT_DUPLICATE_DAYS)).strftime("%Y-%m-%d")
    records = database.list_records()
    return [record for record in records if (record.get("date") or "") >= cutoff]


@app.route("/api/import/parse", methods=["POST"])
@login_required
def import_parse():
    """解析微信/支付宝导出的 CSV / Excel，返回预览数据与重复标记（不写库）。"""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="请选择要导入的 CSV 或 Excel 文件"), 400

    frame, error_message = _import_dataframe(upload)
    if error_message is not None:
        return jsonify(error=error_message), 400
    if frame is None or frame.empty:
        return jsonify(error="文件里没有可解析的流水"), 400

    columns = list(frame.columns)
    time_column = _import_pick_column(columns, IMPORT_TIME_KEYWORDS)
    amount_column = _import_pick_column(columns, IMPORT_AMOUNT_KEYWORDS)
    merchant_column = _import_pick_column(columns, IMPORT_MERCHANT_KEYWORDS)
    type_column = _import_pick_column(columns, IMPORT_TYPE_KEYWORDS)
    note_column = _import_pick_column(columns, IMPORT_NOTE_KEYWORDS)
    status_column = _import_pick_column(columns, IMPORT_STATUS_KEYWORDS)
    pay_column = _import_pick_column(columns, IMPORT_PAY_KEYWORDS)

    if amount_column is None:
        return jsonify(error="没找到金额列，请确认是微信 / 支付宝导出的账单文件"), 400
    if time_column is None:
        return jsonify(error="没找到交易时间列，请确认是微信 / 支付宝导出的账单文件"), 400

    header_text = " ".join(str(item) for item in columns)
    source = "alipay" if ("支付宝" in header_text or "交易号" in header_text) else "wechat"

    accounts = [item["name"] for item in database.list_accounts()]
    recent = _import_recent_records()
    items = []
    skipped = 0

    for _, row in frame.iterrows():
        if len(items) >= IMPORT_MAX_ROWS:
            break
        amount = _import_amount(row.get(amount_column))
        date = _import_date(row.get(time_column))
        record_type = _import_type(row.get(type_column) if type_column else "")
        status = str(row.get(status_column) or "") if status_column else ""
        merchant = str(row.get(merchant_column) or "").strip() if merchant_column else ""
        note = str(row.get(note_column) or "").strip() if note_column else ""

        invalid = (
            amount is None
            or amount <= 0
            or date is None
            or record_type is None
            or "退款" in status
            or "关闭" in status
            or "失败" in status
        )
        if invalid:
            skipped += 1
            continue

        duplicate = None
        for record in recent:
            if abs(float(record.get("amount") or 0) - amount) > 0.005:
                continue
            if (record.get("date") or "")[:10] != date:
                continue
            if _import_similar(merchant or note, record.get("note") or ""):
                duplicate = record
                break

        items.append(
            {
                "date": date,
                "amount": amount,
                "type": record_type,
                "category": _import_category(merchant, note),
                "account": _import_account(row.get(pay_column) if pay_column else "", accounts),
                "note": note or merchant or "导入流水",
                "merchant": merchant,
                "is_duplicate": duplicate is not None,
                "duplicate_id": duplicate.get("id") if duplicate else None,
            }
        )

    duplicate_count = sum(1 for item in items if item["is_duplicate"])
    return jsonify(
        source=source,
        filename=upload.filename,
        total=len(items),
        duplicate_count=duplicate_count,
        skipped=skipped,
        items=items,
    )


@app.route("/api/import/confirm", methods=["POST"])
@login_required
def import_confirm():
    """把预览里勾选的流水批量写进 records，同步账户余额并记录 import_history。"""
    data = request.get_json(silent=True) or {}
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify(error="没有勾选任何流水"), 400

    source = data.get("source") if data.get("source") in database.IMPORT_SOURCES else "wechat"
    filename = data.get("filename") or ""
    imported = 0
    duplicated = 0
    failed = []

    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            failed.append({"index": index, "error": "数据格式不对"})
            continue
        amount = _import_amount(item.get("amount"))
        date = _import_date(item.get("date"))
        record_type = _import_type(item.get("type"))
        if amount is None or amount <= 0 or date is None or record_type is None:
            failed.append({"index": index, "error": "金额 / 日期 / 收支类型不合法"})
            continue
        if item.get("is_duplicate"):
            duplicated += 1
            continue

        category_name = (item.get("category") or "其他").strip()
        try:
            category = database.ensure_category(category_name)
        except database.RecordError:
            category = database.ensure_category("其他")
        account = (item.get("account") or database.DEFAULT_ACCOUNT).strip()
        # 商户 + 商品都写进备注：下次导入同一份账单时，10 天去重能命中商户
        merchant = (item.get("merchant") or "").strip()
        note_text = (item.get("note") or "").strip()
        note = (merchant + " " + note_text).strip() or "导入流水"
        note = note[:200]

        record_id, error_message = database.add_record(
            amount,
            category["name"] if isinstance(category, dict) else category_name,
            note,
            date,
            account,
            record_type,
            category["id"] if isinstance(category, dict) else None,
            "",
            "",
            0,
        )
        if error_message is not None:
            failed.append({"index": index, "error": error_message})
            continue
        imported += 1

    history = database.add_import_history(
        source, len(raw_items), imported, duplicated, filename
    )
    return jsonify(
        imported=imported,
        duplicated=duplicated,
        failed=failed,
        total=len(raw_items),
        history=history,
    )


# ---------------- AI 记忆库管理（v0.11.4，后台 Tab 用） ----------------


@app.route("/api/ai-memory", methods=["GET"])
def list_ai_memory():
    """AI 纠错记忆列表，新的在前；?limit=N 控制条数（1~200）。"""
    raw_limit = request.args.get("limit", "50")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify(error="limit 必须是整数"), 400
    items = database.list_ai_memories(limit)
    return jsonify(items=items, total=len(items))


@app.route("/api/ai-memory", methods=["POST"])
def create_ai_memory():
    """管理端手动补一条纠错记忆（body：corrected_category 必填）。"""
    data = request.get_json(silent=True) or {}
    try:
        memory = database.add_ai_memory(
            data.get("original_text"),
            data.get("raw_category"),
            data.get("corrected_category"),
            note=data.get("note") if isinstance(data.get("note"), str) else "",
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(memory), 201


@app.route("/api/ai-correction-log", methods=["GET"])
def list_ai_correction_log():
    """后台右栏：最近的 AI 纠错审计日志（新的在前），?limit=N 控制条数（1~200）。"""
    raw_limit = request.args.get("limit", "30")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify(error="limit 必须是整数"), 400
    items = database.list_ai_correction_logs(limit)
    return jsonify(items=items, total=len(items))


@app.route("/api/ai-memory/<int:memory_id>", methods=["DELETE"])
def remove_ai_memory(memory_id):
    """删一条纠错记忆；删掉后下次解析就不再带这条 few-shot。"""
    if not database.delete_ai_memory(memory_id):
        return jsonify(error="记忆不存在或已被删除"), 404
    return jsonify(removed=True, id=memory_id)


@app.route("/api/records", methods=["GET"])
def list_records():
    """读出账目，支持三个筛选条件（可叠加）：

    - ?account=微信        只看这个账户的流水
    - ?category_id=7       只看这个具体分类（一级或二级都行）
    - ?parent_id=1         只看这个一级分类，连同它下面的所有二级分类
    """
    account = (request.args.get("account") or "").strip() or None

    category_id = request.args.get("category_id")
    if category_id is not None and not str(category_id).strip():
        category_id = None
    elif category_id is not None:
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            return jsonify(error="category_id 必须是整数"), 400

    parent_id = request.args.get("parent_id")
    if parent_id is not None and not str(parent_id).strip():
        parent_id = None
    elif parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify(error="parent_id 必须是整数"), 400

    rows = database.list_records(account, category_id, parent_id)
    return jsonify(
        count=len(rows),
        account=account,
        category_id=category_id,
        parent_id=parent_id,
        records=rows,
    )


@app.route("/api/search", methods=["GET"])
def search_records_api():
    """全局搜索（v0.11.8）：?q=关键词&limit=200，备注/分类/账户/金额随便搜。

    只读接口，和账单列表一样公开；前端拿到后每 10 条一批渲染成搜索浮窗。
    """
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify(items=[], total=0)
    if len(keyword) > 50:
        return jsonify(error="关键词太长了，控制在 50 字以内"), 400
    raw_limit = request.args.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify(error="limit 必须是整数"), 400
    items = database.search_records(keyword, limit)
    return jsonify(items=items, total=len(items))


@app.route("/api/records/<int:record_id>", methods=["PUT"])
def update_record(record_id):
    """整条覆盖式更新一条账目，并修正余额。前端编辑时会把表单里的全部字段一起发上来。"""
    payload, error = _parse_record(request.get_json(silent=True))
    if error is not None:
        return error

    updated, error_message = database.update_record(
        record_id,
        payload["amount"],
        payload["category"],
        payload["note"],
        payload["date"],
        payload["account"],
        payload["type"],
        payload["category_id"],
        payload["formula"],
        payload["to_account"],
        payload["fee"],
    )
    if error_message is not None:
        return jsonify(error=error_message), 400
    if not updated:
        return jsonify(error="记录不存在"), 404

    cache_ext.invalidate_record_caches()
    return jsonify(id=record_id, **payload)


@app.route("/api/records/<int:record_id>/reimbursement", methods=["PUT"])
def update_record_reimbursement(record_id):
    """只改一条账目的报销设置（开关 / 报销人 / 报销金额 / 已报销），不动金额与余额。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    is_reimbursable = data.get("is_reimbursable", False)
    if not isinstance(is_reimbursable, bool):
        return jsonify(error="is_reimbursable 必须是布尔值"), 400

    contact_id = data.get("contact_id")
    if contact_id is not None and (
        isinstance(contact_id, bool) or not isinstance(contact_id, int)
    ):
        return jsonify(error="contact_id 必须是整数"), 400

    try:
        total_reimbursement = round(float(data.get("total_reimbursement") or 0), 2)
        reimbursed_amount = round(float(data.get("reimbursed_amount") or 0), 2)
    except (TypeError, ValueError):
        return jsonify(error="金额必须是数字"), 400

    updated, error_message = database.set_record_reimbursement(
        record_id,
        is_reimbursable,
        contact_id,
        total_reimbursement,
        reimbursed_amount,
    )
    if error_message is not None:
        return jsonify(error=error_message), 400
    if not updated:
        return jsonify(error="记录不存在"), 404

    return jsonify(record=database.get_record(record_id))


@app.route("/api/records/<int:record_id>", methods=["DELETE"])
def remove_record(record_id):
    """删除一条账目：移进回收站并回滚余额，id 不存在时返回 404。"""
    deleted = database.soft_delete_record(record_id)
    if not deleted:
        return jsonify(error="记录不存在"), 404
    cache_ext.invalidate_record_caches()
    return jsonify(deleted=record_id, trashed=True)


# ---------------- 回收站（旧版沿用） ----------------

@app.route("/api/records/trash", methods=["GET"])
def list_trash():
    """回收站：deleted_at 不为空的账目。"""
    records = database.list_deleted_records()
    return jsonify(count=len(records), records=records)


@app.route("/api/records/<int:record_id>/restore", methods=["PUT"])
def restore_record(record_id):
    """从回收站恢复一条账目，余额影响重新套上。"""
    restored = database.restore_record(record_id)
    if not restored:
        return jsonify(error="回收站里没有这条记录"), 404
    record = database.get_record(record_id)
    return jsonify(record=record)


@app.route("/api/records/<int:record_id>/purge", methods=["DELETE"])
def purge_record(record_id):
    """彻底删除：只允许删回收站里的账目。"""
    purged = database.purge_record(record_id)
    if not purged:
        return jsonify(error="回收站里没有这条记录"), 404
    return jsonify(purged=record_id)


# ---------------- 分类接口 ----------------

@app.route("/api/categories", methods=["GET"])
def list_categories():
    """两级分类树。一级分类带 children，前端拿它做级联下拉框。

    v0.13.1 停用语义：默认只返回启用中的分类；`?include_disabled=1` 返回全量，
    **仅允许分类管理弹窗的「已停用」管理区使用**（D18：编辑态走前端零请求合成，不用这个开关）。
    """
    include_disabled = request.args.get("include_disabled") in ("1", "true", "True")
    tree = database.list_categories_tree(include_disabled=include_disabled)
    total = sum(1 + len(node["children"]) for node in tree)
    return jsonify(count=len(tree), total=total, categories=tree)


@app.route("/api/categories", methods=["POST"])
def create_category():
    """新建分类。body: {"name": "咖啡", "parent_id": 1}（parent_id 省略 = 一级分类）"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="name 必须是非空字符串"), 400

    parent_id = data.get("parent_id")
    if parent_id is not None and (
        isinstance(parent_id, bool) or not isinstance(parent_id, int)
    ):
        return jsonify(error="parent_id 必须是整数或 null"), 400

    category_type = data.get("type")
    if category_type is not None and category_type not in ("expense", "income"):
        return jsonify(error="type 只能是 expense 或 income"), 400
    category, error = database.create_category(
        name.strip(),
        parent_id,
        category_type if category_type in ("expense", "income") else "expense",
    )
    if error is not None:
        # 同名冲突是「资源冲突」409，父级不存在之类是「参数不对」400
        status = 409 if "已存在" in error else 400
        return jsonify(error=error), status
    return jsonify(category), 201


@app.route("/api/categories/<int:category_id>", methods=["PUT"])
def rename_category(category_id):
    """给分类改名。body: {"name": "咖啡奶茶"}（只能改名，不能改父级）"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="name 必须是非空字符串"), 400

    category, error = database.rename_category(category_id, name.strip())
    if error is not None:
        if "不存在" in error:
            return jsonify(error=error), 404
        status = 409 if "已存在" in error else 400
        return jsonify(error=error), status
    return jsonify(category)


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def remove_category(category_id):
    """删分类。还有子分类或还有账目在用它就拒绝（409），避免出现悬空引用。"""
    deleted, error = database.delete_category(category_id)
    if not deleted:
        if "不存在" in error:
            return jsonify(error=error), 404
        return jsonify(error=error), 409
    return jsonify(deleted=category_id)


@app.route("/api/categories/ensure-templates", methods=["POST"])
@login_required
def ensure_category_templates():
    """v0.13.1 A6：给当前登录用户补齐一整套默认分类模板（幂等），返回本次新增条数。

    - 登录后的静默兜底：失败由前端静默（仅 console 留痕），不打断登录流程；
    - 用户在设置 / 分类管理里手动点「同步默认分类」：失败要弹 Toast，故这里返回明确错误。
    「补缺不覆盖」：已经齐了返回 added=0，用户自己删过的分类不会被复活。
    """
    user_id = g.current_user.get("id")
    try:
        added = database.ensure_category_templates(user_id)
    except Exception as exc:  # noqa: BLE001 - 手动点击场景必须能看到错误，转 500 + 中文文案
        print("[v0.13.1] 补齐默认分类失败（用户 %s）：%s" % (user_id, exc), flush=True)
        return jsonify(error="补齐默认分类失败，请稍后重试"), 500
    return jsonify(added=added, categories=database.list_categories_tree())


@app.route("/api/categories/<int:category_id>/disabled", methods=["PATCH", "PUT"])
@login_required
def set_category_disabled(category_id):
    """停用 / 恢复分类（v0.13.1 T05）。body: {"disabled": true|false}

    PATCH 与 PUT 都接（设计文档 §5 写的是 PUT，前端契约写的是 PATCH，两种都能用）。
    「停用」≠「消失」（D16）：行保留、被历史账单引用的值仍可回读（D19），只是不再出现在新增场景的选项里。
    恢复二级分类时若上级仍是停用状态，返回 400「请先恢复上级分类」——
    否则会出现「提示恢复成功、但分类在默认树里看不见」的假成功。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    disabled = data.get("disabled")
    # 只认布尔（兼容 0/1 数字写法），避免 "false" 字符串被当成真值
    if isinstance(disabled, int) and not isinstance(disabled, bool) and disabled in (0, 1):
        disabled = bool(disabled)
    if not isinstance(disabled, bool):
        return jsonify(error="disabled 必须是 true 或 false"), 400

    category, error = database.set_category_disabled(category_id, disabled)
    if error is not None:
        status = 404 if "不存在" in error else 400
        return jsonify(error=error), status
    return jsonify(category=category, disabled=disabled)


@app.route("/api/categories/<int:category_id>/merge", methods=["POST", "PUT"])
@login_required
def merge_categories(category_id):
    """把当前分类合并到另一个分类（v0.13.1 T05）。body: {"target_id": <int>}

    合并语义（D12）：源分类下的账目全部改指向目标分类，源分类置为停用（不物理删除）。
    红线：只改分类字段，不动任何金额字段、不动 accounts.balance。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    target_id = data.get("target_id")
    if isinstance(target_id, bool) or not isinstance(target_id, int):
        return jsonify(error="target_id 必须是整数"), 400

    result, error = database.merge_categories(category_id, target_id)
    if error is not None:
        # 「分类不存在」→ 404（含跨用户：不泄露他人分类是否存在）；其余业务校验失败 → 400
        status = 404 if "不存在" in error else 400
        return jsonify(error=error), status

    return jsonify(
        ok=True,
        moved=result["moved"],
        migrated_records=result["migrated_records"],
        source_id=result["source_id"],
        target_id=result["target_id"],
        disabled_source_ids=result["disabled_source_ids"],
        source=result["source"],
        target=result["target"],
        # Q3：合并后前端直接用这份最新树整体覆盖 state.categories，避免四处增量拼接残留脏状态
        categories=database.list_categories_tree(),
    )


# ---------------- 账户接口 ----------------

@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    """所有账户及当前余额、大类；groups 是按大类分好组的版本，前端下接用。"""
    rows = database.list_accounts()
    return jsonify(
        count=len(rows),
        accounts=rows,
        groups=database.list_accounts_grouped(),
        group_names=list(database.ACCOUNT_GROUPS),
    )


@app.route("/api/accounts", methods=["POST"])
def create_account():
    """新建账户。body: {"name": "招行卡", "group_name": "储蓄账户", "balance": 0}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="name 必须是非空字符串"), 400

    group_name = data.get("group_name", database.DEFAULT_GROUP)
    if not isinstance(group_name, str) or group_name not in database.ACCOUNT_GROUPS:
        return jsonify(
            error="group_name 只能是 " + " / ".join(database.ACCOUNT_GROUPS)
        ), 400

    balance = data.get("balance", 0)
    if isinstance(balance, bool) or not isinstance(balance, (int, float)):
        return jsonify(error="balance 必须是数字"), 400

    # v0.13.3：可选功能类型（normal / investment）；建成投资账户时幂等补「默认」子平台
    account_type = data.get("type", database.DEFAULT_ACCOUNT_TYPE)
    if not isinstance(account_type, str) or account_type not in database.ACCOUNT_TYPES:
        return jsonify(error="type 只能是 normal / investment"), 400

    account, error = database.create_account(name.strip(), group_name, balance, account_type)
    if error is not None:
        status = 409 if "已存在" in error else 400
        return jsonify(error=error), status
    return jsonify(account), 201


@app.route("/api/accounts/<name>", methods=["PUT"])
def update_account(name):
    """改账户：余额和/或大类，至少给一个。

    body: {"balance": 1234.5} 或 {"group_name": "储蓄账户"} 或两个都给
    允许负数：信用卡、花呗这类账户余额本来就可能是负的。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    if (
        "balance" not in data
        and "group_name" not in data
        and "new_name" not in data
        and "type" not in data
    ):
        return jsonify(error="至少要传 new_name / balance / group_name / type 之一"), 400

    # v0.11.6：账户改名（改名后后续余额/大类修改都作用在新名字上）
    final_name = name
    if "new_name" in data:
        new_name = data.get("new_name")
        if not isinstance(new_name, str) or not new_name.strip():
            return jsonify(error="new_name 必须是非空字符串"), 400
        renamed, rename_error = database.rename_account(name, new_name.strip())
        if rename_error is not None:
            status = 409 if "已存在" in rename_error else 400
            return jsonify(error=rename_error), status
        final_name = renamed["name"]

    balance = None
    if "balance" in data:
        balance = data["balance"]
        if isinstance(balance, bool) or not isinstance(balance, (int, float)):
            return jsonify(error="balance 必须是数字"), 400
        # 金额只保留到分，避免 12.345000000001 这种浮点尾巴进库
        balance = round(balance, 2)

    group_name = None
    if "group_name" in data:
        group_name = data["group_name"]
        if not isinstance(group_name, str) or group_name not in database.ACCOUNT_GROUPS:
            return jsonify(
                error="group_name 只能是 " + " / ".join(database.ACCOUNT_GROUPS)
            ), 400

    account_type = None
    if "type" in data:
        account_type = data["type"]
        if not isinstance(account_type, str) or account_type not in database.ACCOUNT_TYPES:
            return jsonify(error="type 只能是 normal / investment"), 400
        # 切到 investment 时数据库层会幂等补「默认」子平台；切回 normal 不删任何数据

    account, error = database.update_account(final_name, balance, group_name, account_type)
    if error is not None:
        return jsonify(error=error), 404 if "不存在" in error else 400
    return jsonify(account)


@app.route("/api/accounts/<name>", methods=["DELETE"])
def remove_account(name):
    """删账户。还有账目挂在这个账户下就拒绝（409）。"""
    deleted, error = database.delete_account(name)
    if not deleted:
        return jsonify(error=error), 404 if "不存在" in error else 409
    return jsonify(deleted=name)


@app.route("/api/accounts/<name>/adjust_balance", methods=["POST"])
def adjust_account_balance(name):
    """快捷改余额（v0.14.0-TST）：直接覆盖余额，并按差额生成一笔收入 / 支出流水。

    body: {"balance": 1234.5, "generate_record": true,
           "note": "账户余额修改", "category_id": 3, "date": "2026-11-05"}

    与 PUT /api/accounts/<name> 的区别：这里会把差额记成账单，让「改余额」在流水里
    留痕；PUT 仍是纯改字段、不产生流水（行内编辑表单继续用它）。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    # 兼容 balance / new_balance 两种键名，前端传哪个都不会 400
    new_balance = data.get("balance", data.get("new_balance"))
    if isinstance(new_balance, bool) or not isinstance(new_balance, (int, float)):
        return jsonify(error="balance 必须是数字"), 400
    if new_balance != new_balance or new_balance in (float("inf"), float("-inf")):
        return jsonify(error="balance 必须是有效数字"), 400

    generate_record = data.get("generate_record", True)
    if not isinstance(generate_record, bool):
        generate_record = bool(generate_record)

    note = data.get("note", "账户余额修改")
    if note is None:
        note = "账户余额修改"
    if not isinstance(note, str):
        return jsonify(error="note 必须是字符串"), 400

    category_id = data.get("category_id")
    if category_id in ("", None):
        category_id = None
    else:
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            return jsonify(error="category_id 必须是整数"), 400

    record_date = data.get("date")
    if record_date in ("", None):
        record_date = None
    elif not isinstance(record_date, str) or not re.match(
        r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$", record_date.strip()
    ):
        return jsonify(error="date 格式应为 YYYY-MM-DD"), 400

    result, error = database.adjust_account_balance(
        name,
        new_balance,
        generate_record=generate_record,
        note=note.strip()[:60],
        category_id=category_id,
        record_date=record_date,
    )
    if error is not None:
        return jsonify(error=error), 404 if "不存在" in error else 400

    # 回带最新账户（含 market_value / total），前端可直接替换 state.accounts 对应项，
    # 不用为了一个数字再拉一次 /api/accounts
    latest = next(
        (item for item in database.list_accounts() if item["name"] == name), None
    )
    payload = dict(result)
    payload["account_detail"] = latest
    # v0.14.1：平账会连带账户余额（statistics 的 balance_total），必须失效缓存
    cache_ext.invalidate_record_caches()
    return jsonify(payload)


@app.route("/api/accounts/merge", methods=["POST"])
def merge_accounts():
    """把 AI 自动建出来的账户合并进用户已有的账户（v0.11.6）。

    body {"source": "微信零钱通", "target": "微信"}：余额相加、账目/借贷迁移后删掉 source。
    """
    data = request.get_json(silent=True) or {}
    source = data.get("source")
    target = data.get("target")
    if not isinstance(source, str) or not source.strip():
        return jsonify(error="source 必须是非空字符串"), 400
    if not isinstance(target, str) or not target.strip():
        return jsonify(error="target 必须是非空字符串"), 400

    account, error_message = database.merge_account(source.strip(), target.strip())
    if error_message is not None:
        status = 404 if "不存在" in error_message else 400
        return jsonify(error=error_message), status
    return jsonify(merged=True, account=account)


@app.route("/api/accounts/batch/delete", methods=["POST"])
def batch_delete_accounts():
    """批量删除账户（v0.11.6）：逐个删，仍挂账目的账户会被跳过并回报原因。"""
    data = request.get_json(silent=True) or {}
    names = data.get("names")
    if not isinstance(names, list) or not names:
        return jsonify(error="names 必须是非空数组"), 400

    deleted = []
    failed = []
    for raw in names:
        if not isinstance(raw, str) or not raw.strip():
            continue
        name = raw.strip()
        ok, error_message = database.delete_account(name)
        if ok:
            deleted.append(name)
        else:
            failed.append({"name": name, "error": error_message})
    return jsonify(deleted=len(deleted), names=deleted, failed=failed)


# ---------------- 投资接口（v0.13.3） ----------------
#
# 全部落在 /api/invest/*，全部挂 @login_required，全部由 database._uid() 做用户隔离。
# 资金口径（team-lead 决策 B）：买入 = 扣 accounts.balance + 写/加仓 holdings，**不写 records**；
# 删除持仓 = 撤销式清仓退款。全项目只有 database.buy_holding / database.liquidate_holding
# 两处能动这两张表，本文件禁止出现第二条扣款路径。

# 单一错误码映射源：数据库层只回中文文案，状态码在这里统一决定，避免各路由各写一套
def _invest_status(error):
    """按数据库层返回的中文文案决定 HTTP 状态码。

    跨用户 / 不存在一律 404（**不用 403**，避免泄露「这条数据存在但不属于你」）。
    """
    if not error:
        return 200
    if "不存在" in error:
        return 404
    # 冲突类：同名 / 已存在 / 平台下还有持仓（先清仓再删）
    if "已有" in error or "同名" in error or "还有" in error:
        return 409
    return 400


def _to_number(value, default=0.0):
    """把请求里的数字字段转成 float；非数字 / 布尔一律回落默认值。"""
    if isinstance(value, bool) or value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# 资产类型 -> 中文品类：投资页选中标的时的展示文案（股票 / 基金 / 黄金）
_INVEST_CATEGORY_LABELS = {"stock": "股票", "fund": "基金", "gold": "黄金", "bond": "债券"}


@app.route("/api/invest/search", methods=["GET"])
@login_required
def invest_search():
    """标的代码 / 名称 / 拼音搜索（东方财富全市场，失败自动降级本地 Mock）。

    `?keyword=005827&limit=10` → 200 {total, items:[{ticker,name,asset_type,price,source}]}
    未命中返回 {total: 0, items: []}（**不是 404**），前端据此显示「没有找到匹配的标的」。
    """
    keyword = request.args.get("keyword", "")
    if not isinstance(keyword, str) or not keyword.strip():
        return jsonify(error="请输入标的名称或代码"), 400
    keyword = keyword.strip()
    if len(keyword) > 50:
        return jsonify(error="搜索关键字不能超过 50 个字"), 400

    limit = _to_number(request.args.get("limit", 10), 10)
    limit = int(limit)
    if limit <= 0 or limit > 50:
        limit = 10

    items, fallback, reason = invest_eastmoney.search_with_fallback_info(keyword, limit)
    if fallback:
        app.logger.warning("[v0.13.4][投资搜索][东财不可用，回退本地字典] %s: %s", keyword, reason)
    # 两种字段名一起下发：code/name/category/type 是新契约，
    # ticker/asset_type/price 是 v0.13.3 前端已在用的旧字段，改契约要同时改前端，没到那一步。
    out = [
        {
            "code": it.get("ticker"),
            "name": it.get("name"),
            "category": _INVEST_CATEGORY_LABELS.get(it.get("asset_type"), "其他"),
            "type": it.get("asset_type"),
            "ticker": it.get("ticker"),
            "asset_type": it.get("asset_type"),
            "price": it.get("price", 0),
            "source": it.get("source"),
        }
        for it in items
    ]
    resp = {"total": len(out), "items": out, "fallback": fallback}
    if fallback:
        # 降级时必须让前端说清楚，别让用户以为「本地字典就是全部市场」
        resp["notice"] = "东方财富接口暂时不可用，已回退本地字典，结果可能不全"
    return jsonify(**resp)


@app.route("/api/invest/board", methods=["GET"])
@login_required
def invest_board():
    """投资看板聚合数据：一次请求拿全持仓 Tab 需要的全部数据。

    `?account=天天基金` → 200 {account, total_market_value, total_cost, day_pl, platforms}
    市值 / 盈亏一律服务端算好下发，前端不做二次计算。
    """
    account = request.args.get("account", "")
    if not isinstance(account, str) or not account.strip():
        return jsonify(error="请先指定要查看的投资账户"), 400

    board, error = database.list_invest_board(account.strip())
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(board)


@app.route("/api/invest/platforms", methods=["GET"])
@login_required
def list_invest_platforms():
    """某投资账户下的子平台列表（带持仓数与市值），给「新建持仓」弹窗的下拉用。"""
    account = request.args.get("account", "")
    if not isinstance(account, str) or not account.strip():
        return jsonify(error="请先指定投资账户"), 400

    platforms, error = database.list_invest_platforms(account.strip())
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(count=len(platforms), platforms=platforms, account=account.strip())


@app.route("/api/invest/platforms", methods=["POST"])
@login_required
def create_invest_platform():
    """新建子平台。body: {"account": "天天基金", "name": "支付宝"}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    account = data.get("account")
    if not isinstance(account, str) or not account.strip():
        return jsonify(error="请先指定投资账户"), 400
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="平台名称不能为空"), 400

    platform, error = database.create_platform(account.strip(), name.strip())
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(platform), 201


@app.route("/api/invest/platforms/<int:pid>", methods=["PUT"])
@login_required
def update_invest_platform(pid):
    """子平台改名。body: {"name": "支付宝"}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="平台名称不能为空"), 400

    platform, error = database.rename_platform(pid, name.strip())
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(platform)


@app.route("/api/invest/platforms/<int:pid>", methods=["DELETE"])
@login_required
def delete_invest_platform(pid):
    """删子平台。平台下还有持仓就拒绝（409），先清仓再删——删空平台不涉及任何资金。"""
    deleted, error = database.delete_platform(pid)
    if not deleted:
        return jsonify(error=error), _invest_status(error)
    return jsonify(deleted=pid)


@app.route("/api/invest/holdings", methods=["POST"])
@login_required
def create_invest_holding():
    """**全局唯一的投资入账口**（手动建仓 / AI 确认建仓 / 未来的 CSV 导入都走这里）。

    body: {
      "account": "天天基金", "platform_id": 3, "ticker": "005827",
      "name": "易方达蓝筹精选", "asset_type": "fund",
      "shares": 1000, "cost_price": 1.0, "amount": 1000,
      "dca": {"amount": 500, "frequency": "monthly", "next_date": "2026-11-01"}
    }
    201 {holding, platform, dca, record, balance}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    account = data.get("account")
    if not isinstance(account, str) or not account.strip():
        return jsonify(error="请先指定投资账户"), 400
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify(error="请填写标的名称"), 400

    # 决策 D 的写入侧：只允许在**建仓**时给定金额三要素，改只能改元信息
    price = data.get("price")
    if price is None:
        price = data.get("cost_price")
    dca = data.get("dca")
    if not isinstance(dca, dict):
        dca = None

    # v0.13.3：扣款来源账户（可选）。空串 = 用投资账户自己的可用资金。
    source_account = data.get("source_account", "")
    if source_account is None:
        source_account = ""
    if not isinstance(source_account, str):
        return jsonify(error="source_account 必须是账户名"), 400

    payload, error = database.buy_holding(
        account.strip(),
        platform_id=data.get("platform_id"),
        name=name.strip(),
        ticker=str(data.get("ticker") or "").strip(),
        asset_type=data.get("asset_type", database.DEFAULT_ASSET_TYPE),
        shares=_to_number(data.get("shares"), 0),
        price=_to_number(price, 0),
        amount=_to_number(data.get("amount"), 0),
        dca=dca,
        source_account=source_account.strip(),
    )
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(payload), 201


@app.route("/api/invest/holdings/<int:hid>", methods=["PUT"])
@login_required
def update_invest_holding(hid):
    """改持仓**元信息**（名称 / 代码 / 资产类型 / 平台）。

    决策 D：**份额与成本一律不许改**——金额填错请走「删除（清仓退款）后重建」，
    否则 shares / cost_price / cost_total 三者漂移，勾稽再也对齐不上。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    for forbidden in ("shares", "cost_price", "price", "cost_total", "amount"):
        if forbidden in data:
            return jsonify(
                error="份额与成本不支持修改，金额填错了请先清仓再重新建仓"
            ), 400

    allowed = ("name", "ticker", "asset_type", "platform_id")
    if not any(key in data for key in allowed):
        return jsonify(error="至少要传 name / ticker / asset_type / platform_id 之一"), 400

    if "name" in data and (not isinstance(data["name"], str) or not data["name"].strip()):
        return jsonify(error="标的名称不能为空"), 400

    holding, error = database.update_holding_meta(
        hid,
        name=data["name"].strip() if "name" in data else None,
        ticker=data.get("ticker"),
        asset_type=data.get("asset_type"),
        platform_id=data.get("platform_id"),
    )
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(holding)


@app.route("/api/invest/holdings/<int:hid>", methods=["DELETE"])
@login_required
def delete_invest_holding(hid):
    """撤销式清仓：可用资金加回累计成本并删除持仓，该持仓的定投计划一并暂停。"""
    payload, error = database.liquidate_holding(hid)
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(payload)


@app.route("/api/invest/dca-plans", methods=["POST"])
@login_required
def create_dca_plan():
    """给持仓挂一条定投计划。本期只落库 + 展示，不自动生成任何账目。

    body: {"holding_id": 5, "amount": 500, "frequency": "monthly", "next_date": "2026-11-01"}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    holding_id = data.get("holding_id")
    try:
        holding_id = int(holding_id)
    except (TypeError, ValueError):
        return jsonify(error="holding_id 必须是整数"), 400

    if "amount" not in data:
        return jsonify(error="请填写定投金额"), 400

    plan, error = database.create_dca_plan(
        holding_id,
        _to_number(data.get("amount"), 0),
        frequency=data.get("frequency"),
        next_date=str(data.get("next_date") or "").strip(),
        status=data.get("status"),
    )
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(plan), 201


@app.route("/api/invest/dca-plans/<int:did>", methods=["PUT"])
@login_required
def update_dca_plan(did):
    """改定投计划（金额 / 频率 / 下次扣款日 / 状态），只改计划本身，不产生任何账目。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    plan, error = database.update_dca_plan(
        did,
        amount=data.get("amount"),
        frequency=data.get("frequency"),
        next_date=data.get("next_date"),
        status=data.get("status"),
    )
    if error is not None:
        return jsonify(error=error), _invest_status(error)
    return jsonify(plan)


@app.route("/api/invest/dca-plans/<int:did>", methods=["DELETE"])
@login_required
def delete_dca_plan(did):
    """删定投计划。计划不牵涉任何余额，可安全物理删除。"""
    deleted, error = database.delete_dca_plan(did)
    if not deleted:
        return jsonify(error=error), _invest_status(error)
    return jsonify(deleted=did)


@app.route("/api/records/batch/delete", methods=["POST"])
def batch_delete_records():
    """批量删账单（v0.11.6）：走软删除，每条都按原有规则回滚账户余额。"""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        return jsonify(error="ids 必须是非空数组"), 400

    deleted = 0
    failed = []
    for raw in ids:
        try:
            record_id = int(raw)
        except (TypeError, ValueError):
            failed.append({"id": raw, "error": "id 必须是整数"})
            continue
        try:
            ok = database.delete_record(record_id)
        except database.RecordError as exc:
            failed.append({"id": record_id, "error": str(exc)})
            continue
        if ok:
            deleted += 1
        else:
            failed.append({"id": record_id, "error": "账单不存在或已删除"})
    return jsonify(deleted=deleted, failed=failed)


@app.route("/api/records/batch/category", methods=["PUT"])
def batch_update_record_category():
    """批量改分类（v0.11.6）：只动分类字段，不重算余额。"""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    category = data.get("category")
    if not isinstance(ids, list) or not ids:
        return jsonify(error="ids 必须是非空数组"), 400
    if not isinstance(category, str) or not category.strip():
        return jsonify(error="category 必须是非空字符串"), 400

    changed, error_message = database.set_records_category(ids, category.strip())
    if error_message is not None:
        return jsonify(error=error_message), 400
    return jsonify(updated=changed)


@app.route("/api/statistics", methods=["GET"])
def statistics():
    """总览：总收入、总支出、总余额，给首页三张卡片用。

    v0.14.1：结果走 cache_ext 的 @cache.memoize(timeout=600)。缓存 key 显式
    带 uid，且把同一个 uid 传给 database.get_statistics(user_id=...)，
    key 与 SQL 用同一个值，不会因为请求上下文串到别的用户。
    """
    uid = database.current_user_id()
    return jsonify(cache_ext.statistics_data(uid))


@app.route("/api/records/recent_7_days", methods=["GET"])
def recent_7_days():
    """近 7 天收支趋势（图表数据），同样按 uid 维度 memoize(600s)。"""
    uid = database.current_user_id()
    return jsonify(cache_ext.recent_7_days_data(uid))


@app.after_request
def _invalidate_caches_after_write(response):
    """缓存失效总闸门：任何成功的写请求之后清掉统计 / 近 7 天缓存。

    项目里写路径有几十条（普通记账、AI 记账、图片记账、导入确认、批量删除、
    还原 / 彻底删除、报销、账户调平、账户合并、借贷结清……），逐条在函数末尾
    补 delete_memoized 一定会漏。这里在「响应即将发出」时统一清一次，等价于
    在每条写逻辑末尾执行且不会漏；几个主写接口里另外显式调了一次做双保险。
    只对 2xx 生效：失败的请求没改数据，不必白白失效。
    """
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and response.status_code < 400
    ):
        cache_ext.invalidate_record_caches()
    return response


# ---------------- 通知中心（v0.06.2） ----------------

# v0.14.0-TST 安全加固（S4）：通知正文统一收敛为纯文本。
# 后端只保留换行语义、剥掉全部 HTML 标签；前端一律 textContent 渲染，
# 从根上阻断「任意登录用户写通知 → 游客打开首页执行脚本」的存储型 XSS。
_NOTICE_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.I)
_NOTICE_BLOCK_END_RE = re.compile(r"</\s*(?:div|p|li|tr|h[1-6])\s*>", re.I)
_NOTICE_BLOCK_START_RE = re.compile(r"<\s*(?:div|p|li|tr|h[1-6])\b[^>]*>", re.I)
_NOTICE_ANY_TAG_RE = re.compile(r"<[^>]*>")
_NOTICE_MULTI_NL_RE = re.compile(r"\n{3,}")
# 危险元素连同内部文本一起丢弃，避免「标签被剥掉、载荷文字还在」
_NOTICE_DANGEROUS_BLOCK_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|template|svg|math)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.I | re.S,
)
_NOTICE_DANGEROUS_OPEN_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|template|svg|math)\b[^>]*>", re.I
)


def _sanitize_notice_content(raw):
    """把通知正文净化为纯文本：块级标签 / <br> 转换行，其余标签全部剥离。"""
    if not isinstance(raw, str):
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _NOTICE_DANGEROUS_BLOCK_RE.sub("", text)
    text = _NOTICE_DANGEROUS_OPEN_RE.sub("", text)
    text = _NOTICE_BR_RE.sub("\n", text)
    text = _NOTICE_BLOCK_END_RE.sub("\n", text)
    text = _NOTICE_BLOCK_START_RE.sub("", text)
    text = _NOTICE_ANY_TAG_RE.sub("", text)
    # 只还原最常见排版实体，绝不做完整 unescape：否则 &lt;script&gt; 会重新
    # 变回 <script> 字样。前端一律 textContent 渲染，本就不需要反转义。
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _NOTICE_MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


@app.route("/api/notifications", methods=["GET"])
def list_notifications():
    """通知列表。

    默认只回 status=published，前台信封面板按时间倒序展示；
    后台传 ?include=drafts 才拿到全部（含待审核草稿）。
    """
    include = (request.args.get("include") or "").strip()
    if include in ("drafts", "all"):
        return jsonify(notifications=database.list_notifications())
    # v0.11.7：前台严格按生效时间过滤，visible_at 没到今天的通知绝对不可见
    return jsonify(
        notifications=database.list_notifications(status="published", visible_only=True),
    )


@app.route("/api/notifications", methods=["POST"])
def create_notification():
    """后台手动写一条通知（v0.11.3：一律进「待审核草稿」，必须人工点发布才对外）。"""
    data = request.get_json(silent=True) or {}

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return jsonify(error="title 必须是非空字符串"), 400
    if len(title.strip()) > 80:
        return jsonify(error="title 最多 80 个字符"), 400

    content = data.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        return jsonify(error="content 必须是字符串"), 400
    if len(content) > 20000:
        return jsonify(error="content 太长了，最多 20000 个字符"), 400
    content = _sanitize_notice_content(content)

    image_url = data.get("image_url", "")
    if image_url is None:
        image_url = ""
    if not isinstance(image_url, str):
        return jsonify(error="image_url 必须是字符串"), 400
    # 只收站内相对路径或 http(s) 链接，防止塞进 javascript: 之类的伪协议
    if image_url and not (
        image_url.startswith("/static/")
        or image_url.startswith("http://")
        or image_url.startswith("https://")
    ):
        return jsonify(error="image_url 只能是 /static/ 下的路径或 http(s) 链接"), 400

    publish_date = data.get("publish_date")
    if publish_date is not None and not isinstance(publish_date, str):
        return jsonify(error="publish_date 必须是字符串"), 400
    visible_at = data.get("visible_at")
    if visible_at is not None and not isinstance(visible_at, str):
        return jsonify(error="visible_at 必须是字符串"), 400
    # v0.11.7：发布时间留空时用定时发布时间兜底；生效时间永远单独存 visible_at
    publish_date = (publish_date or "").strip() or None
    visible_at = (visible_at or "").strip() or None
    if publish_date is None and visible_at is not None:
        publish_date = visible_at

    try:
        notification = database.create_notification(
            title, content, image_url, publish_date, status="draft", visible_at=visible_at
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(notification), 201


@app.route("/api/notifications/<int:notify_id>", methods=["PUT"])
def update_notification(notify_id):
    """开发者修改已发布的通知：只改 body 里出现的字段，没传的保持原样。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    title = data.get("title")
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            return jsonify(error="title 必须是非空字符串"), 400
        if len(title.strip()) > 80:
            return jsonify(error="title 最多 80 个字符"), 400

    content = data.get("content")
    if content is not None:
        if not isinstance(content, str):
            return jsonify(error="content 必须是字符串"), 400
        if len(content) > 20000:
            return jsonify(error="content 太长了，最多 20000 个字符"), 400
        content = _sanitize_notice_content(content)

    image_url = data.get("image_url")
    if image_url is not None:
        if not isinstance(image_url, str):
            return jsonify(error="image_url 必须是字符串"), 400
        if image_url and not (
            image_url.startswith("/static/")
            or image_url.startswith("http://")
            or image_url.startswith("https://")
        ):
            return jsonify(error="image_url 只能是 /static/ 下的路径或 http(s) 链接"), 400

    publish_date = data.get("publish_date")
    if publish_date is not None and not isinstance(publish_date, str):
        return jsonify(error="publish_date 必须是字符串"), 400
    visible_at = data.get("visible_at")
    if visible_at is not None and not isinstance(visible_at, str):
        return jsonify(error="visible_at 必须是字符串"), 400
    publish_date = (publish_date or "").strip() or None if publish_date is not None else None
    visible_at = (visible_at or "").strip() or None if visible_at is not None else None
    # 展示时间留空、但给了定时发布时间：用定时发布时间兜底
    if publish_date is None and visible_at is not None:
        publish_date = visible_at

    try:
        notification = database.update_notification(
            notify_id,
            title=title,
            content=content,
            image_url=image_url,
            publish_date=publish_date,
            visible_at=visible_at,
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    if notification is None:
        return jsonify(error="通知不存在"), 404
    return jsonify(notification)


@app.route("/api/notifications/<int:notify_id>", methods=["DELETE"])
def delete_notification(notify_id):
    """删通知。找不到就是 404，前端 Toast 直接显示。"""
    if not database.delete_notification(notify_id):
        return jsonify(error="通知不存在"), 404
    return jsonify(deleted=notify_id)


@app.route("/api/notifications/draft", methods=["POST"])
def draft_notification():
    """AI 全自动起草当前版本更新公告（v0.11.3）。

    前端不再传主题：后端自己读当前版本号 + docs/dev-log.md 里该版本的真实日志，
    生成标题以「版本号 版本更新：」开头的草稿，状态 draft 等人工审核。
    """
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    version = detect_version()
    hint = data.get("topic")
    if hint is not None and not isinstance(hint, str):
        return jsonify(error="topic 必须是字符串"), 400

    try:
        draft = ai_service.generate_notification(
            version=version, hint=(hint or "").strip()
        )
    except ai_service.AIServiceError as exc:
        return jsonify(error=str(exc)), 502

    try:
        notification = database.create_notification(
            draft["title"], _sanitize_notice_content(draft.get("content", "")), "", None, status="draft"
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(draft=notification, version=version), 201


@app.route("/api/notifications/<int:notify_id>/publish", methods=["PUT"])
def publish_notification(notify_id):
    """一键发布草稿：status 改 published，发布时间刷新为现在。"""
    # 安全兜底：历史草稿可能含旧版写入的 HTML，发布前再净化一次
    for existing in database.list_notifications():
        if int(existing.get("id") or 0) == notify_id:
            cleaned = _sanitize_notice_content(existing.get("content") or "")
            if cleaned != (existing.get("content") or ""):
                database.update_notification(notify_id, content=cleaned)
            break
    notification = database.publish_notification(notify_id)
    if notification is None:
        return jsonify(error="通知不存在"), 404
    return jsonify(notification)


def _save_upload_image(upload):
    """校验并保存一张图片；返回 (url, None)，失败返回 (None, 中文错误)。"""
    if upload is None or not upload.filename:
        return None, "没有收到文件，字段名应为 file"

    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "只支持 png / jpg / jpeg / gif / webp 图片"

    data = upload.read()
    if not data:
        return None, "图片是空文件"
    if len(data) > MAX_UPLOAD_BYTES:
        return None, "图片不能超过 5MB"

    # 文件名用 uuid 重命名：避免中文名、空格、同名覆盖，也顺带切断路径穿越
    filename = uuid.uuid4().hex + ext
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as handle:
        handle.write(data)
    return "/static/uploads/" + filename, None


def _save_avatar_image(upload):
    """头像专用落盘：存进 static/uploads/avatars/，文件名 uuid 防重名、防路径穿越。

    返回 (访问路径 /static/uploads/avatars/<uuid>.<ext>, None)，失败返回 (None, 中文错误)。
    DB 只存这个相对路径，重启后 Flask 仍能通过 /static 直接服务。
    """
    if upload is None or not upload.filename:
        return None, "没有收到文件，字段名应为 file"
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "只支持 png / jpg / jpeg / gif / webp 图片"
    data = upload.read()
    if not data:
        return None, "图片是空文件"
    if len(data) > MAX_UPLOAD_BYTES:
        return None, "图片不能超过 5MB"
    # 目录可能被人手动删掉，写前兜底补建
    os.makedirs(AVATAR_DIR, exist_ok=True)
    filename = uuid.uuid4().hex + ext
    with open(os.path.join(AVATAR_DIR, filename), "wb") as handle:
        handle.write(data)
    return "/static/uploads/avatars/" + filename, None


def _delete_avatar_file(url):
    """删除被替换掉的旧头像文件；只认 /static/uploads/avatars/ 前缀，绝不接受任意路径。"""
    prefix = "/static/uploads/avatars/"
    if not url or not url.startswith(prefix):
        return
    name = url[len(prefix):]
    # 阻断任何路径穿越（如 ../）；只接受纯文件名
    if name != os.path.basename(name) or not name:
        return
    path = os.path.join(AVATAR_DIR, name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


@app.route("/api/upload", methods=["POST"])
def upload_image():
    """接收 multipart 表单里的 file 字段，存进 static/uploads，返回可直接访问的 URL。"""
    url, error = _save_upload_image(request.files.get("file"))
    if error:
        return jsonify(error=error), 400
    return jsonify(url=url, filename=url.rsplit("/", 1)[-1]), 201


# ---------------- 访问密码接口（v0.11.1） ----------------


@app.route("/api/access/config", methods=["GET"])
def access_config():
    """前端启动先问这个：有没有设密码、验证超时多久。"""
    return jsonify(database.get_access_config())


@app.route("/api/access/verify", methods=["POST"])
def access_verify():
    """交密码换 token；没设密码也发一个 token，前端逻辑保持统一。"""
    data = request.get_json(silent=True) or {}
    config = database.get_access_config()

    if config["protected"]:
        password = data.get("password")
        if not isinstance(password, str) or not password:
            return jsonify(error="请输入访问密码", code="access_denied"), 400
        if not database.verify_access_password(password):
            return jsonify(error="密码不正确，请重新输入", code="access_denied"), 401

    token = database.create_access_session()
    return jsonify(
        ok=True,
        token=token,
        protected=config["protected"],
        timeout_minutes=config["timeout_minutes"],
    )


@app.route("/api/access/passwords", methods=["GET"])
def access_passwords():
    """后台设置面板：密码列表（只有掩码序号）+ 当前超时。"""
    config = database.get_access_config()
    return jsonify(
        passwords=database.list_access_passwords(),
        timeout_minutes=config["timeout_minutes"],
        protected=config["protected"],
    )


@app.route("/api/access/passwords/reveal", methods=["POST"])
def reveal_access_password():
    """查看明文密码（v0.11.2）：必须现场交当前密码，独立二次验证。

    这里刻意不走 _fresh_admin_check：5 分钟内免密也不放行，必须每次重新输入。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    password = data.get("password")
    if not isinstance(password, str) or not password:
        return jsonify(error="请输入当前密码", code="access_denied"), 400

    ok, error, plain = database.reveal_access_password(data.get("index"), password)
    if not ok:
        code = "access_denied" if error == "当前密码不正确" else "bad_request"
        status = 401 if code == "access_denied" else 400
        return jsonify(error=error, code=code), status
    return jsonify(index=int(data.get("index")), password=plain)


@app.route("/api/access/passwords", methods=["POST"])
def add_access_password():
    """新增密码。敏感操作：最近 5 分钟内没验证过就要重新输当前密码。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    denied = _fresh_admin_check(data)
    if denied is not None:
        return denied

    password = data.get("password")
    if not isinstance(password, str):
        return jsonify(error="password 必须是字符串"), 400

    ok, error, count = database.add_access_password(password)
    if not ok:
        return jsonify(error=error), 400
    return jsonify(added=True, password_count=count,
                   passwords=database.list_access_passwords()), 201


@app.route("/api/access/passwords/<int:index>", methods=["DELETE"])
def delete_access_password(index):
    """删除指定序号的密码，同样要 5 分钟内验证过。"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    denied = _fresh_admin_check(data)
    if denied is not None:
        return denied

    ok, error, count = database.remove_access_password(index)
    if not ok:
        return jsonify(error=error), 400
    return jsonify(deleted=index, password_count=count,
                   passwords=database.list_access_passwords())


@app.route("/api/access/timeout", methods=["PUT"])
def update_access_timeout():
    """调验证超时（10 分钟 ~ 1440 分钟），同样要 5 分钟内验证过。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    denied = _fresh_admin_check(data)
    if denied is not None:
        return denied

    ok, error, minutes = database.set_access_timeout(data.get("timeout_minutes"))
    if not ok:
        return jsonify(error=error), 400
    return jsonify(timeout_minutes=minutes)


@app.route("/admin", methods=["GET"])
def admin():
    """开发者发布端：填标题 + 富文本 + 配图，发布后立刻出现在前台信封里。"""
    return render_template("admin.html", notifications=database.list_notifications())


# ---------------- PWA：清单 / Service Worker / 图标 ----------------

@app.route("/manifest.json")
def serve_manifest():
    """manifest 放根路径访问，作用域覆盖整站；实际文件以 static/manifest.json 为准。

    v0.14.0 修复：历史上项目根目录和 static/ 各有一份 manifest.json / service-worker.js，
    真正被浏览器加载的是根目录那份，而发版改的却是 static/ 副本 —— 于是
    「manifest 加 ?v」和「SW 升 r2 清缓存」永远不生效，页面一直吃旧缓存。
    这里统一把根路径指向 static/ 下的唯一版本，避免再出现两份文件打架。
    """
    return send_from_directory(
        os.path.join(BASE_DIR, "static"), "manifest.json", mimetype="application/manifest+json"
    )


@app.route("/service-worker.js")
def serve_service_worker():
    """SW 必须能从根路径访问，才能控制 / 与所有子路径；文件同样以 static/ 为准。"""
    response = send_from_directory(
        os.path.join(BASE_DIR, "static"), "service-worker.js", mimetype="text/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.route("/favicon.ico")
def serve_favicon():
    """浏览器默认会抓 /favicon.ico；直接发我们的 PNG 图标，省掉一条 404。"""
    return send_from_directory(
        os.path.join(BASE_DIR, "static", "icons"), "favicon.png", mimetype="image/png"
    )


@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    """后台「用户管理」：只读列表，带 UID（users.id）与账目数。

    v0.13.7：后台要能一眼拿到用户的专属 UID 方便定位。
    设了访问密码时要求带有效的 X-Access-Token（access-guard.js 会自动加）。
    """
    config = database.get_access_config()
    if config["protected"] and not database.check_access_session(_request_access_token()):
        return jsonify(error="请先验证访问密码", code="access_denied"), 401
    return jsonify(users=database.list_users())


# ---------------- v0.14.0：提示文案库（Tips） ----------------
# 前端的 toast() 用 /api/tips 取「启用中的颜文字文案」，接口不可用时前端自动回退内置池；
# 后台「提示文案管理」用 /api/admin/tips 增删改查，守卫口径跟 /api/admin/users 一致。


def _require_admin_access():
    """后台接口的统一守卫：设了访问密码就必须带有效的 X-Access-Token。"""
    config = database.get_access_config()
    if config["protected"] and not database.check_access_session(_request_access_token()):
        return jsonify(error="请先验证访问密码", code="access_denied"), 401
    return None


@app.route("/api/tips", methods=["GET"])
def api_tips():
    """前端 toast() 专用：只回 is_active=1 的文案，按类型分组。

    返回结构 {"tips": {"success": [...], "error": [...], "info": [...], "warn": [...]}}，
    某类型空列表时前端回退内置保底池，所以这里不需要 404 / 兜底文案。
    """
    return jsonify(tips=database.active_tips_by_type())


@app.route("/api/admin/tips", methods=["GET"])
def admin_list_tips():
    """后台提示文案管理：全量列表（含停用的），按 type + id 排序。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    return jsonify(tips=database.list_system_tips())


@app.route("/api/admin/tips", methods=["POST"])
def admin_create_tip():
    """新增一条提示文案。字段：type（默认 success）、content（必填，≤80 字）、
    location（场景位置，可选，≤20 字）、is_active。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    try:
        tip = database.create_system_tip(
            data.get("type", "success"),
            data.get("content"),
            data.get("is_active", 1),
            data.get("location", ""),
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(tip=tip), 201


@app.route("/api/admin/tips/<int:tip_id>", methods=["PUT"])
def admin_update_tip(tip_id):
    """修改提示文案：只改 body 里出现的字段，没传的保持原样。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    try:
        tip = database.update_system_tip(
            tip_id,
            tip_type=data.get("type") if "type" in data else None,
            content=data.get("content") if "content" in data else None,
            is_active=data.get("is_active") if "is_active" in data else None,
            # location 传了才改；没传（None）表示保持原场景位置不动
            location=data.get("location") if "location" in data else None,
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    if tip is None:
        return jsonify(error="提示文案不存在"), 404
    return jsonify(tip=tip)


@app.route("/api/admin/tips/<int:tip_id>", methods=["DELETE"])
def admin_delete_tip(tip_id):
    """删除提示文案。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    if not database.delete_system_tip(tip_id):
        return jsonify(error="提示文案不存在"), 404
    return jsonify(ok=True, id=tip_id)


# ---------------- v0.14.0：帮助与反馈 ----------------
# 用户在设置弹窗「帮助与反馈」里读 FAQ / 快捷键 / 联系方式，并提交问题反馈；
# 后台在「提示文案管理」里编辑帮助内容、在「用户反馈」Tab 里看全部反馈。
# 帮助内容存在 app_settings（见 database.get_help_raw / update_help_content）。

# 反馈截图上限：前端已经压到 2MB 以内，服务端再兜一层，超了直接 413
FEEDBACK_MAX_IMAGE_BYTES = 2 * 1024 * 1024


@app.route("/api/help", methods=["GET"])
def api_help():
    """设置弹窗「帮助与反馈」：登录用户读取结构化帮助内容（无后台访问密码要求）。"""
    return jsonify(help=database.get_help_content())


@app.route("/api/admin/help", methods=["GET"])
def admin_get_help():
    """后台读取帮助内容原文（FAQ / 快捷键 / 联系方式 / 反馈占位文案）。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    return jsonify(help=database.get_help_raw())


@app.route("/api/admin/help", methods=["PUT"])
def admin_update_help():
    """后台保存帮助内容：只改 body 里出现的字段，返回保存后的原文。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    try:
        help_content = database.update_help_content(
            faq=data.get("faq") if "faq" in data else None,
            shortcuts=data.get("shortcuts") if "shortcuts" in data else None,
            contact=data.get("contact") if "contact" in data else None,
            feedback_placeholder=(
                data.get("feedback_placeholder") if "feedback_placeholder" in data else None
            ),
        )
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(help=help_content)


@app.route("/api/user-feedback", methods=["POST"])
def submit_user_feedback():
    """用户提交问题反馈（设置弹窗「帮助与反馈」）。

    注意：路径用 /api/user-feedback，不占用 v0.10 的 AI 反馈 /api/feedback。
    body JSON：issue_description（必填）、occur_date（YYYY-MM-DD 或 ""）、
    image_path（dataURL / Base64，或已经落盘的 /static/uploads/... 路径；可空）、
    contact_type（""|qq|wechat|phone）、contact_info、email、nickname。
    截图非空时按截图记账同一套函数落盘；超过 2MB 返回 413。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    # 前端契约字段叫 image_path，同时兼容老写法的 image；空串 / None 都表示没截图
    image_value = data.get("image_path")
    if not isinstance(image_value, str) or not image_value.strip():
        image_value = data.get("image")
    image_value = image_value.strip() if isinstance(image_value, str) else ""

    image_path = ""
    if image_value.startswith("/static/uploads/"):
        # 已经落过盘（比如前端重试提交）：沿用原路径，不重复写文件
        image_path = image_value
    elif image_value:
        # Base64 相对原图膨胀约 4/3，先按编码长度粗筛，别把超大图读进内存再报错
        if len(image_value) > FEEDBACK_MAX_IMAGE_BYTES * 2:
            return jsonify(error="截图太大，请压到 2MB 以内"), 413
        mime = data.get("mime") if isinstance(data.get("mime"), str) else None
        raw, mime, error_message = _decode_ai_image(image_value, mime)
        if error_message is not None:
            return jsonify(error=error_message), 400
        if len(raw) > FEEDBACK_MAX_IMAGE_BYTES:
            return jsonify(error="截图太大，请压到 2MB 以内"), 413
        image_path, error_message = _save_ai_image_to_disk(raw, mime)
        if error_message is not None:
            return jsonify(error=error_message), 400

    try:
        feedback = database.create_user_feedback(
            data.get("issue_description"),
            occur_date=data.get("occur_date") or "",
            image_path=image_path,
            contact_type=data.get("contact_type") or "",
            contact_info=data.get("contact_info") or "",
            email=data.get("email") or "",
            nickname=data.get("nickname") or "",
        )
    except database.RecordError as exc:
        # 校验失败（含 10 秒防刷）时把刚落盘的截图删掉，别留下孤儿文件
        if image_path:
            _remove_saved_image(image_path)
        return jsonify(error=str(exc)), 400
    return jsonify(feedback=feedback), 201


@app.route("/api/admin/feedback", methods=["GET"])
def admin_list_user_feedback():
    """后台「用户反馈」列表：全部用户的反馈，按提交时间倒序。"""
    denied = _require_admin_access()
    if denied is not None:
        return denied
    return jsonify(feedback=database.list_user_feedback())


# ---------------- v0.14.1 工单系统（管理员回复 / 用户查自己的单） ----------------

FEEDBACK_REPLY_STATUSES = ("pending", "replied", "closed")
MAX_FEEDBACK_REPLY_LENGTH = 2000


def _require_feedback_admin():
    """工单回复的守卫：登录 + 后台访问密码 + 管理员身份。

    比现有 /api/admin/feedback 更严一点：站点没设访问密码时，只认 1 号管理员，
    避免「任何登录用户都能冒充官方回复」；设了密码时，持有有效访问令牌即可
    （与后台其它接口的既有口径保持一致）。
    """
    user = g.get("current_user")
    if user is None:
        return jsonify(error="请先登录", code="auth_required"), 401
    denied = _require_admin_access()
    if denied is not None:
        return denied
    if int(user.get("id") or 0) == database.ADMIN_USER_ID:
        return None
    config = database.get_access_config()
    if not config["protected"]:
        return jsonify(error="只有管理员可以回复工单", code="forbidden"), 403
    return None


@app.route("/api/admin/feedback/<int:feedback_id>/reply", methods=["PUT"])
def admin_reply_feedback(feedback_id):
    """管理员回复工单：写 admin_reply，并把 status 置为 replied（可显式覆盖）。

    body: {"reply": "官方回复内容", "status": "replied"|"pending"|"closed"}
    """
    denied = _require_feedback_admin()
    if denied is not None:
        return denied

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return jsonify(error="回复内容不能为空"), 400
    reply = reply.strip()
    if len(reply) > MAX_FEEDBACK_REPLY_LENGTH:
        return jsonify(error="回复最多 %d 个字" % MAX_FEEDBACK_REPLY_LENGTH), 400
    status = data.get("status") or "replied"
    if not isinstance(status, str) or status.strip().lower() not in FEEDBACK_REPLY_STATUSES:
        return jsonify(error="status 只能是 pending / replied / closed"), 400
    status = status.strip().lower()

    # 走 SQLAlchemy ORM；未安装 SQLAlchemy 时 sqlalchemy_db 自动回落原生 SQL
    updated = sqlalchemy_db.reply_feedback(feedback_id, reply, status=status)
    if updated is None:
        return jsonify(error="工单不存在"), 404
    return jsonify(feedback=updated)


@app.route("/api/feedback/my", methods=["GET"])
@app.route("/api/user-feedback", methods=["GET"])
@login_required
def my_feedback():
    """用户查「自己的」反馈与官方回复，按提交时间倒序。

    /api/feedback/my 是 v0.14.1 指令指定的路径；/api/user-feedback 是兼容别名：
    并行开发的前端「我的工单」列表读的是后者、契约 { feedback: [...] }
    （issue_description / created_at / status / admin_reply），本接口正好一致。
    加个别名就能让前端直接读到官方回复，无需改任何前端文件。

    uid 直接取 JWT 解析出的 g.current_user，不读 contextvar，
    避免公开路径把 0 兜底成 1 号管理员导致越权看到别人的工单。
    """
    uid = int(g.current_user["id"])
    limit = request.args.get("limit", "200")
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit = 200
    return jsonify(feedback=sqlalchemy_db.list_my_feedback(uid, limit=limit))


# ---------------- 版本号：优先环境变量，其次 Git Tag ----------------

APP_VERSION_FALLBACK = "v0.14.0-TST"


def detect_version():
    """返回当前统一版本号 v0.14.0-TST。

    v0.14.0-TST 修复：原实现优先读本地 Git Tag，但仓库最新 tag 还停在
    v0.13.9-DEV，导致 /api/version 把侧边栏、「我的」页卡片、后台公告草稿
    全部串成旧版本，和静态文案对不上。验收期直接钉死内置版本号；
    部署时仍可用 APP_VERSION 环境变量显式覆盖，封版时同步改本常量即可。
    """
    pinned = (os.environ.get("APP_VERSION") or "").strip()
    return pinned or APP_VERSION_FALLBACK


@app.route("/api/version")
def api_version():
    return jsonify(version=detect_version())


# ---------------- 导出 CSV（带 BOM，Excel 打开不乱码） ----------------

TYPE_LABELS = {"expense": "支出", "income": "收入", "transfer": "转账"}


@app.route("/api/export")
def export_records():
    """把全部账目导成 CSV。开头的 \\ufeff 是给 Excel 认 UTF-8 用的 BOM。"""
    buffer = io.StringIO()
    buffer.write(chr(0xFEFF))
    headers = ["日期", "类型", "分类", "账户", "转入账户", "金额", "手续费", "公式", "备注"]
    crlf = chr(13) + chr(10)
    buffer.write(",".join(headers) + crlf)

    def cell(value):
        """普通字段：含逗号/引号/换行时才加引号，其余保持可读。"""
        text = "" if value is None else str(value)
        if any(char in text for char in (",", '"', chr(13), chr(10))):
            return '"' + text.replace('"', '""') + '"'
        return text

    for record in database.list_records():
        # 日期列写成 ="2026-10-26 22:07"：Excel 会当成公式算成文本，
        # 不再把「2026-10-26 22:07」误认成超长数字而只显示一串 ####。
        date_cell = '="%s"' % record["date"]
        rest = [
            TYPE_LABELS.get(record["type"], record["type"]),
            record["category"],
            record["account"],
            record.get("to_account", ""),
            "%.2f" % round(record["amount"], 2),
            "%.2f" % round(record.get("fee", 0), 2),
            record.get("formula", ""),
            record.get("note", ""),
        ]
        buffer.write(date_cell + "," + ",".join(cell(value) for value in rest) + crlf)

    filename = "ai-accounting-%s.csv" % datetime.datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


# ---------------- 拖拽排序：分类 / 账户 ----------------

@app.route("/api/categories/order", methods=["PUT"])
def reorder_categories():
    """body: {"ids": [3, 1, 2], "parent_id": null} —— 只重排同一父级下的兄弟分类。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    parent_id = data.get("parent_id")
    if parent_id is not None and (
        isinstance(parent_id, bool) or not isinstance(parent_id, int)
    ):
        return jsonify(error="parent_id 必须是整数或 null"), 400

    error = database.reorder_categories(data.get("ids"), parent_id)
    if error is not None:
        return jsonify(error=error), 400
    return jsonify(ok=True)


@app.route("/api/accounts/order", methods=["PUT"])
def reorder_accounts():
    """body: {"names": ["微信", "支付宝", ...]} —— 账户是全量顺序，可跨大类拖。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    error = database.reorder_accounts(data.get("names"))
    if error is not None:
        return jsonify(error=error), 400
    return jsonify(ok=True)


# ---------------- 通讯录接口（v0.07） ----------------

@app.route("/api/contacts", methods=["GET"])
def list_contacts():
    """全部联系人，带各自的借贷条数。"""
    contacts = database.list_contacts()
    return jsonify(count=len(contacts), contacts=contacts)


@app.route("/api/contacts", methods=["POST"])
def create_contact():
    """body: {"name": "张三", "identity": "室友", "phone": "138...", "wechat": "zs"}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    contact, error = database.create_contact(
        data.get("name"),
        data.get("identity", ""),
        data.get("phone", ""),
        data.get("wechat", ""),
    )
    if error is not None:
        status = 409 if "已存在" in error else 400
        return jsonify(error=error), status
    return jsonify(contact), 201


@app.route("/api/contacts/<int:contact_id>", methods=["PUT"])
def update_contact(contact_id):
    """只改传进来的字段；一个都没传算 400。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    for key in ("name", "identity", "phone", "wechat"):
        if key in data and not isinstance(data[key], str):
            return jsonify(error="%s 必须是字符串" % key), 400

    contact, error = database.update_contact(
        contact_id,
        name=data.get("name"),
        identity=data.get("identity"),
        phone=data.get("phone"),
        wechat=data.get("wechat"),
    )
    if error is not None:
        status = 404 if error == "联系人不存在" else (409 if "已存在" in error else 400)
        return jsonify(error=error), status
    return jsonify(contact)


@app.route("/api/contacts/<int:contact_id>", methods=["DELETE"])
def delete_contact(contact_id):
    """删联系人；有关联借贷或报销时返回 409，让用户先处理。"""
    deleted, error = database.delete_contact(contact_id)
    if error is not None:
        status = 404 if error == "联系人不存在" else 409
        return jsonify(error=error), status
    return jsonify(ok=True)


# ---------------- 借贷接口（v0.07） ----------------

@app.route("/api/debts", methods=["GET"])
def list_debts():
    """全部借贷；?contact_id=1 筛人，?status=unpaid 筛未结清。"""
    contact_id = request.args.get("contact_id", type=int)
    status = (request.args.get("status") or "").strip()
    if status and status not in database.DEBT_STATUSES:
        return jsonify(error="status 只能是 unpaid / paid"), 400

    debts = database.list_debts(contact_id=contact_id, status=status or None)
    return jsonify(count=len(debts), debts=debts)


@app.route("/api/debts", methods=["POST"])
def create_debt():
    """body: {"contact_id":1,"amount":100,"type":"lend","account":"现金","date":"...","status":"unpaid"}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    image_path = ""
    if isinstance(data.get("image"), str) and data["image"].strip():
        raw, mime, image_error = _decode_ai_image(data["image"], data.get("mime"))
        if image_error is not None:
            return jsonify(error=image_error), 400
        image_path, image_error = _save_ai_image_to_disk(raw, mime)
        if image_error is not None:
            return jsonify(error=image_error), 400

    debt, error = database.create_debt(
        data.get("contact_id"),
        data.get("amount"),
        debt_type=data.get("type", "lend"),
        account=data.get("account", database.DEFAULT_ACCOUNT),
        date=data.get("date"),
        status=data.get("status", "unpaid"),
        due_date=data.get("due_date") or "",
        interest=data.get("interest") or 0,
        image_path=image_path,
    )
    if error is not None:
        status = 404 if error == "联系人不存在" else 400
        return jsonify(error=error), status
    return jsonify(debt), 201


@app.route("/api/debts/<int:debt_id>", methods=["PUT"])
def update_debt(debt_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    debt, error = database.update_debt(
        debt_id,
        contact_id=data.get("contact_id"),
        amount=data.get("amount"),
        debt_type=data.get("type"),
        account=data.get("account"),
        date=data.get("date"),
        status=data.get("status"),
        due_date=data.get("due_date"),
        interest=data.get("interest"),
        image_path=data.get("image_path"),
    )
    if error is not None:
        status = 404 if error == "借贷记录不存在" else 400
        return jsonify(error=error), status
    return jsonify(debt)


@app.route("/api/debts/<int:debt_id>", methods=["DELETE"])
def delete_debt(debt_id):
    deleted, error = database.delete_debt(debt_id)
    if error is not None:
        return jsonify(error=error), 404
    return jsonify(ok=True)


@app.route("/api/debts/<int:debt_id>/settle", methods=["POST"])
def settle_debt(debt_id):
    """结清借贷：状态置 paid；有利息时自动补一笔利息收入/支出账单。"""
    data = request.get_json(silent=True) or {}
    debt, record, error = database.settle_debt(debt_id, data.get("date"))
    if error is not None:
        status = 404 if error == "借贷记录不存在" else 400
        return jsonify(error=error), status
    return jsonify(debt=debt, record=record, message="已结清" + ("，利息账单已入账" if record else ""))


@app.route("/api/debts/<int:debt_id>/repay", methods=["POST"])
def repay_debt(debt_id):
    """v0.13.8 还款闭环：扣/加资金账户余额 + 生成流水 + 累加已还 + 到期自动结清。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    amount = data.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return jsonify(error="amount 必须是数字"), 400
    account = data.get("account")
    if account is not None and not isinstance(account, str):
        return jsonify(error="account 必须是字符串"), 400
    debt, record, error = database.repay_debt(
        debt_id, amount, account, data.get("date")
    )
    if error is not None:
        status = 404 if error == "借贷记录不存在" else 400
        return jsonify(error=error), status
    message = "已结清" if debt["status"] == "paid" else "已还 %.2f，剩余 %.2f" % (
        float(amount),
        debt["remaining"],
    )
    return jsonify(debt=debt, record=record, message=message)


@app.route("/api/records/<int:record_id>/reimburse", methods=["POST"])
def reimburse_record(record_id):
    """v0.13.8 报销闭环：生成报销入账流水并累加已报销金额。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    amount = data.get("amount")
    if amount is not None and (
        isinstance(amount, bool) or not isinstance(amount, (int, float))
    ):
        return jsonify(error="amount 必须是数字"), 400
    account = data.get("account")
    if account is not None and not isinstance(account, str):
        return jsonify(error="account 必须是字符串"), 400
    record, flow, error = database.reimburse_record(
        record_id, amount, account, data.get("date")
    )
    if error is not None:
        status = 404 if error == "账目不存在" else 400
        return jsonify(error=error), status
    return jsonify(record=record, flow=flow, message="已标记报销并入账")


# ---------------- 图标素材库（v0.12.3） ----------------


@app.route("/api/icons", methods=["GET"])
def list_icons():
    """图标列表：系统内置 + 自己上传；?all=1 仅管理员可看全站上传。"""
    include_others = request.args.get("all") in ("1", "true", "yes")
    if include_others and (g.current_user.get("id") != database.ADMIN_USER_ID):
        return jsonify(error="只有管理员可以查看全部图标"), 403
    items = database.list_icons(include_others=include_others)
    return jsonify(items=items, total=len(items))


@app.route("/api/icons", methods=["POST"])
def create_icon():
    """上传图标：body {name, image: dataURL}；管理员可传系统内置图标（is_system=1）。"""
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if not isinstance(image, str) or not image.strip():
        return jsonify(error="没有收到图标文件"), 400
    if len(image) > 2 * 1024 * 1024:
        return jsonify(error="图标太大，请压到 1MB 以内"), 413
    raw, mime, error = _decode_ai_image(image, data.get("mime"))
    if error is not None:
        return jsonify(error=error), 400
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"):
        return jsonify(error="图标只支持 png / jpg / webp / gif / svg"), 400
    path, error = _save_ai_image_to_disk(raw, mime)
    if error is not None:
        return jsonify(error=error), 400
    is_system = bool(data.get("is_system")) and g.current_user.get("id") == database.ADMIN_USER_ID
    try:
        icon = database.add_icon(data.get("name") or "", path, is_system=is_system)
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(icon), 201


@app.route("/api/icons/<int:icon_id>", methods=["DELETE"])
def delete_icon(icon_id):
    """删自己上传的图标（系统图标删不掉）。"""
    deleted, error = database.delete_icon(icon_id)
    if error is not None:
        return jsonify(error=error), 400
    return jsonify(ok=True)


@app.route("/api/user-icons", methods=["GET"])
def list_user_icons():
    """当前用户的图标覆盖：{category: {名称: {...}}, account: {...}}。"""
    return jsonify(icons=database.list_user_icons())


@app.route("/api/user-icons", methods=["PUT"])
def set_user_icon():
    """把分类/账户换成指定图标：{kind, name, icon_id}。"""
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    name = (data.get("name") or "").strip()
    try:
        icon_id = int(data.get("icon_id"))
    except (TypeError, ValueError):
        return jsonify(error="icon_id 必须是整数"), 400
    if not name:
        return jsonify(error="name 不能为空"), 400
    try:
        ok = database.set_user_icon(kind, name, icon_id)
    except database.RecordError as exc:
        return jsonify(error=str(exc)), 400
    if not ok:
        return jsonify(error="图标不存在"), 404
    return jsonify(ok=True)


@app.route("/api/user-icons", methods=["DELETE"])
def clear_user_icon():
    """恢复系统默认图标：?kind=category&name=餐饮。"""
    kind = (request.args.get("kind") or "").strip()
    name = (request.args.get("name") or "").strip()
    if kind not in ("category", "account") or not name:
        return jsonify(error="kind 与 name 都必填"), 400
    database.clear_user_icon(kind, name)
    return jsonify(ok=True)


# ---------------- 404：接口给 JSON，页面给有人情味的 404.html ----------------

@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="接口不存在：%s" % request.path), 404
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=False)
