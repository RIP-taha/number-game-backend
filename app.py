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
import copy

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'change-this-secret-in-production'
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='gevent'
)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, DELETE, OPTIONS"
    )
    return response


init_database()


# =========================
# API ROUTES
# =========================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Number Game API is running!"
    })


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400

    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")

    if not all(
        isinstance(value, str)
        for value in (username, email, password)
    ):
        return jsonify({
            "error": "اطلاعات واردشده معتبر نیست!"
        }), 400

    username = username.strip()
    email = email.strip()

    if not username or not email or not password:
        return jsonify({
            "error": "همه فیلدها الزامی است!"
        }), 400

    if len(username) < 3:
        return jsonify({
            "error": "نام کاربری باید حداقل ۳ کاراکتر باشد!"
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "رمز عبور باید حداقل ۶ کاراکتر باشد!"
        }), 400

    if get_user_by_username(username):
        return jsonify({
            "error": "این نام کاربری قبلاً گرفته شده!"
        }), 400

    if get_user_by_email(email):
        return jsonify({
            "error": "این ایمیل قبلاً ثبت شده!"
        }), 400

    user_id = create_user(
        username,
        email,
        generate_password_hash(password)
    )

    if not user_id:
        return jsonify({
            "error": "خطا در ساخت حساب!"
        }), 500

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
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400

    username = data.get("username", "")
    password = data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({
            "error": "اطلاعات واردشده معتبر نیست!"
        }), 400

    username = username.strip()

    if not username or not password:
        return jsonify({
            "error": "همه فیلدها الزامی است!"
        }), 400

    user = get_user_by_username(username)

    if not user:
        return jsonify({
            "error": "کاربری با این نام پیدا نشد!"
        }), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({
            "error": "رمز عبور اشتباه است!"
        }), 401

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
        return jsonify({
            "error": "کاربر پیدا نشد!"
        }), 404

    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "email": user["email"]
    }), 200


@app.route("/api/save-result", methods=["POST"])
def save_result():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "داده‌ای ارسال نشد!"}), 400

    required_fields = (
        "user_id", "score", "rank", "players", "rounds"
    )

    if any(field not in data for field in required_fields):
        return jsonify({
            "error": "اطلاعات نتیجه کامل نیست!"
        }), 400

    try:
        user_id = int(data["user_id"])
        score = int(data["score"])
        rank = int(data["rank"])
        players_count = int(data["players"])
        rounds = int(data["rounds"])
    except (TypeError, ValueError):
        return jsonify({
            "error": "اطلاعات نتیجه معتبر نیست!"
        }), 400

    if (
        user_id < 1
        or score < 0
        or rank < 1
        or players_count < 1
        or rounds < 1
    ):
        return jsonify({
            "error": "اطلاعات نتیجه خارج از محدوده مجاز است!"
        }), 400

    save_game_result(
        user_id,
        score,
        rank,
        players_count,
        rounds
    )

    return jsonify({
        "message": "نتیجه ذخیره شد!"
    }), 201


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

VALID_BOT_DIFFICULTIES = {
    "easy",
    "medium",
    "hard"
}

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
    level = random.choice([
        "easy",
        "medium",
        "hard"
    ])

    if level == "easy":
        question, answer = random.choice(easy_questions)
        time_limit = 7

    elif level == "medium":
        question, answer = random.choice(medium_questions)
        time_limit = 10

    else:
        question, answer = random.choice(hard_questions)
        time_limit = 15

    return {
        "question": question,
        "answer": answer,
        "time_limit": time_limit
    }


def emit_game_state(room_code):
    """
    ارسال نسخه امن وضعیت بازی به اعضای اتاق.

    عددهای دست جاری تا پایان آن دست مخفی می‌مانند.
    اطلاعات اصلی بازی در سرور تغییر نمی‌کند.
    """

    game = games_data.get(room_code)

    if game is None:
        return

    # روی یک کپی کار می‌کنیم تا عددهای واقعی بازی
    # در حافظه سرور دست‌نخورده باقی بمانند.
    public_game = copy.deepcopy(game)

    current_round = public_game["current_round"]
    num_rounds = public_game["num_rounds"]
    game_over = public_game.get("game_over", False)

    # در طول بازی، عددهای دست جاری برای همه مخفی‌اند.
    # پس از پایان دست، current_round افزایش پیدا می‌کند
    # و عددهای دست قبلی در وضعیت بعدی قابل مشاهده می‌شوند.
    if not game_over and current_round < num_rounds:
        for player in public_game["players"]:
            numbers = player.get("numbers", [])

            if current_round < len(numbers):
                numbers[current_round] = None

    socketio.emit(
        "update_game_state",
        {"state": public_game},
        to=room_code
    )


def get_real_players(room):
    """برگرداندن بازیکنان واقعی بدون بات‌ها."""

    bot_names = set(room.get("bot_names", []))

    return [
        player
        for player in room["players"]
        if player not in bot_names
    ]


def choose_bot_number(game, player, round_idx):
    """انتخاب عدد توسط بات."""

    difficulty = game.get("bot_difficulty", "medium")

    if difficulty not in VALID_BOT_DIFFICULTIES:
        difficulty = "medium"

    if difficulty == "easy":
        return random.randint(1, 20)

    previous_numbers = [
        p["numbers"][round_idx]
        for p in game["players"]
        if p["name"] != player["name"]
        and len(p.get("numbers", [])) > round_idx
        and p["numbers"][round_idx] != 0
    ]

    if difficulty == "medium":
        return random.randint(1, 20)

    # Hard: تلاش برای انتخاب عدد منحصربه‌فرد
    # و قرار گرفتن در گروه کم‌تعدادتر.

    counts_low = sum(
        1 for number in previous_numbers
        if number < 10
    )

    counts_high = sum(
        1 for number in previous_numbers
        if number >= 10
    )

    if counts_low < counts_high:
        preferred_range = range(1, 10)

    elif counts_high < counts_low:
        preferred_range = range(10, 21)

    else:
        preferred_range = range(1, 21)

    used_numbers = set(previous_numbers)

    preferred_unused = [
        number
        for number in preferred_range
        if number not in used_numbers
    ]

    if preferred_unused:
        return random.choice(preferred_unused)

    all_unused = [
        number
        for number in range(1, 21)
        if number not in used_numbers
    ]

    if all_unused:
        return random.choice(all_unused)

    return random.randint(1, 20)


def apply_number_to_player(game, player_idx, number):
    """ثبت عدد و بررسی امتیاز سؤال ریاضی."""

    round_idx = game["current_round"]
    player = game["players"][player_idx]

    player["numbers"][round_idx] = number

    if (
        game["rounds_with_math"][round_idx]
        and game.get("current_question")
        and not game.get("question_answered", False)
    ):
        elapsed = time.time() - game["round_start_time"]

        if (
            elapsed <= game["current_question"]["time_limit"]
            and number == game["current_question"]["answer"]
        ):
            player["score"] += 2

        game["question_answered"] = True


def prepare_next_round_or_finish(room_code):
    """پایان راند و آماده‌سازی راند بعدی."""

    game = games_data[room_code]

    end_round_logic(game)

    if game["current_round"] >= game["num_rounds"]:
        game["game_over"] = True
        game["current_question"] = None
        game["round_start_time"] = None
        game["question_answered"] = False
        return

    if game["rounds_with_math"][game["current_round"]]:
        game["current_question"] = get_new_question()
        game["round_start_time"] = time.time()
        game["question_answered"] = False

    else:
        game["current_question"] = None
        game["round_start_time"] = None
        game["question_answered"] = False


def process_automatic_bot_turns(room_code):
    """اجرای خودکار نوبت‌های بات."""

    game = games_data.get(room_code)

    if not game or game.get("game_over"):
        return

    while not game.get("game_over"):

        if game["current_round"] >= game["num_rounds"]:
            game["game_over"] = True
            game["current_question"] = None
            game["round_start_time"] = None
            break

        if game["current_player_idx"] >= len(game["players"]):
            prepare_next_round_or_finish(room_code)
            emit_game_state(room_code)

            if game.get("game_over"):
                break

            continue

        current_idx = game["current_player_idx"]
        current_player = game["players"][current_idx]

        if not current_player.get("is_bot", False):
            break

        socketio.sleep(0.45)

        game = games_data.get(room_code)

        if not game or game.get("game_over"):
            return

        if game["current_round"] >= game["num_rounds"]:
            game["game_over"] = True
            game["current_question"] = None
            game["round_start_time"] = None
            break

        if game["current_player_idx"] >= len(game["players"]):
            continue

        current_idx = game["current_player_idx"]
        current_player = game["players"][current_idx]

        if not current_player.get("is_bot", False):
            break

        number = choose_bot_number(
            game,
            current_player,
            game["current_round"]
        )

        apply_number_to_player(
            game,
            current_idx,
            number
        )

        game["current_player_idx"] += 1

        if game["current_player_idx"] >= len(game["players"]):
            prepare_next_round_or_finish(room_code)

        emit_game_state(room_code)


# =========================
# CREATE ROOM
# =========================

@socketio.on("create_room")
def handle_create_room(data):
    data = data or {}

    room_code = data.get("room_code")
    username = data.get("username")
    max_players = data.get("max_players", 2)
    bot_count = data.get("bot_count", 0)
    bot_difficulty = data.get("bot_difficulty", "medium")

    if not isinstance(room_code, str) or not room_code.strip():
        emit("error", {
            "message": "کد اتاق معتبر نیست!"
        })
        return

    if not isinstance(username, str) or not username.strip():
        emit("error", {
            "message": "نام کاربری معتبر نیست!"
        })
        return

    room_code = room_code.strip()
    username = username.strip()

    try:
        max_players = int(max_players)
        bot_count = int(bot_count)
    except (TypeError, ValueError):
        emit("error", {
            "message": "تنظیمات اتاق نامعتبر است!"
        })
        return

    if max_players < 2 or max_players > 20:
        emit("error", {
            "message": "ظرفیت اتاق باید بین ۲ تا ۲۰ باشد!"
        })
        return

    if bot_count < 0 or bot_count > 5:
        emit("error", {
            "message": "تعداد بات باید بین صفر تا پنج باشد!"
        })
        return

    # تعداد بات‌ها در ظرفیت بازیکنان واقعی حساب نمی‌شود.

    if bot_difficulty not in VALID_BOT_DIFFICULTIES:
        bot_difficulty = "medium"

    if room_code in rooms_data:
        emit("error", {
            "message": "این کد اتاق قبلاً استفاده شده است!"
        })
        return

    bot_names = [
        f"بات {i + 1}"
        for i in range(bot_count)
    ]

    if username in bot_names:
        emit("error", {
            "message": "این نام کاربری قابل استفاده نیست!"
        })
        return

    players = [username] + bot_names

    rooms_data[room_code] = {
        "players": players,
        "bot_names": bot_names,
        "host": username,
        "max_players": max_players,
        "bot_count": bot_count,
        "bot_difficulty": bot_difficulty
    }

    join_room(room_code)

    emit(
        "update_players",
        rooms_data[room_code],
        room=room_code
    )


# =========================
# JOIN ROOM
# =========================

@socketio.on("join_room")
def handle_join_room(data):
    data = data or {}

    room_code = data.get("room_code")
    username = data.get("username")

    if not isinstance(room_code, str) or not isinstance(username, str):
        emit("error", {
            "message": "کد اتاق و نام کاربری الزامی است!"
        })
        return

    room_code = room_code.strip()
    username = username.strip()

    if not room_code or not username:
        emit("error", {
            "message": "کد اتاق و نام کاربری الزامی است!"
        })
        return

    if room_code not in rooms_data:
        emit("error", {
            "message": "اتاق پیدا نشد!"
        })
        return

    room = rooms_data[room_code]
    bot_names = set(room.get("bot_names", []))

    if username in bot_names:
        emit("error", {
            "message": "این نام کاربری قابل استفاده نیست!"
        })
        return

    is_existing_player = username in room["players"]
    real_players_count = len(get_real_players(room))

    if (
        not is_existing_player
        and real_players_count >= room["max_players"]
    ):
        emit("error", {
            "message": "ظرفیت بازیکنان واقعی اتاق پر است!"
        })
        return

    join_room(room_code)

    if not is_existing_player:
        room["players"].append(username)

        emit(
            "player_joined",
            {"username": username},
            room=room_code,
            include_self=False
        )

    emit(
        "update_players",
        room,
        room=room_code
    )

    # وضعیت بازی را فقط از تابع امن ارسال می‌کنیم.
    # ارسال مستقیم games_data می‌توانست عددهای مخفی را افشا کند.
    if room_code in games_data:
        emit_game_state(room_code)


# =========================
# KICK PLAYER
# =========================

@socketio.on("kick_player")
def handle_kick_player(data):
    data = data or {}

    room_code = data.get("room_code")
    username_to_kick = data.get("username_to_kick")
    host = data.get("host")

    if room_code not in rooms_data:
        return

    room = rooms_data[room_code]
    bot_names = set(room.get("bot_names", []))

    if room["host"] != host:
        return

    if username_to_kick not in room["players"]:
        return

    if username_to_kick == room["host"]:
        return

    if username_to_kick in bot_names:
        return

    room["players"].remove(username_to_kick)

    emit(
        "update_players",
        room,
        room=room_code
    )

    emit(
        "kicked",
        {"username": username_to_kick},
        room=room_code
    )


# =========================
# START GAME
# =========================

@socketio.on("start_game")
def handle_start_game(data):
    data = data or {}

    room_code = data.get("room_code")

    if room_code not in rooms_data:
        emit("error", {
            "message": "اتاق پیدا نشد!"
        })
        return

    if room_code in games_data:
        emit("error", {
            "message": "بازی این اتاق قبلاً شروع شده است!"
        })
        return

    room = rooms_data[room_code]
    players = room["players"]
    bot_names = set(room.get("bot_names", []))

    if not players:
        emit("error", {
            "message": "هیچ بازیکنی در اتاق نیست!"
        })
        return

    num_rounds = 5

    rounds_with_math = [
        random.random() < 0.3
        for _ in range(num_rounds)
    ]

    game_players = []

    for player_name in players:
        is_bot = player_name in bot_names

        game_players.append({
            "name": player_name,
            "score": 0,
            "numbers": [0] * num_rounds,
            "is_bot": is_bot
        })

    games_data[room_code] = {
        "players": game_players,
        "num_rounds": num_rounds,
        "current_round": 0,
        "current_player_idx": 0,
        "rounds_with_math": rounds_with_math,
        "current_question": None,
        "round_start_time": None,
        "question_answered": False,
        "bot_difficulty": room.get(
            "bot_difficulty",
            "medium"
        ),
        "game_over": False
    }

    if rounds_with_math[0]:
        games_data[room_code]["current_question"] = get_new_question()
        games_data[room_code]["round_start_time"] = time.time()

    emit(
        "game_started",
        {
            "room_code": room_code,
            "players": players
        },
        room=room_code
    )

    emit_game_state(room_code)

    socketio.start_background_task(
        process_automatic_bot_turns,
        room_code
    )


# =========================
# SUBMIT NUMBER
# =========================

@socketio.on("submit_number")
def handle_submit_number(data):
    data = data or {}

    room_code = data.get("room_code")
    username = data.get("username")
    number = data.get("number")

    if room_code not in games_data:
        emit("error", {
            "message": "بازی پیدا نشد!"
        })
        return

    game = games_data[room_code]

    if game.get("game_over", False):
        emit("error", {
            "message": "این بازی به پایان رسیده است!"
        })
        return

    if game["current_round"] >= game["num_rounds"]:
        game["game_over"] = True

        emit("error", {
            "message": "این بازی به پایان رسیده است!"
        })

        emit_game_state(room_code)
        return

    try:
        number = int(number)
    except (TypeError, ValueError):
        emit("error", {
            "message": "عدد واردشده معتبر نیست!"
        })
        return

    if number < 1 or number > 20:
        emit("error", {
            "message": "عدد باید بین ۱ تا ۲۰ باشد!"
        })
        return

    if game["current_player_idx"] >= len(game["players"]):
        emit("error", {
            "message": "در حال آماده‌سازی دست بعدی هستیم!"
        })
        return

    player_idx = game["current_player_idx"]
    current_player = game["players"][player_idx]

    if current_player.get("is_bot", False):
        emit("error", {
            "message": "نوبت بات است؛ سرور در حال اجرای حرکت آن است."
        })
        return

    if username != current_player["name"]:
        emit("error", {
            "message": "هنوز نوبت شما نیست!"
        })
        return

    apply_number_to_player(
        game,
        player_idx,
        number
    )

    game["current_player_idx"] += 1

    if game["current_player_idx"] >= len(game["players"]):
        prepare_next_round_or_finish(room_code)

    emit_game_state(room_code)

    if not game.get("game_over", False):
        socketio.start_background_task(
            process_automatic_bot_turns,
            room_code
        )


# =========================
# END ROUND
# =========================

def end_round_logic(game):
    round_idx = game["current_round"]

    one_count = sum(
        1 for player in game["players"]
        if player["numbers"][round_idx] < 10
    )

    two_count = len(game["players"]) - one_count

    if one_count < two_count:
        for player in game["players"]:
            if player["numbers"][round_idx] < 10:
                player["score"] += 3

    elif two_count < one_count:
        for player in game["players"]:
            if player["numbers"][round_idx] >= 10:
                player["score"] += 3

    for i, player in enumerate(game["players"]):
        number = player["numbers"][round_idx]

        is_unique = all(
            j == i
            or game["players"][j]["numbers"][round_idx] != number
            for j in range(len(game["players"]))
        )

        if is_unique:
            player["score"] += 1

    game["players"].sort(
        key=lambda player: player["score"],
        reverse=True
    )

    game["current_round"] += 1
    game["current_player_idx"] = 0


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

