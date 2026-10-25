from datetime import date

from flask import Flask, jsonify, request

app = Flask(__name__)

# 让 jsonify 直接输出中文，而不是 \uXXXX 转义，方便浏览器里肉眼检查
app.json.ensure_ascii = False

# 内存里的账目列表：进程一重启就清空。第 2 步刻意这么干，先只验证数据流，不掺数据库
records = []


@app.route("/", methods=["GET"])
def index():
    """首页路由：返回服务状态和项目名，用于确认后端已正常启动。"""
    return jsonify(status="ok", project="AI记账管家")


@app.route("/health", methods=["GET"])
def health():
    """健康检查路由：给部署平台或监控探针轮询，正常时固定返回 good。"""
    return jsonify(health="good")


@app.route("/api/records", methods=["POST"])
def create_record():
    """接收前端提交的一笔账，存进内存，把带 id 的完整记录返回给前端。"""
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

    # 组装成完整记录：id 由后端发，date 没传就默认今天
    record = {
        "id": len(records) + 1,
        "amount": amount,
        "category": category.strip(),
        "note": (data.get("note") or "").strip(),
        "date": data.get("date") or date.today().isoformat(),
    }
    records.append(record)

    # 201 表示"已创建"，比 200 更准确
    return jsonify(record), 201


@app.route("/api/records", methods=["GET"])
def list_records():
    """把内存里的账目全部返回，前端列表页拿它来渲染。"""
    return jsonify(count=len(records), records=records)


if __name__ == "__main__":
    app.run(debug=True)
