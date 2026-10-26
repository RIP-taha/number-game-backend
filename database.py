import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            players INTEGER NOT NULL,
            rounds INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

def create_user(username, email, password_hash):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_username(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_game_result(user_id, score, rank, players, rounds):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO game_results (user_id, score, rank, players, rounds) VALUES (?, ?, ?, ?, ?)",
        (user_id, score, rank, players, rounds)
    )
    conn.commit()
    conn.close()

def get_user_results(user_id, limit=20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM game_results WHERE user_id = ? ORDER BY played_at DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_stats(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM game_results WHERE user_id = ?", (user_id,))
    games = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM game_results WHERE user_id = ? AND rank = 1", (user_id,))
    wins = cursor.fetchone()[0]
    cursor.execute("SELECT AVG(score) FROM game_results WHERE user_id = ?", (user_id,))
    avg = cursor.fetchone()[0]
    cursor.execute("SELECT MAX(score) FROM game_results WHERE user_id = ?", (user_id,))
    best = cursor.fetchone()[0]
    conn.close()
    return {
        "games": games,
        "wins": wins,
        "avg": round(avg, 1) if avg else 0,
        "best": best if best else 0
    }