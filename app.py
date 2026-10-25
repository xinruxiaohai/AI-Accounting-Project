from datetime import date

from flask import Flask, jsonify, render_template, request

import database

app = Flask(__name__)

# 让 jsonify 直接输出中文，而不是 \uXXXX 转义，方便浏览器里肉眼检查
app.json.ensure_ascii = False

# 启动就建表。表已存在时 CREATE TABLE IF NOT EXISTS 会自动跳过，重启多少次都没事
database.init_db()


@app.route("/", methods=["GET"])
def index():
    """首页路由：返回记一笔页面。模板默认从同级的 templates 目录里找。"""
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """健康检查路由：给部署平台或监控探针轮询，正常时固定返回 good。"""
    return jsonify(health="good")


@app.route("/api/records", methods=["POST"])
def create_record():
    """接收前端提交的一笔账，写进 SQLite，把入库后的完整记录返回给前端。"""
    # 客户端必须带 Content-Type: application/json，否则这里拿到的是 None
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400

    amount = data.get("amount")
    # bool 是 int 的子类，先单独排掉 True/False，否则 isinstance 检查会放过它
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify(error="amount 必须是大于 0 的数字"), 400

    category = data.get("category")
    if not isinstance(category, str) or not category.strip():
        return jsonify(error="category 必须是非空字符串"), 400

    # 先清洗成干净的值，再统一入库和返回，避免两边不一致
    category = category.strip()
    note = (data.get("note") or "").strip()
    record_date = data.get("date") or date.today().isoformat()

    new_id = database.add_record(amount, category, note, record_date)

    # 201 表示"已创建"
    return jsonify(
        id=new_id,
        amount=amount,
        category=category,
        note=note,
        date=record_date,
    ), 201


@app.route("/api/records", methods=["GET"])
def list_records():
    """从 SQLite 读全部账目，前端列表页拿它来渲染。"""
    rows = database.list_records()
    return jsonify(count=len(rows), records=rows)


if __name__ == "__main__":
    app.run(debug=True)
