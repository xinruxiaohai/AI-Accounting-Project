import datetime

from flask import Flask, jsonify, render_template, request

import database

app = Flask(__name__)

# 让 jsonify 直接输出中文，而不是 \uXXXX 转义，方便浏览器里肉眼检查
app.json.ensure_ascii = False

# 启动就建表 / 升级表结构。表已存在时 CREATE TABLE 会跳过，缺列时自动补列
database.init_db()


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
            return None, None, (jsonify(error="category_id 对应的分类不存在"), 400)
        return category["name"], category["id"], None

    category = data.get("category")
    if not isinstance(category, str) or not category.strip():
        return None, None, (
            jsonify(error="category 必须是非空字符串，或者改传 category_id"),
            400,
        )
    category = database.ensure_category(category.strip())
    return category["name"], category["id"], None


def _parse_record(data):
    """把请求体校验成一份干净的记录字段。POST 和 PUT 共用这一份规则。"""
    # 客户端必须带 Content-Type: application/json，否则这里拿到的是 None
    if not isinstance(data, dict):
        return None, (jsonify(error="请求体必须是 JSON 对象"), 400)

    amount = data.get("amount")
    # bool 是 int 的子类，先单独排掉 True/False，否则 isinstance 检查会放过它
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return None, (jsonify(error="amount 必须是大于 0 的数字"), 400)

    category, category_id, error = _resolve_category(data)
    if error is not None:
        return None, error

    # 类型只认 expense / income，其他一律拒绝，不猜
    record_type = data.get("type", database.DEFAULT_TYPE)
    if record_type not in database.RECORD_TYPES:
        return None, (jsonify(error="type 只能是 expense 或 income"), 400)

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

    new_id = database.add_record(
        payload["amount"],
        payload["category"],
        payload["note"],
        payload["date"],
        payload["account"],
        payload["type"],
        payload["category_id"],
    )

    # 201 表示"已创建"
    return jsonify(id=new_id, **payload), 201


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
        payload["category_id"],
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


# ---------------- 分类接口 ----------------

@app.route("/api/categories", methods=["GET"])
def list_categories():
    """两级分类树。一级分类带 children，前端拿它做级联下拉框。"""
    tree = database.list_categories_tree()
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

    category, error = database.create_category(name.strip(), parent_id)
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

    account, error = database.create_account(name.strip(), group_name, balance)
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

    if "balance" not in data and "group_name" not in data:
        return jsonify(error="至少要传 balance 或 group_name 之一"), 400

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

    account, error = database.update_account(name, balance, group_name)
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


@app.route("/api/statistics", methods=["GET"])
def statistics():
    """总览：总收入、总支出、总余额，给首页三张卡片用。"""
    return jsonify(database.get_statistics())


if __name__ == "__main__":
    app.run(debug=True)
