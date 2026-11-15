
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is not configured!"
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        sslmode="require"
    )


# =========================
# DATABASE INITIALIZATION
# =========================

def init_database():
    with get_connection() as conn:
        with conn.cursor() as cursor:

            # USERS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_admin
                BOOLEAN NOT NULL DEFAULT FALSE
            """)

            # GAME RESULTS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_results (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    score INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    players INTEGER NOT NULL,
                    rounds INTEGER NOT NULL,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_game_results_user_id
                ON game_results(user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_game_results_played_at
                ON game_results(played_at DESC)
            """)

            # NUMORA VOICE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS voice_messages (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    category TEXT NOT NULL
                        CHECK (
                            category IN (
                                'suggestion',
                                'criticism',
                                'bug',
                                'feedback'
                            )
                        ),
                    subject VARCHAR(100),
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK (
                            status IN (
                                'new',
                                'reviewed',
                                'replied',
                                'archived'
                            )
                        ),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_voice_messages_user_id
                ON voice_messages(user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_voice_messages_created_at
                ON voice_messages(created_at DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_voice_messages_status
                ON voice_messages(status)
            """)


# =========================
# USER MANAGEMENT
# =========================

def create_user(username, email, password_hash):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO users (
                        username,
                        email,
                        password_hash
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (username, email, password_hash))

                row = cursor.fetchone()
                return row["id"]

    except UniqueViolation:
        return None


def get_user_by_username(username):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM users
                WHERE username = %s
            """, (username,))

            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_email(email):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM users
                WHERE email = %s
            """, (email,))

            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM users
                WHERE id = %s
            """, (user_id,))

            row = cursor.fetchone()
            return dict(row) if row else None


def get_all_users():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    u.id,
                    u.username,
                    u.email,
                    u.is_admin,
                    u.created_at,
                    COUNT(g.id) AS total_games
                FROM users u
                LEFT JOIN game_results g
                    ON g.user_id = u.id
                GROUP BY u.id
                ORDER BY u.created_at DESC
            """)

            rows = cursor.fetchall()
            return [dict(row) for row in rows]


# =========================
# GAME RESULTS
# =========================

def save_game_result(user_id, score, rank, players, rounds):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO game_results (
                    user_id,
                    score,
                    rank,
                    players,
                    rounds
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id,
                score,
                rank,
                players,
                rounds
            ))

            row = cursor.fetchone()
            return row["id"]


def get_user_results(user_id, limit=20):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    user_id,
                    score,
                    rank,
                    players,
                    rounds,
                    played_at
                FROM game_results
                WHERE user_id = %s
                ORDER BY played_at DESC
                LIMIT %s
            """, (user_id, limit))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_user_stats(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*) AS games,
                    COUNT(*) FILTER (
                        WHERE rank = 1
                    ) AS wins,
                    AVG(score) AS avg,
                    MAX(score) AS best
                FROM game_results
                WHERE user_id = %s
            """, (user_id,))

            row = cursor.fetchone()

            return {
                "games": row["games"],
                "wins": row["wins"],
                "avg": (
                    round(float(row["avg"]), 1)
                    if row["avg"] is not None else 0
                ),
                "best": (
                    row["best"]
                    if row["best"] is not None else 0
                )
            }


# =========================
# NUMORA VOICE
# =========================

VALID_VOICE_CATEGORIES = {
    "suggestion",
    "criticism",
    "bug",
    "feedback"
}

VALID_VOICE_STATUSES = {
    "new",
    "reviewed",
    "replied",
    "archived"
}


def create_voice_message(user_id, category, subject, message):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO voice_messages (
                    user_id,
                    category,
                    subject,
                    message
                )
                VALUES (%s, %s, %s, %s)
                RETURNING
                    id,
                    user_id,
                    category,
                    subject,
                    message,
                    status,
                    created_at
            """, (
                user_id,
                category,
                subject,
                message
            ))

            return dict(cursor.fetchone())


def get_user_voice_messages(user_id, limit=200):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    user_id,
                    category,
                    subject,
                    message,
                    status,
                    created_at
                FROM voice_messages
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
            """, (user_id, limit))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_all_voice_messages(category=None, status=None):
    conditions = []
    params = []

    if category:
        conditions.append("vm.category = %s")
        params.append(category)

    if status:
        conditions.append("vm.status = %s")
        params.append(status)

    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    query = f"""
        SELECT
            vm.id,
            vm.user_id,
            vm.category,
            vm.subject,
            vm.message,
            vm.status,
            vm.created_at,
            u.username,
            u.email
        FROM voice_messages vm
        JOIN users u ON u.id = vm.user_id
        {where_clause}
        ORDER BY vm.created_at DESC, vm.id DESC
        LIMIT 500
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)

            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def update_voice_message_status(message_id, status):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE voice_messages
                SET status = %s
                WHERE id = %s
                RETURNING
                    id,
                    user_id,
                    category,
                    subject,
                    message,
                    status,
                    created_at
            """, (status, message_id))

            row = cursor.fetchone()
            return dict(row) if row else None

