
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


def init_database():
    with get_connection() as conn:
        with conn.cursor() as cursor:

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

            # آماده‌سازی نقش مدیر برای مراحل بعدی
            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_admin
                BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_game_results_user_id
                ON game_results(user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_game_results_played_at
                ON game_results(played_at DESC)
            """)


def create_user(username, email, password_hash):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO users
                    (username, email, password_hash)
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
            cursor.execute(
                "SELECT * FROM users WHERE username = %s",
                (username,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_email(email):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def save_game_result(user_id, score, rank, players, rounds):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO game_results
                (user_id, score, rank, players, rounds)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, score, rank, players, rounds))


def get_user_results(user_id, limit=20):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
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
                    COUNT(*) FILTER (WHERE rank = 1) AS wins,
                    AVG(score) AS avg,
                    MAX(score) AS best
                FROM game_results
                WHERE user_id = %s
            """, (user_id,))

            row = cursor.fetchone()

            return {
                "games": row["games"],
                "wins": row["wins"],
                "avg": round(float(row["avg"]), 1)
                    if row["avg"] is not None else 0,
                "best": row["best"] if row["best"] is not None else 0
            }
