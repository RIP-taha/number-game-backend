from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room, leave_room, emit
from database import (
    init_database, create_user, get_user_by_username,
    get_user_by_email, get_user_by_id, save_game_result,
    get_user_results, get_user_stats
)
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

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


# --- Socket.IO Events for Rooms and Game ---
rooms_data = {}
games_data = {}

@socketio.on('create_room')
def handle_create_room(data):
    room_code = data.get('room_code')
    username = data.get('username')
    if not room_code or not username: return
    join_room(room_code)
    rooms_data[room_code] = [username]
    emit('update_players', {'players': rooms_data[room_code]}, room=room_code)

@socketio.on('join_room')
def handle_join_room(data):
    room_code = data.get('room_code')
    username = data.get('username')
    if not room_code or not username: return
    join_room(room_code)
    if room_code in rooms_data:
        if username not in rooms_data[room_code]:
            rooms_data[room_code].append(username)
    else:
        rooms_data[room_code] = [username]
    
    emit('update_players', {'players': rooms_data[room_code]}, room=room_code)
    emit('player_joined', {'username': username}, room=room_code, include_self=False)
    
    # اگه بازی در جریان هست، وضعیت رو برای نفر جدید هم بفرست
    if room_code in games_data:
        emit('update_game_state', {'state': games_data[room_code]}, room=room_code)

@socketio.on('start_game')
def handle_start_game(data):
    room_code = data.get('room_code')
    if room_code in rooms_data:
        players = rooms_data[room_code]
        num_rounds = 5
        
        games_data[room_code] = {
            'players': [{'name': p, 'score': 0, 'numbers': [0]*num_rounds} for p in players],
            'num_rounds': num_rounds,
            'current_round': 0,
            'current_player_idx': 0,
            'rounds_with_math': [random.random() < 0.3 for _ in range(num_rounds)]
        }
        
        emit('game_started', {'room_code': room_code, 'players': players}, room=room_code)
        emit('update_game_state', {'state': games_data[room_code]}, room=room_code)

@socketio.on('submit_number')
def handle_submit_number(data):
    room_code = data.get('room_code')
    username = data.get('username')
    number = data.get('number')
    
    if room_code not in games_data: return
    game = games_data[room_code]
    
    current_player = game['players'][game['current_player_idx']]['name']
    if username != current_player: return
    
    player_idx = game['current_player_idx']
    game['players'][player_idx]['numbers'][game['current_round']] = number
    game['current_player_idx'] += 1
    
    if game['current_player_idx'] >= len(game['players']):
        end_round_logic(game)
    
    emit('update_game_state', {'state': game}, room=room_code)

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
    socketio.run(app, debug=False, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)