from flask import Blueprint, request, jsonify, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from database import get_connection, get_user_by_id
from psycopg.errors import UniqueViolation
import os


friends_bp = Blueprint("friends", __name__)

TOKEN_MAX_AGE = 7 * 24 * 60 * 60
TOKEN_SALT = "numora-admin-access"

token_serializer = URLSafeTimedSerializer(
    os.environ.get(
        "SECRET_KEY",
        "change-this-secret-in-production"
    ),
    salt=TOKEN_SALT
)


# =========================
# DATABASE
# =========================

def init_friends_tables():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS friendships (
                    id BIGSERIAL PRIMARY KEY,

                    user_low_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,

                    user_high_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,

                    requester_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,

                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted')),

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    CONSTRAINT unique_friendship_pair
                        UNIQUE (user_low_id, user_high_id),

                    CONSTRAINT valid_friendship_pair
                        CHECK (user_low_id < user_high_id),

                    CONSTRAINT valid_requester
                        CHECK (
                            requester_id = user_low_id
                            OR requester_id = user_high_id
                        )
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_friendships_low_status
                ON friendships(user_low_id, status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_friendships_high_status
                ON friendships(user_high_id, status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_friendships_requester_status
                ON friendships(requester_id, status)
            """)


# =========================
# AUTHENTICATION
# =========================

def get_current_user():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return None

    try:
        payload = token_serializer.loads(
            token,
            max_age=TOKEN_MAX_AGE
        )

        user_id = int(payload.get("user_id"))

    except (
        BadSignature,
        SignatureExpired,
        TypeError,
        ValueError
    ):
        return None

    return get_user_by_id(user_id)


def login_required():
    user = get_current_user()

    if not user:
        return None, (
            jsonify({
                "error": "Please log in first."
            }),
            401
        )

    return user, None


def pair_ids(first_id, second_id):
    return (
        min(first_id, second_id),
        max(first_id, second_id)
    )


# =========================
# SEARCH USERS
# =========================

@friends_bp.route("/api/friends/search", methods=["GET"])
def search_users():
    user, error = login_required()

    if error:
        return error

    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify({
            "users": [],
            "message": "Enter at least 2 characters."
        }), 200

    if len(query) > 30:
        return jsonify({
            "error": "Search query is too long."
        }), 400

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        u.id,
                        u.username,
                        CASE
                            WHEN f.status = 'accepted'
                                THEN 'friends'
                            WHEN f.status = 'pending'
                                AND f.requester_id = %s
                                THEN 'outgoing'
                            WHEN f.status = 'pending'
                                THEN 'incoming'
                            ELSE 'none'
                        END AS relationship
                    FROM users u

                    LEFT JOIN friendships f
                        ON f.user_low_id = LEAST(u.id, %s)
                        AND f.user_high_id = GREATEST(u.id, %s)

                    WHERE
                        u.id != %s
                        AND u.username ILIKE %s

                    ORDER BY u.username ASC
                    LIMIT 20
                """, (
                    user["id"],
                    user["id"],
                    user["id"],
                    user["id"],
                    f"%{query}%"
                ))

                users = [
                    dict(row)
                    for row in cursor.fetchall()
                ]

        return jsonify({
            "users": users
        }), 200

    except Exception:
        current_app.logger.exception(
            "Friends user search failed"
        )

        return jsonify({
            "error": "Could not search users."
        }), 500


# =========================
# FRIEND LIST
# =========================

@friends_bp.route("/api/friends", methods=["GET"])
def get_friends():
    user, error = login_required()

    if error:
        return error

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        u.id,
                        u.username,
                        f.created_at AS friends_since

                    FROM friendships f

                    JOIN users u
                        ON u.id = CASE
                            WHEN f.user_low_id = %s
                                THEN f.user_high_id
                            ELSE f.user_low_id
                        END

                    WHERE
                        (
                            f.user_low_id = %s
                            OR f.user_high_id = %s
                        )
                        AND f.status = 'accepted'

                    ORDER BY u.username ASC
                """, (
                    user["id"],
                    user["id"],
                    user["id"]
                ))

                friends = [
                    dict(row)
                    for row in cursor.fetchall()
                ]

        return jsonify({
            "friends": friends,
            "total": len(friends)
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not retrieve friends"
        )

        return jsonify({
            "error": "Could not load friends."
        }), 500


# =========================
# FRIEND REQUESTS
# =========================

@friends_bp.route("/api/friends/requests", methods=["GET"])
def get_friend_requests():
    user, error = login_required()

    if error:
        return error

    user_id = user["id"]

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:

                # Incoming requests
                cursor.execute("""
                    SELECT
                        f.id,
                        u.id AS user_id,
                        u.username,
                        f.created_at

                    FROM friendships f

                    JOIN users u
                        ON u.id = f.requester_id

                    WHERE
                        (
                            f.user_low_id = %s
                            OR f.user_high_id = %s
                        )
                        AND f.requester_id != %s
                        AND f.status = 'pending'

                    ORDER BY f.created_at DESC
                """, (user_id, user_id, user_id))

                incoming = [
                    dict(row)
                    for row in cursor.fetchall()
                ]

                # Outgoing requests
                cursor.execute("""
                    SELECT
                        f.id,
                        u.id AS user_id,
                        u.username,
                        f.created_at

                    FROM friendships f

                    JOIN users u
                        ON u.id = CASE
                            WHEN f.user_low_id = %s
                                THEN f.user_high_id
                            ELSE f.user_low_id
                        END

                    WHERE
                        f.requester_id = %s
                        AND f.status = 'pending'

                    ORDER BY f.created_at DESC
                """, (user_id, user_id))

                outgoing = [
                    dict(row)
                    for row in cursor.fetchall()
                ]

        return jsonify({
            "incoming": incoming,
            "outgoing": outgoing,
            "incoming_total": len(incoming),
            "outgoing_total": len(outgoing)
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not retrieve friend requests"
        )

        return jsonify({
            "error": "Could not load friend requests."
        }), 500


# =========================
# SEND FRIEND REQUEST
# =========================

@friends_bp.route("/api/friends/request", methods=["POST"])
def send_friend_request():
    user, error = login_required()

    if error:
        return error

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid request data."
        }), 400

    username = data.get("username", "")

    if not isinstance(username, str):
        return jsonify({
            "error": "Invalid username."
        }), 400

    username = username.strip()

    if len(username) < 3 or len(username) > 30:
        return jsonify({
            "error": "Invalid username."
        }), 400

    user_id = user["id"]

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:

                cursor.execute("""
                    SELECT id, username
                    FROM users
                    WHERE LOWER(username) = LOWER(%s)
                    LIMIT 1
                """, (username,))

                target = cursor.fetchone()

                if not target:
                    return jsonify({
                        "error": "User not found."
                    }), 404

                target_id = target["id"]

                if target_id == user_id:
                    return jsonify({
                        "error": "You cannot add yourself."
                    }), 400

                low_id, high_id = pair_ids(
                    user_id,
                    target_id
                )

                cursor.execute("""
                    SELECT *
                    FROM friendships
                    WHERE
                        user_low_id = %s
                        AND user_high_id = %s
                    FOR UPDATE
                """, (low_id, high_id))

                existing = cursor.fetchone()

                if existing:
                    if existing["status"] == "accepted":
                        return jsonify({
                            "error": "You are already friends."
                        }), 409

                    if existing["requester_id"] == user_id:
                        return jsonify({
                            "error": "Request already sent."
                        }), 409

                    # The other user already requested you.
                    cursor.execute("""
                        UPDATE friendships
                        SET
                            status = 'accepted',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (existing["id"],))

                    return jsonify({
                        "message": "Friend request accepted.",
                        "status": "accepted"
                    }), 200

                cursor.execute("""
                    INSERT INTO friendships (
                        user_low_id,
                        user_high_id,
                        requester_id,
                        status
                    )
                    VALUES (%s, %s, %s, 'pending')
                """, (
                    low_id,
                    high_id,
                    user_id
                ))

        return jsonify({
            "message": "Friend request sent.",
            "status": "outgoing"
        }), 201

    except UniqueViolation:
        return jsonify({
            "error": "A request already exists."
        }), 409

    except Exception:
        current_app.logger.exception(
            "Could not send friend request"
        )

        return jsonify({
            "error": "Could not send friend request."
        }), 500


# =========================
# ACCEPT FRIEND REQUEST
# =========================

@friends_bp.route(
    "/api/friends/requests/<int:request_id>/accept",
    methods=["POST"]
)
def accept_friend_request(request_id):
    user, error = login_required()

    if error:
        return error

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT *
                    FROM friendships
                    WHERE id = %s
                    FOR UPDATE
                """, (request_id,))

                friendship = cursor.fetchone()

                if not friendship:
                    return jsonify({
                        "error": "Request not found."
                    }), 404

                if friendship["status"] != "pending":
                    return jsonify({
                        "error": "This request is no longer pending."
                    }), 409

                if friendship["requester_id"] == user["id"]:
                    return jsonify({
                        "error": "You cannot accept your own request."
                    }), 403

                if user["id"] not in (
                    friendship["user_low_id"],
                    friendship["user_high_id"]
                ):
                    return jsonify({
                        "error": "You cannot accept this request."
                    }), 403

                cursor.execute("""
                    UPDATE friendships
                    SET
                        status = 'accepted',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (request_id,))

        return jsonify({
            "message": "Friend request accepted.",
            "status": "friends"
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not accept friend request"
        )

        return jsonify({
            "error": "Could not accept request."
        }), 500


# =========================
# REJECT FRIEND REQUEST
# =========================

@friends_bp.route(
    "/api/friends/requests/<int:request_id>/reject",
    methods=["POST"]
)
def reject_friend_request(request_id):
    user, error = login_required()

    if error:
        return error

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT *
                    FROM friendships
                    WHERE id = %s
                    FOR UPDATE
                """, (request_id,))

                friendship = cursor.fetchone()

                if not friendship:
                    return jsonify({
                        "error": "Request not found."
                    }), 404

                if friendship["status"] != "pending":
                    return jsonify({
                        "error": "This request is no longer pending."
                    }), 409

                if friendship["requester_id"] == user["id"]:
                    return jsonify({
                        "error": "You cannot reject your own request."
                    }), 403

                if user["id"] not in (
                    friendship["user_low_id"],
                    friendship["user_high_id"]
                ):
                    return jsonify({
                        "error": "You cannot reject this request."
                    }), 403

                cursor.execute("""
                    DELETE FROM friendships
                    WHERE id = %s
                """, (request_id,))

        return jsonify({
            "message": "Friend request rejected."
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not reject friend request"
        )

        return jsonify({
            "error": "Could not reject request."
        }), 500


# =========================
# CANCEL OUTGOING REQUEST
# =========================

@friends_bp.route(
    "/api/friends/requests/<int:request_id>",
    methods=["DELETE"]
)
def cancel_friend_request(request_id):
    user, error = login_required()

    if error:
        return error

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM friendships
                    WHERE
                        id = %s
                        AND requester_id = %s
                        AND status = 'pending'
                    RETURNING id
                """, (request_id, user["id"]))

                deleted = cursor.fetchone()

                if not deleted:
                    return jsonify({
                        "error": "Request not found or cannot be cancelled."
                    }), 404

        return jsonify({
            "message": "Friend request cancelled."
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not cancel friend request"
        )

        return jsonify({
            "error": "Could not cancel request."
        }), 500


# =========================
# REMOVE FRIEND
# =========================

@friends_bp.route(
    "/api/friends/<int:friend_id>",
    methods=["DELETE"]
)
def remove_friend(friend_id):
    user, error = login_required()

    if error:
        return error

    user_id = user["id"]

    if friend_id == user_id:
        return jsonify({
            "error": "Invalid friend ID."
        }), 400

    low_id, high_id = pair_ids(
        user_id,
        friend_id
    )

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM friendships
                    WHERE
                        user_low_id = %s
                        AND user_high_id = %s
                        AND status = 'accepted'
                    RETURNING id
                """, (low_id, high_id))

                deleted = cursor.fetchone()

                if not deleted:
                    return jsonify({
                        "error": "Friend not found."
                    }), 404

        return jsonify({
            "message": "Friend removed."
        }), 200

    except Exception:
        current_app.logger.exception(
            "Could not remove friend"
        )

        return jsonify({
            "error": "Could not remove friend."
        }), 500
