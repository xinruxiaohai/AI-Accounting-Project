import datetime

from flask import Flask, jsonify, render_template, request

import database

app = Flask(__name__)

# 让 jsonify 直接输出中文，而不是 \uXXXX 转义，方便浏览器里肉眼检查
app.json.ensure_ascii = False

# 启动就建表 / 升级表结构。表已存在时 CREATE TABLE 会跳过，缺列时自动补列
database.init_db()


def _parse_datetime(value):
    """把请求里的日期时间统一成「YYYY-MM-DD HH:MM」，返回 (字符串, 错误信息)。

    - 不传 / 空串：取当前时间，精确到分钟
    - 只给日期 2026-10-26：补成 2026-10-26 00:00（兼容老前端和手写 curl）
    - <input type="datetime-local"> 给的是 2026-10-26T14:30，也接受
    - 带秒的 2026-10-26 14:30:59 会截断到分钟
    """
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


def _parse_record(data):
    """把请求体校验成一份干净的记录字段。

    返回 (payload, error)：payload 是字典，error 是要直接 return 的响应（对，或 None）。
    POST 和 PUT 都走这一个函数 —— 校验规则只有一份，不会出现「新增严格、修改宽松」的漏洞。
    """
    # 客户端必须带 Content-Type: application/json，否则这里拿到的是 None
    if not isinstance(data, dict):
        return None, (jsonify(error="请求体必须是 JSON 对象"), 400)

    amount = data.get("amount")
    # bool 是 int 的子类，先单独排掉 True/False，否则 isinstance 检查会放过它
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return None, (jsonify(error="amount 必须是大于 0 的数字"), 400)

    category = data.get("category")
    if not isinstance(category, str) or not category.strip():
        return None, (jsonify(error="category 必须是非空字符串"), 400)

    # 类型只认 expense / income，其他一律拒绝，不猜
    record_type = data.get("type", database.DEFAULT_TYPE)
    if record_type not in database.RECORD_TYPES:
        return None, (jsonify(error="type 只能是 expense 或 income"), 400)

    # 时间精确到分钟：老前端只给日期也能收，统一成 2026-10-26 14:30 这种形态
    date, date_error = _parse_datetime(data.get("date"))
    if date_error is not None:
        return None, (jsonify(error=date_error), 400)

    # 先清洗成干净的值，再统一入库和返回，避免两边不一致
    payload = {
        "amount": amount,
        "category": category.strip(),
        "note": (data.get("note") or "").strip(),
        "date": date,
        # 账户允许自定义，前端不传时给默认值"现金"
        "account": (data.get("account") or database.DEFAULT_ACCOUNT).strip(),
        "type": record_type,
    }
    return payload, None


@app.route("/", methods=["GET"])
def index():
    """首页路由：返回记账页面，顺便把分类和账户选项注入模板，下拉框不用再发一次请求。"""
    return render_template(
        "index.html",
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

    new_id = database.add_record(
        payload["amount"],
        payload["category"],
        payload["note"],
        payload["date"],
        payload["account"],
        payload["type"],
    )

    # 201 表示"已创建"
    return jsonify(id=new_id, **payload), 201


@app.route("/api/records", methods=["GET"])
def list_records():
    """读出账目，支持 ?account=微信 只筛选某个账户的流水。

    倒序规则由 database.list_records() 的 SQL 决定，这里不重新排序。
    """
    # 没传或者是空串就当"不筛选"，避免 ?account= 这种写法变成「找账户名为空的记录」
    account = (request.args.get("account") or "").strip() or None
    rows = database.list_records(account)
    return jsonify(count=len(rows), account=account, records=rows)


@app.route("/api/records/<int:record_id>", methods=["PUT"])
def update_record(record_id):
    """整条覆盖式更新一条账目，并修正余额。前端编辑时会把表单里的全部字段一起发上来。"""
    payload, error = _parse_record(request.get_json(silent=True))
    if error is not None:
        return error

    updated = database.update_record(
        record_id,
        payload["amount"],
        payload["category"],
        payload["note"],
        payload["date"],
        payload["account"],
        payload["type"],
    )
    if not updated:
        return jsonify(error="记录不存在"), 404

    return jsonify(id=record_id, **payload)


@app.route("/api/records/<int:record_id>", methods=["DELETE"])
def remove_record(record_id):
    """删除一条账目并回滚余额。id 不存在时返回 404，而不是假装成功。"""
    deleted = database.delete_record(record_id)
    if not deleted:
        return jsonify(error="记录不存在"), 404
    return jsonify(deleted=record_id)


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    """所有账户及当前余额。"""
    rows = database.list_accounts()
    return jsonify(count=len(rows), accounts=rows)


@app.route("/api/accounts/<name>", methods=["PUT"])
def update_account(name):
    """手动把某个账户的余额改成指定值（用于「我其实知道还剩多少钱」的场景）。

    允许负数：信用卡、花呗这类账户余额本来就可能是负的。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    balance = data.get("balance")
    if isinstance(balance, bool) or not isinstance(balance, (int, float)):
        return jsonify(error="balance 必须是数字"), 400

    # 金额只保留到分，避免 12.345000000001 这种浮点尾巴进库
    balance = round(balance, 2)

    updated = database.update_account_balance(name, balance)
    if not updated:
        return jsonify(error="账户不存在"), 404

    return jsonify(name=name, balance=balance)


@app.route("/api/statistics", methods=["GET"])
def statistics():
    """总览：总收入、总支出、总余额，给首页三张卡片用。"""
    return jsonify(database.get_statistics())


if __name__ == "__main__":
    app.run(debug=True)
