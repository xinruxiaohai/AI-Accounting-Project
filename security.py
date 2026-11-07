"""v0.14.1 密码哈希统一入口（Werkzeug 加盐哈希 + 老哈希静默升级）。

对外接口
--------
    generate_password_hash(password)  新的加盐哈希（Werkzeug，scrypt）
    check_password_hash(stored, pwd)  原生 Werkzeug 校验（现代格式）
    verify_password(stored, pwd)      兼容校验：现代格式 + 旧简单 Hash
    needs_upgrade(stored)             是不是老格式
    upgrade_if_needed(...)            登录成功后静默改写数据库，绝不抛错

为什么要保留「旧哈希」分支
--------------------------
本项目当前 users 表 4 个账号已经全是 Werkzeug scrypt（形如
`scrypt:32768:8:1$...`），本分支在本地是**不触发**的兼容兜底；
但早期版本 / 外部导入的库可能存过「简单 SHA256」，直接喂给
werkzeug.check_password_hash() 会因格式不认识而抛 ValueError / 返回 False，
老用户就再也登不进来。所以这里先把老格式验通，登录成功的同一请求里
静默换成加盐哈希，之后就再也不走老分支。

安全边界
--------
* 只认「看起来像哈希」的旧格式（定长 hex / 盐$hex），绝不把明文当密码接受；
* 一律 hmac.compare_digest 常量时间比较；
* 升级失败只记日志、不影响本次登录（登录必须永远可用）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sys

from werkzeug.security import (
    check_password_hash as _werkzeug_check,
    generate_password_hash as _werkzeug_generate,
)

# 直接重新导出，调用方（注册 / 改密 / 找回密码）不用知道内部实现
generate_password_hash = _werkzeug_generate
check_password_hash = _werkzeug_check

_MODERN_METHODS = frozenset({"scrypt", "pbkdf2", "argon2"})
_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]+$")
# 旧格式：盐$哈希（database._hash_password 的 v0.11 站点访问密码同款算法）
_SALTED_LEGACY = re.compile(r"^([0-9a-fA-F]{1,64})\$([0-9a-fA-F]{32,64})$")


def is_modern_hash(stored):
    """现代加盐哈希（Werkzeug）？"""
    if not isinstance(stored, str) or not stored:
        return False
    method = stored.split("$", 1)[0].split(":", 1)[0].strip().lower()
    return method in _MODERN_METHODS


def looks_like_legacy_hash(stored):
    """只有「像哈希」的字符串才允许走旧校验，明文一律拒绝。"""
    if not isinstance(stored, str) or not stored:
        return False
    if is_modern_hash(stored):
        return False
    if _SALTED_LEGACY.match(stored):
        return True
    return bool(_HEX_DIGEST.match(stored)) and len(stored) in (32, 40, 64)


def _legacy_matches(stored, password):
    raw = str(password).encode("utf-8")
    salted = _SALTED_LEGACY.match(stored)
    if salted:
        salt, digest = salted.group(1), salted.group(2)
        candidate = hashlib.sha256(
            (salt + ":" + str(password)).encode("utf-8")
        ).hexdigest()
        return hmac.compare_digest(candidate.lower(), digest.lower())

    candidates = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sha1": hashlib.sha1(raw).hexdigest(),   # noqa: S324 - 仅用于兼容旧库校验
        "md5": hashlib.md5(raw).hexdigest(),     # noqa: S324 - 仅用于兼容旧库校验
    }
    target = stored.lower()
    return any(
        hmac.compare_digest(value, target)
        for value in candidates.values()
        if len(value) == len(target)
    )


def verify_password(stored, password):
    """兼容校验入口：现代加盐哈希 + 旧简单 Hash。任何异常都吞掉返回 False。"""
    if not isinstance(stored, str) or not stored or not isinstance(password, str):
        return False
    if is_modern_hash(stored):
        try:
            return bool(check_password_hash(stored, password))
        except (ValueError, TypeError, KeyError, IndexError):
            # Werkzeug 遇到不认识的 method 会抛 ValueError，登录接口不能崩
            return False
    if not looks_like_legacy_hash(stored):
        return False
    try:
        return _legacy_matches(stored, password)
    except Exception:  # noqa: BLE001 - 兼容分支绝不影响登录可用性
        return False


def needs_upgrade(stored):
    """老格式且已验证通过时才需要升级；空值 / 明文返回 False。"""
    return bool(stored) and looks_like_legacy_hash(stored)


def hash_password(password):
    """生成新的加盐哈希。"""
    return generate_password_hash(password)


def upgrade_if_needed(user_id, stored, password, updater):
    """登录成功后静默升级：把旧简单 Hash 换成 Werkzeug 加盐哈希。

    updater 形如 database.update_user_password(user_id, new_hash) -> bool。
    静默 = 不返回错误给用户、不记密码/哈希、失败只留一行 stderr 日志。
    """
    if not needs_upgrade(stored):
        return False
    try:
        updated = bool(updater(user_id, hash_password(password)))
        if updated:
            print(
                "[security] 用户 %s 的旧密码哈希已静默升级为加盐哈希" % user_id,
                file=sys.stderr,
                flush=True,
            )
        return updated
    except Exception as exc:  # noqa: BLE001 - 升级失败不能阻断登录
        print(
            "[security] 用户 %s 密码哈希升级失败（登录不受影响）：%s"
            % (user_id, exc),
            file=sys.stderr,
            flush=True,
        )
        return False


__all__ = [
    "generate_password_hash",
    "check_password_hash",
    "verify_password",
    "needs_upgrade",
    "hash_password",
    "upgrade_if_needed",
    "is_modern_hash",
    "looks_like_legacy_hash",
]
