from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    init_database, create_user, get_user_by_username,
    get_user_by_email, get_user_by_id, save_game_result,
    get_user_results, get_user_stats
)
import random
import os
import time

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

init_database()

# --- API ها ---
@app.route("/", methods=["GET"])
def home(): return jsonify({"message": "Number Game API is running!"})

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data: return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not username or not email or not password: return jsonify({"error": "همه فیلدها الزامی است!"}), 400
    if len(username) < 3: return jsonify({"error": "نام کاربری باید حداقل ۳ کاراکتر باشد!"}), 400
    if len(password) < 6: return jsonify({"error": "رمز عبور باید حداقل ۶ کاراکتر باشد!"}), 400
    if get_user_by_username(username): return jsonify({"error": "این نام کاربری قبلاً گرفته شده!"}), 400
    if get_user_by_email(email): return jsonify({"error": "این ایمیل قبلاً ثبت شده!"}), 400
    user_id = create_user(username, email, generate_password_hash(password))
    if not user_id: return jsonify({"error": "خطا در ساخت حساب!"}), 500
    return jsonify({"message": "ثبت‌نام موفق!", "user": {"id": user_id, "username": username, "email": email}}), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data: return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password: return jsonify({"error": "همه فیلدها الزامی است!"}), 400
    user = get_user_by_username(username)
    if not user: return jsonify({"error": "کاربری با این نام پیدا نشد!"}), 401
    if not check_password_hash(user["password_hash"], password): return jsonify({"error": "رمز عبور اشتباه است!"}), 401
    return jsonify({"message": "ورود موفق!", "user": {"id": user["id"], "username": user["username"], "email": user["email"]}}), 200

@app.route("/api/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = get_user_by_id(user_id)
    if not user: return jsonify({"error": "کاربر پیدا نشد!"}), 404
    return jsonify({"id": user["id"], "username": user["username"], "email": user["email"]}), 200

@app.route("/api/save-result", methods=["POST"])
def save_result():
    data = request.get_json()
    if not data: return jsonify({"error": "داده‌ای ارسال نشد!"}), 400
    save_game_result(data.get("user_id"), data.get("score"), data.get("rank"), data.get("players"), data.get("rounds"))
    return jsonify({"message": "نتیجه ذخیره شد!"}), 201

@app.route("/api/results/<int:user_id>", methods=["GET"])
def get_results(user_id): return jsonify({"results": get_user_results(user_id)}), 200

@app.route("/api/stats/<int:user_id>", methods=["GET"])
def get_stats(user_id): return jsonify({"stats": get_user_stats(user_id)}), 200


# ==========================================
# 🚀 API های جدید برای اتاق و بازی (بدون Socket.IO)
# ==========================================
rooms_data = {}
games_data = {}

# بانک سوالات
easy_questions = [(f"{a} + {b}", a + b) for a in range(1, 11) for b in range(1, 11) if a + b <= 20]
medium_questions = [(f"{a} - {b}", a - b) for a in range(1, 21) for b in range(1, 21) if 1 <= a - b <= 20]
hard_questions = [(f"{a} × {b}", a * b) for a in range(1, 21) for b in range(1, 21) if a * b <= 20]

def get_new_question():
    level = random.choice(["easy", "medium", "hard"])
    if level == "easy": q, ans = random.choice(easy_questions); t = 7
    elif level == "medium": q, ans = random.choice(medium_questions); t = 10
    else: q, ans = random.choice(hard_questions); t = 15
    return {"question": q, "answer": ans, "time_limit": t}

@app.route("/api/room/create", methods=["POST"])
def api_create_room():
    data = request.get_json()
    room_code = data.get("room_code")
    username = data.get("username")
    max_players = data.get("max_players", 2)
    bot_count = data.get("bot_count", 0)
    bot_difficulty = data.get("bot_difficulty", "medium")
    
    if not room_code or not username: return jsonify({"error": "اطلاعات ناقص است"}), 400
    
    if max_players > 20: max_players = 20
    if bot_count > 5: bot_count = 5
    
    players = [username]
    for i in range(bot_count):
        players.append(f"بات {i+1}")
    
    rooms_data[room_code] = {
        'players': players,
        'host': username,
        'max_players': max_players,
        'bot_count': bot_count,
        'bot_difficulty': bot_difficulty
    }
    
    return jsonify({"message": "اتاق ساخته شد", "room": rooms_data[room_code]}), 201

@app.route("/api/room/join", methods=["POST"])
def api_join_room():
    data = request.get_json()
    room_code = data.get("room_code")
    username = data.get("username")
    
    if not room_code or not username: return jsonify({"error": "اطلاعات ناقص است"}), 400
    if room_code not in rooms_data: return jsonify({"error": "اتاق پیدا نشد!"}), 404
    
    room = rooms_data[room_code]
    if len(room['players']) >= room['max_players']: return jsonify({"error": "اتاق پر است!"}), 400
    if username not in room['players']: room['players'].append(username)
    
    return jsonify({"message": "وارد اتاق شدی", "room": room}), 200

@app.route("/api/room/status/<room_code>", methods=["GET"])
def api_room_status(room_code):
    if room_code not in rooms_data: return jsonify({"error": "اتاق پیدا نشد!"}), 404
    return jsonify(rooms_data[room_code]), 200

@app.route("/api/room/kick", methods=["POST"])
def api_kick_player():
    data = request.get_json()
    room_code = data.get("room_code")
    username_to_kick = data.get("username_to_kick")
    host = data.get("host")
    
    if room_code in rooms_data and rooms_data[room_code]['host'] == host:
        room = rooms_data[room_code]
        if username_to_kick in room['players']:
            room['players'].remove(username_to_kick)
            return jsonify({"message": "بازیکن اخراج شد", "room": room}), 200
    return jsonify({"error": "اجازه نداری"}), 403

@app.route("/api/game/start", methods=["POST"])
def api_start_game():
    data = request.get_json()
    room_code = data.get("room_code")
    if room_code not in rooms_data: return jsonify({"error": "اتاق پیدا نشد!"}), 404
    
    room = rooms_data[room_code]
    players = room['players']
    num_rounds = 5
    rounds_with_math = [random.random() < 0.3 for _ in range(num_rounds)]

    game_players = []
    for p in players:
        is_bot = p.startswith("بات")
        game_players.append({'name': p, 'score': 0, 'numbers': [0]*num_rounds, 'is_bot': is_bot})
    
    games_data[room_code] = {
        'players': game_players,
        'num_rounds': num_rounds,
        'current_round': 0,
        'current_player_idx': 0,
        'rounds_with_math': rounds_with_math,
        'current_question': None,
        'round_start_time': None,
        'question_answered': False,
        'bot_difficulty': room.get('bot_difficulty', 'medium'),
        'status': 'playing'
    }
    
    if rounds_with_math[0]:
        games_data[room_code]['current_question'] = get_new_question()
        games_data[room_code]['round_start_time'] = time.time()
    
    return jsonify({"message": "بازی شروع شد", "game": games_data[room_code]}), 200

@app.route("/api/game/state/<room_code>", methods=["GET"])
def api_game_state(room_code):
    if room_code not in games_data: return jsonify({"error": "بازی پیدا نشد!"}), 404
    game = games_data[room_code]
    
    # اجرای نوبت بات‌ها به صورت خودکار
    if game['status'] == 'playing' and game['current_player_idx'] < len(game['players']):
        current_player = game['players'][game['current_player_idx']]
        if current_player['is_bot']:
            # بات یه عدد انتخاب می‌کنه
            chosen = random.randint(1, 20)
            if game['rounds_with_math'][game['current_round']] and game['current_question']:
                difficulty = game['bot_difficulty']
                if random.random() < (0.85 if difficulty == "hard" else 0.55 if difficulty == "medium" else 0.3):
                    chosen = game['current_question']['answer']
            
            game['players'][game['current_player_idx']]['numbers'][game['current_round']] = chosen
            
            if game['rounds_with_math'][game['current_round']] and game['current_question']:
                if not game['question_answered']:
                    elapsed = time.time() - game['round_start_time']
                    if elapsed <= game['current_question']['time_limit'] and chosen == game['current_question']['answer']:
                        game['players'][game['current_player_idx']]['score'] += 2
                    game['question_answered'] = True
            
            game['current_player_idx'] += 1
            
            if game['current_player_idx'] >= len(game['players']):
                end_round_logic(game)
                if game['current_round'] < game['num_rounds']:
                    if game['rounds_with_math'][game['current_round']]:
                        game['current_question'] = get_new_question()
                        game['round_start_time'] = time.time()
                        game['question_answered'] = False
                    else:
                        game['current_question'] = None
                else:
                    game['status'] = 'finished'
    
    return jsonify({"game": game}), 200

@app.route("/api/game/submit", methods=["POST"])
def api_game_submit():
    data = request.get_json()
    room_code = data.get("room_code")
    username = data.get("username")
    number = data.get("number")
    
    if room_code not in games_data: return jsonify({"error": "بازی پیدا نشد!"}), 404
    game = games_data[room_code]
    
    current_player = game['players'][game['current_player_idx']]['name']
    if username != current_player: return jsonify({"error": "نوبت تو نیست!"}), 400
    
    player_idx = game['current_player_idx']
    game['players'][player_idx]['numbers'][game['current_round']] = number
    
    if game['rounds_with_math'][game['current_round']] and game['current_question']:
        if not game['question_answered']:
            elapsed = time.time() - game['round_start_time']
            if elapsed <= game['current_question']['time_limit'] and number == game['current_question']['answer']:
                game['players'][player_idx]['score'] += 2
            game['question_answered'] = True
    
    game['current_player_idx'] += 1
    
    if game['current_player_idx'] >= len(game['players']):
        end_round_logic(game)
        if game['current_round'] < game['num_rounds']:
            if game['rounds_with_math'][game['current_round']]:
                game['current_question'] = get_new_question()
                game['round_start_time'] = time.time()
                game['question_answered'] = False
            else:
                game['current_question'] = None
        else:
            game['status'] = 'finished'
    
    return jsonify({"game": game}), 200

def end_round_logic(game):
    r = game['current_round']
    one_count = sum(1 for p in game['players'] if p['numbers'][r] < 10)
    two_count = len(game['players']) - one_count
    
    if one_count < two_count:
        for p in game['players']:
            if p['numbers'][r] < 10: p['score'] += 3
    elif two_count < one_count:
        for p in game['players']:
            if p['numbers'][r] >= 10: p['score'] += 3
            
    for i, p in enumerate(game['players']):
        num = p['numbers'][r]
        is_unique = all(k == i or game['players'][k]['numbers'][r] != num for k in range(len(game['players'])))
        if is_unique: p['score'] += 1

    game['players'].sort(key=lambda x: x['score'], reverse=True)
    game['current_round'] += 1
    game['current_player_idx'] = 0

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)