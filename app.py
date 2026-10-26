from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    init_database, create_user, get_user_by_username,
    get_user_by_email, get_user_by_id, save_game_result,
    get_user_results, get_user_stats
)

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

init_database()

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Number Game API is running!", "version": "1.0.0"})

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not username or not email or not password:
        return jsonify({"error": "همه فیلدها الزامی است!"}), 400
    if len(username) < 3:
        return jsonify({"error": "نام کاربری باید حداقل ۳ کاراکتر باشد!"}), 400
    if len(password) < 8:
        return jsonify({"error": "رمز باید حداقل ۸ کاراکتر باشد!"}), 400
    if get_user_by_username(username):
        return jsonify({"error": "این نام کاربری قبلاً گرفته شده!"}), 400
    if get_user_by_email(email):
        return jsonify({"error": "این ایمیل قبلاً ثبت شده!"}), 400
    password_hash = generate_password_hash(password)
    user_id = create_user(username, email, password_hash)
    if not user_id:
        return jsonify({"error": "خطا در ساخت حساب!"}), 500
    return jsonify({
        "message": "ثبت‌نام موفق!",
        "user": {"id": user_id, "username": username, "email": email}
    }), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "همه فیلدها الزامی است!"}), 400
    user = get_user_by_username(username)
    if not user:
        return jsonify({"error": "کاربری با این نام پیدا نشد!"}), 401
    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "رمز عبور اشتباه است!"}), 401
    return jsonify({
        "message": "ورود موفق!",
        "user": {"id": user["id"], "username": user["username"], "email": user["email"]}
    }), 200

@app.route("/api/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "کاربر پیدا نشد!"}), 404
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "created_at": user["created_at"]
    }), 200

@app.route("/api/save-result", methods=["POST"])
def save_result():
    data = request.get_json()
    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    user_id = data.get("user_id")
    score = data.get("score")
    rank = data.get("rank")
    players = data.get("players")
    rounds = data.get("rounds")
    if not all([user_id, score is not None, rank, players, rounds]):
        return jsonify({"error": "همه فیلدها الزامی است!"}), 400
    save_game_result(user_id, score, rank, players, rounds)
    return jsonify({"message": "نتیجه ذخیره شد!"}), 201

@app.route("/api/results/<int:user_id>", methods=["GET"])
def get_results(user_id):
    results = get_user_results(user_id)
    return jsonify({"results": results}), 200

@app.route("/api/stats/<int:user_id>", methods=["GET"])
def get_stats(user_id):
    stats = get_user_stats(user_id)
    return jsonify({"stats": stats}), 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)