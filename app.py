
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room, emit
from database import (
    init_database, create_user, get_user_by_username,
    get_user_by_email, get_user_by_id, save_game_result,
    get_user_results, get_user_stats
)
import random
import os
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='gevent'
)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


init_database()


# =========================
# API ROUTES
# =========================

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Number Game API is running!"})


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

    if len(password) < 6:
        return jsonify({"error": "رمز عبور باید حداقل ۶ کاراکتر باشد!"}), 400

    if get_user_by_username(username):
        return jsonify({"error": "این نام کاربری قبلاً گرفته شده!"}), 400

    if get_user_by_email(email):
        return jsonify({"error": "این ایمیل قبلاً ثبت شده!"}), 400

    user_id = create_user(
        username,
        email,
        generate_password_hash(password)
    )

    if not user_id:
        return jsonify({"error": "خطا در ساخت حساب!"}), 500

    return jsonify({
        "message": "ثبت‌نام موفق!",
        "user": {
            "id": user_id,
            "username": username,
            "email": email
        }
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
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"]
        }
    }), 200


@app.route("/api/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = get_user_by_id(user_id)

    if not user:
        return jsonify({"error": "کاربر پیدا نشد!"}), 404

    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "email": user["email"]
    }), 200


@app.route("/api/save-result", methods=["POST"])
def save_result():
    data = request.get_json()

    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400

    save_game_result(
        data.get("user_id"),
        data.get("score"),
        data.get("rank"),
        data.get("players"),
        data.get("rounds")
    )

    return jsonify({"message": "نتیجه ذخیره شد!"}), 201


@app.route("/api/results/<int:user_id>", methods=["GET"])
def get_results(user_id):
    return jsonify({
        "results": get_user_results(user_id)
    }), 200


@app.route("/api/stats/<int:user_id>", methods=["GET"])
def get_stats(user_id):
    return jsonify({
        "stats": get_user_stats(user_id)
    }), 200


# =========================
# GAME DATA
# =========================

rooms_data = {}
games_data = {}


easy_questions = [
    (f"{a} + {b}", a + b)
    for a in range(1, 11)
    for b in range(1, 11)
    if a + b <= 20
]

medium_questions = [
    (f"{a} - {b}", a - b)
    for a in range(1, 21)
    for b in range(1, 21)
    if 1 <= a - b <= 20
]

hard_questions = [
    (f"{a} × {b}", a * b)
    for a in range(1, 21)
    for b in range(1, 21)
    if a * b <= 20
]


def get_new_question():
    level = random.choice(["easy", "medium", "hard"])

    if level == "easy":
        q, ans = random.choice(easy_questions)
        t = 7
    elif level == "medium":
        q, ans = random.choice(medium_questions)
        t = 10
    else:
        q, ans = random.choice(hard_questions)
        t = 15

    return {
        "question": q,
        "answer": ans,
        "time_limit": t
    }


# =========================
# CREATE ROOM
# =========================

@socketio.on('create_room')
def handle_create_room(data):
    room_code = data.get('room_code')
    username = data.get('username')
    max_players = data.get('max_players', 2)
    bot_count = data.get('bot_count', 0)
    bot_difficulty = data.get('bot_difficulty', 'medium')

    if not room_code or not username:
        return

    try:
        max_players = int(max_players)
        bot_count = int(bot_count)
    except (TypeError, ValueError):
        emit('error', {'message': 'تنظیمات اتاق نامعتبر است!'})
        return

    max_players = max(2, min(max_players, 20))
    bot_count = max(0, min(bot_count, 5))

    if bot_count + 1 > max_players:
        emit('error', {
            'message': 'ظرفیت اتاق برای این تعداد بات کافی نیست!'
        })
        return

    if room_code in rooms_data:
        emit('error', {'message': 'این کد اتاق قبلاً استفاده شده است!'})
        return

    join_room(room_code)

    players = [username]

    for i in range(bot_count):
        players.append(f"بات {i + 1}")

    rooms_data[room_code] = {
        'players': players,
        'host': username,
        'max_players': max_players,
        'bot_count': bot_count,
        'bot_difficulty': bot_difficulty
    }

    emit('update_players', rooms_data[room_code], room=room_code)


# =========================
# JOIN ROOM
# =========================

@socketio.on('join_room')
def handle_join_room(data):
    room_code = data.get('room_code')
    username = data.get('username')

    if not room_code or not username:
        return

    if room_code not in rooms_data:
        emit('error', {'message': 'اتاق پیدا نشد!'})
        return

    room = rooms_data[room_code]

    is_existing_player = username in room['players']

    if not is_existing_player and len(room['players']) >= room['max_players']:
        emit('error', {'message': 'اتاق پر است!'})
        return

    join_room(room_code)

    if not is_existing_player:
        room['players'].append(username)

        emit(
            'player_joined',
            {'username': username},
            room=room_code,
            include_self=False
        )

    emit('update_players', room, room=room_code)

    # ارسال وضعیت بازی برای بازیکنی که دوباره وصل شده
    if room_code in games_data:
        emit(
            'update_game_state',
            {'state': games_data[room_code]}
        )


# =========================
# KICK PLAYER
# =========================

@socketio.on('kick_player')
def handle_kick_player(data):
    room_code = data.get('room_code')
    username_to_kick = data.get('username_to_kick')
    host = data.get('host')

    if room_code not in rooms_data:
        return

    room = rooms_data[room_code]

    if room['host'] != host:
        return

    if username_to_kick not in room['players']:
        return

    if username_to_kick == room['host']:
        return

    room['players'].remove(username_to_kick)

    emit('update_players', room, room=room_code)

    emit(
        'kicked',
        {'username': username_to_kick},
        room=room_code
    )


# =========================
# START GAME
# =========================

@socketio.on('start_game')
def handle_start_game(data):
    room_code = data.get('room_code')

    if room_code not in rooms_data:
        emit('error', {'message': 'اتاق پیدا نشد!'})
        return

    room = rooms_data[room_code]

    if room_code in games_data:
        emit('error', {'message': 'بازی این اتاق قبلاً شروع شده است!'})
        return

    players = room['players']

    if not players:
        emit('error', {'message': 'هیچ بازیکنی در اتاق نیست!'})
        return

    num_rounds = 5

    rounds_with_math = [
        random.random() < 0.3
        for _ in range(num_rounds)
    ]

    game_players = []

    for p in players:
        is_bot = p.startswith("بات")

        game_players.append({
            'name': p,
            'score': 0,
            'numbers': [0] * num_rounds,
            'is_bot': is_bot
        })

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

        # وضعیت پایان بازی
        'game_over': False
    }

    if rounds_with_math[0]:
        games_data[room_code]['current_question'] = get_new_question()
        games_data[room_code]['round_start_time'] = time.time()

    emit(
        'game_started',
        {
            'room_code': room_code,
            'players': players
        },
        room=room_code
    )

    emit(
        'update_game_state',
        {'state': games_data[room_code]},
        room=room_code
    )


# =========================
# SUBMIT NUMBER
# =========================

@socketio.on('submit_number')
def handle_submit_number(data):
    room_code = data.get('room_code')
    username = data.get('username')
    number = data.get('number')

    if room_code not in games_data:
        emit('error', {'message': 'بازی پیدا نشد!'})
        return

    game = games_data[room_code]

    # جلوگیری از ثبت عدد بعد از پایان بازی
    if game.get('game_over', False):
        emit('error', {'message': 'این بازی به پایان رسیده است!'})
        return

    try:
        number = int(number)
    except (TypeError, ValueError):
        emit('error', {'message': 'عدد واردشده معتبر نیست!'})
        return

    if number < 1 or number > 20:
        emit('error', {'message': 'عدد باید بین ۱ تا ۲۰ باشد!'})
        return

    if game['current_round'] >= game['num_rounds']:
        emit('error', {'message': 'این بازی به پایان رسیده است!'})
        return

    if game['current_player_idx'] >= len(game['players']):
        emit('error', {'message': 'در حال آماده‌سازی دست بعدی هستیم!'})
        return

    current_player = game['players'][game['current_player_idx']]['name']

    if username != current_player:
        emit('error', {'message': 'هنوز نوبت شما نیست!'})
        return

    player_idx = game['current_player_idx']
    round_idx = game['current_round']

    game['players'][player_idx]['numbers'][round_idx] = number

    # بررسی سؤال ریاضی این دست
    if (
        game['rounds_with_math'][round_idx]
        and game['current_question']
        and not game['question_answered']
    ):
        elapsed = time.time() - game['round_start_time']

        if (
            elapsed <= game['current_question']['time_limit']
            and number == game['current_question']['answer']
        ):
            game['players'][player_idx]['score'] += 2

        game['question_answered'] = True

    game['current_player_idx'] += 1

    # پایان نوبت تمام بازیکنان
    if game['current_player_idx'] >= len(game['players']):
        end_round_logic(game)

        # پایان کامل بازی بعد از آخرین دست
        if game['current_round'] >= game['num_rounds']:
            game['game_over'] = True
            game['current_question'] = None
            game['round_start_time'] = None
            game['question_answered'] = False

        else:
            # آماده‌سازی دست بعدی
            if game['rounds_with_math'][game['current_round']]:
                game['current_question'] = get_new_question()
                game['round_start_time'] = time.time()
                game['question_answered'] = False
            else:
                game['current_question'] = None
                game['round_start_time'] = None
                game['question_answered'] = False

    # ارسال وضعیت جدید به همه بازیکنان
    emit(
        'update_game_state',
        {'state': game},
        room=room_code
    )


# =========================
# END ROUND
# =========================

def end_round_logic(game):
    r = game['current_round']

    one_count = sum(
        1 for p in game['players']
        if p['numbers'][r] < 10
    )

    two_count = len(game['players']) - one_count

    if one_count < two_count:
        for p in game['players']:
            if p['numbers'][r] < 10:
                p['score'] += 3

    elif two_count < one_count:
        for p in game['players']:
            if p['numbers'][r] >= 10:
                p['score'] += 3

    # امتیاز عددهای منحصربه‌فرد
    for i, p in enumerate(game['players']):
        num = p['numbers'][r]

        is_unique = all(
            k == i or game['players'][k]['numbers'][r] != num
            for k in range(len(game['players']))
        )

        if is_unique:
            p['score'] += 1

    # مرتب‌سازی بر اساس امتیاز
    game['players'].sort(
        key=lambda x: x['score'],
        reverse=True
    )

    game['current_round'] += 1
    game['current_player_idx'] = 0


# =========================
# RUN SERVER
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    socketio.run(
        app,
        debug=False,
        host="0.0.0.0",
        port=port,
        allow_unsafe_werkzeug=True
    )
