import argparse
import csv
import json
import os
import random
import sqlite3
import sys
from contextlib import contextmanager
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()


def get_image_folder():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "images")
    else:
        return "images"


def define_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="登録するシナリオのjsonファイル")
    parser.add_argument("-r", "--register", help="ユーザ登録用のcsvファイル")
    parser.add_argument(
        "-d",
        "--database",
        default=os.getenv("DATABASE") or "engine.db",
        help="データベースファイル名",
    )
    parser.add_argument(
        "-p", "--port", default=os.getenv("PORT"), help="サーバのポート番号"
    )
    parser.add_argument(
        "--registrable", action="store_true", help="ユーザ登録機能有効化"
    )

    return parser.parse_args()


args = define_argparse()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
debug = os.getenv("DEBUG", False)
image_folder = get_image_folder()


def transact(db_url):
    def transact(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                conn = sqlite3.connect(db_url)
                conn.row_factory = sqlite3.Row
                result = func(conn, *args, **kwargs)
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

        return wrapper

    return transact


@contextmanager
def db_connection(db_file):
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


@transact(args.database)
def init_db(db: sqlite3.Connection):
    # ユーザーテーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        """
    )

    # シナリオテーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL
        )
        """
    )

    # シーンテーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            scene_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            image TEXT,
            is_end BOOLEAN NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id)
        )
        """
    )

    # 選択肢テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id INTEGER NOT NULL,
            next_id INTEGER,
            text TEXT NOT NULL,
            FOREIGN KEY (scene_id) REFERENCES scenes (id)
        )
        """
    )

    # ランダム選択肢テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS random_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            selection_id INTEGER NOT NULL,
            next_id INTEGER NOT NULL,
            FOREIGN KEY (selection_id) REFERENCES selections (id)
        )
        """
    )

    # プレイ履歴テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            scenario_id INTEGER NOT NULL,
            current_scene_id INTEGER NOT NULL,
            is_completed BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id)
        )
        """
    )

    # 選択履歴テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS selection_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            play_history_id INTEGER NOT NULL,
            scene_id INTEGER NOT NULL,
            selection_id INTEGER NOT NULL,
            FOREIGN KEY (play_history_id) REFERENCES play_history (id),
            FOREIGN KEY (scene_id) REFERENCES scenes (id),
            FOREIGN KEY (selection_id) REFERENCES selections (id)
        )
        """
    )


@transact(args.database)
def register_from_csv(db: sqlite3.Connection, csv_file: str):
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for user in reader:
            db.execute(
                "INSERT OR REPLACE INTO users (username, password) VALUES (?, ?)",
                (user["username"], generate_password_hash(user["password"])),
            )


@transact(args.database)
def import_scenario(db: sqlite3.Connection, scenario_data):
    cursor = db.cursor()

    # 既存のシーンと選択肢を削除
    existing_scenario = cursor.execute(
        "SELECT id FROM scenarios WHERE title = ?", (scenario_data["title"],)
    ).fetchone()
    if existing_scenario:
        cursor.execute(
            """
            DELETE FROM random_selections WHERE selection_id IN
            (
                SELECT sel.id
                FROM selections sel
                JOIN scenes sc ON sel.scene_id = sc.id
                WHERE sc.scenario_id = ?
            )
            """,
            (existing_scenario["id"],),
        )
        cursor.execute(
            """
            DELETE FROM selections WHERE scene_id IN
            (SELECT id FROM scenes WHERE scenario_id = ?)
            """,
            (existing_scenario["id"],),
        )
        cursor.execute(
            "DELETE FROM scenes WHERE scenario_id = ?", (existing_scenario["id"],)
        )

    # シナリオの登録
    scenario_id = cursor.execute(
        "INSERT OR REPLACE INTO scenarios (title, description) VALUES (?, ?) RETURNING id",
        (scenario_data["title"], scenario_data["description"]),
    ).fetchone()["id"]

    # シーンと選択肢の登録
    for scene in scenario_data["scenes"]:
        cursor.execute(
            "INSERT INTO scenes (scenario_id, scene_id, text, image, is_end) VALUES (?, ?, ?, ?, ?)",
            (
                scenario_id,
                scene["id"],
                scene["text"],
                scene.get("image"),
                scene.get("end", False),
            ),
        )
        scene_id = cursor.lastrowid

        for selection in scene.get("selection", []):
            cursor.execute(
                "INSERT INTO selections (scene_id, next_id, text) VALUES (?, ?, ?)",
                (scene_id, dict(selection).get("nextId"), selection["text"]),
            )
            selection_id = cursor.lastrowid
            for random_selection in selection.get("nextIds", []):
                cursor.execute(
                    "INSERT INTO random_selections (selection_id, next_id) VALUES (?, ?)",
                    (selection_id, random_selection),
                )
    cursor.close()


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("scenario_list"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
@transact(args.database)
def register(db: sqlite3.Connection):
    if not args.registrable:
        abort(404)
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        try:
            db.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            flash("Registration successful!")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists!")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@transact(args.database)
def login(db: sqlite3.Connection):
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("scenario_list"))

        flash("Invalid username or password!")

    return render_template("login.html", registrable=args.registrable)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/scenarios")
@login_required
@transact(args.database)
def scenario_list(db: sqlite3.Connection):
    scenarios = db.execute(
        """
        SELECT s.*, ph.current_scene_id, ph.is_completed,
            (SELECT scene_id FROM scenes WHERE scenario_id = s.id ORDER BY scene_id LIMIT 1) as first_scene_id
        FROM scenarios s
        LEFT JOIN play_history ph ON s.id = ph.scenario_id AND ph.user_id = ?
        """,
        (session["user_id"],),
    ).fetchall()

    return render_template("scenario_list.html", scenarios=scenarios)


@app.route("/images/<path:path>")
@login_required
def send_image(path):
    return send_from_directory(image_folder, path)


@app.route("/play/<int:scenario_id>/start")
@login_required
@transact(args.database)
def start_scenario(db: sqlite3.Connection, scenario_id):
    # 最初のシーンを取得
    first_scene = db.execute(
        """
        SELECT scene_id
        FROM scenes
        WHERE scenario_id = ?
        ORDER BY scene_id
        LIMIT 1
        """,
        (scenario_id,),
    ).fetchone()

    if not first_scene:
        flash("Scenario not found!")
        return redirect(url_for("scenario_list"))

    # 既存のプレイ履歴を削除
    db.execute(
        """
        DELETE FROM selection_history
        WHERE play_history_id IN (
            SELECT id FROM play_history
            WHERE user_id = ? AND scenario_id = ?
        )
        """,
        (session["user_id"], scenario_id),
    )
    db.execute(
        """
        DELETE FROM play_history
        WHERE user_id = ? AND scenario_id = ?
        """,
        (session["user_id"], scenario_id),
    )

    # 新しいプレイ履歴を作成
    db.execute(
        """
        INSERT INTO play_history (user_id, scenario_id, current_scene_id, is_completed)
        VALUES (?, ?, ?, 0)
        """,
        (session["user_id"], scenario_id, first_scene["scene_id"]),
    )

    return redirect(url_for("play_scenario", scenario_id=scenario_id))


@app.route("/play/<int:scenario_id>")
@login_required
@transact(args.database)
def play_scenario(db: sqlite3.Connection, scenario_id):
    # プレイ履歴を取得
    play_history = db.execute(
        """
        SELECT * FROM play_history
        WHERE user_id = ? AND scenario_id = ?
        """,
        (session["user_id"], scenario_id),
    ).fetchone()

    if not play_history:
        return redirect(url_for("start_scenario", scenario_id=scenario_id))

    # 現在のシーンを取得
    current_scene = db.execute(
        """
        SELECT s.*, sc.title as scenario_title
        FROM scenes s
        JOIN scenarios sc ON s.scenario_id = sc.id
        WHERE s.scenario_id = ? AND s.scene_id = ?
        """,
        (scenario_id, play_history["current_scene_id"]),
    ).fetchone()

    # 選択肢を取得
    selections = db.execute(
        "SELECT * FROM selections WHERE scene_id = ?",
        (current_scene["id"],),
    ).fetchall()

    return render_template(
        "play.html", scenario_id=scenario_id, scene=current_scene, selections=selections
    )


@app.route("/play/<int:scenario_id>/select/<int:selection_id>", methods=["POST"])
@login_required
@transact(args.database)
def make_selection(db: sqlite3.Connection, scenario_id, selection_id):
    # 選択肢の情報を取得
    selection = db.execute(
        """
        SELECT s.*, sc.scene_id as current_scene_id
        FROM selections s
        JOIN scenes sc ON s.scene_id = sc.id
        WHERE s.id = ?
        """,
        (selection_id,),
    ).fetchone()

    if not selection:
        flash("Invalid selection!")
        return redirect(url_for("play_scenario", scenario_id=scenario_id))

    # プレイ履歴を取得
    play_history = db.execute(
        """
        SELECT * FROM play_history
        WHERE user_id = ? AND scenario_id = ?
        """,
        (session["user_id"], scenario_id),
    ).fetchone()

    # 選択履歴を保存
    db.execute(
        """
        INSERT INTO selection_history (play_history_id, scene_id, selection_id)
        VALUES (?, ?, ?)
        """,
        (play_history["id"], selection["scene_id"], selection_id),
    )

    # 次のシーンの情報を取得
    next_id = dict(selection).get("next_id")
    if next_id is None:
        # TODO: ランダム移動先を取得
        random_selections = db.execute(
            """
            SELECT next_id FROM random_selections
            WHERE selection_id = ?
            """,
            (selection_id,),
        ).fetchall()
        random_selections = list(map(lambda x: x["next_id"], random_selections))
        next_id = random.choice(random_selections)
    next_scene = db.execute(
        """
        SELECT id, is_end FROM scenes
        WHERE scenario_id = ? AND scene_id = ?
        """,
        (scenario_id, next_id),
    ).fetchone()

    # プレイ履歴を更新
    db.execute(
        """
        UPDATE play_history
        SET current_scene_id = ?, is_completed = ?
        WHERE id = ?
        """,
        (next_id, next_scene["is_end"], play_history["id"]),
    )

    if next_scene["is_end"]:
        return redirect(url_for("show_ending", scenario_id=scenario_id))

    return redirect(url_for("play_scenario", scenario_id=scenario_id))


@app.route("/play/<int:scenario_id>/ending")
@login_required
@transact(args.database)
def show_ending(db: sqlite3.Connection, scenario_id):
    # プレイ履歴を取得
    play_history = db.execute(
        """
        SELECT * FROM play_history
        WHERE user_id = ? AND scenario_id = ?
        """,
        (session["user_id"], scenario_id),
    ).fetchone()

    if not play_history:
        return redirect(url_for("start_scenario", scenario_id=scenario_id))

    # 現在のシーンを取得
    current_scene = db.execute(
        """
        SELECT s.*, sc.title as scenario_title
        FROM scenes s
        JOIN scenarios sc ON s.scenario_id = sc.id
        WHERE s.scenario_id = ? AND s.scene_id = ?
        """,
        (scenario_id, play_history["current_scene_id"]),
    ).fetchone()

    # 選択肢を取得
    selections = db.execute(
        "SELECT * FROM selections WHERE scene_id = ?",
        (current_scene["id"],),
    ).fetchall()

    return render_template(
        "ending.html",
        scenario_id=scenario_id,
        scene=current_scene,
        selections=selections,
    )


@app.route("/play/<int:scenario_id>/review")
@login_required
@transact(args.database)
def show_review(db: sqlite3.Connection, scenario_id):
    # シナリオ情報を取得
    scenario = db.execute(
        "SELECT * FROM scenarios WHERE id = ?",
        (scenario_id,),
    ).fetchone()

    # プレイ履歴を取得
    play_history = db.execute(
        """
        SELECT * FROM play_history
        WHERE user_id = ? AND scenario_id = ?
        """,
        (session["user_id"], scenario_id),
    ).fetchone()

    # 選択履歴を取得
    selection_history = db.execute(
        """
        SELECT sh.*, s.scene_id, s.text as scene_text, s.image as image, sel.text as selection_text
        FROM selection_history sh
        JOIN scenes s ON sh.scene_id = s.id
        JOIN selections sel ON sh.selection_id = sel.id
        WHERE sh.play_history_id = ?
        ORDER BY sh.id
        """,
        (play_history["id"],),
    ).fetchall()

    ending = db.execute(
        """
        SELECT s.*, sc.title as scenario_title
        FROM scenes s
        JOIN scenarios sc ON s.scenario_id = sc.id
        WHERE s.scenario_id = ? AND s.scene_id = ?
        """,
        (scenario_id, play_history["current_scene_id"]),
    ).fetchone()

    return render_template(
        "review.html",
        scenario=scenario,
        selection_history=selection_history,
        ending=ending,
    )


if __name__ == "__main__":
    init_db()
    for scenario_json in args.scenarios:
        try:
            with open(scenario_json, "r", encoding="utf-8") as f:
                scenario_data = json.load(f)
                import_scenario(scenario_data)
            print(f"Imported scenario: {scenario_data['title']}")
        except Exception:
            print(f"Import scenario failed: {scenario_json}")
    if args.register:
        try:
            register_from_csv(args.register)
            print("User registration successful.")
        except Exception:
            print("User registration failed.")

    app.run(host="0.0.0.0", port=args.port, debug=debug)
