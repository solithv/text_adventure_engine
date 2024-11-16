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
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from jsonschema import SchemaError, ValidationError, validate
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()


def get_image_folder(image_base):
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), image_base)
    else:
        return image_base


def define_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="登録するシナリオのjsonファイル")
    parser.add_argument("-a", "--admin", help="管理者登録用のcsvファイル")
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


def init_app():
    app = Flask(__name__)
    app.config["ARGS"] = define_argparse()
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.getenv("MAX_CONTENT_LENGTH", 1 * (1024**2))
    )
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "temp")
    app.config["DEBUG"] = os.getenv("DEBUG", False)
    app.config["IMAGE_BASE"] = os.getenv("IMAGE_FOLDER", "images")
    app.config["IMAGE_FOLDER"] = get_image_folder(app.config["IMAGE_BASE"])

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    return app


app = init_app()


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


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return decorated_function


@transact(app.config["ARGS"].database)
def init_db(db: sqlite3.Connection):
    # 管理者テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime'))
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_admins_updated_at AFTER UPDATE ON admins
        BEGIN
            UPDATE admins SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
        """
    )

    # ユーザーテーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime'))
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_users_updated_at AFTER UPDATE ON users
        BEGIN
            UPDATE users SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
        """
    )

    # シナリオテーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime'))
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_scenarios_updated_at AFTER UPDATE ON scenarios
        BEGIN
            UPDATE scenarios SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
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
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id)
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_scenes_updated_at AFTER UPDATE ON scenes
        BEGIN
            UPDATE scenes SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
        """
    )

    # 選択肢テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (scene_id) REFERENCES scenes (id)
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_selections_updated_at AFTER UPDATE ON selections
        BEGIN
            UPDATE selections SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
        """
    )

    # 遷移先テーブル
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS next_scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            selection_id INTEGER NOT NULL,
            next_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (selection_id) REFERENCES selections (id)
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_next_scenes_updated_at AFTER UPDATE ON next_scenes
        BEGIN
            UPDATE next_scenes SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
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
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id)
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_play_history_updated_at AFTER UPDATE ON play_history
        BEGIN
            UPDATE play_history SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
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
            created_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (play_history_id) REFERENCES play_history (id),
            FOREIGN KEY (scene_id) REFERENCES scenes (id),
            FOREIGN KEY (selection_id) REFERENCES selections (id)
        )
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trigger_selection_history_updated_at AFTER UPDATE ON selection_history
        BEGIN
            UPDATE selection_history SET updated_at = DATETIME('now', 'localtime') WHERE rowid == NEW.rowid;
        END
        """
    )


@transact(app.config["ARGS"].database)
def admin_register_from_csv(db: sqlite3.Connection, csv_file: str):
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for admin in reader:
            db.execute(
                """
                INSERT INTO admins (username, password) VALUES (?, ?)
                ON CONFLICT (username)
                DO UPDATE SET password = excluded.password
                """,
                (admin["username"], generate_password_hash(admin["password"])),
            )


@transact(app.config["ARGS"].database)
def register_from_csv(db: sqlite3.Connection, csv_file: str):
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for user in reader:
            db.execute(
                """
                INSERT INTO users (username, password) VALUES (?, ?)
                ON CONFLICT (username)
                DO UPDATE SET password = excluded.password
                """,
                (user["username"], generate_password_hash(user["password"])),
            )


def validate_json(data):
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "text": {"type": "string"},
                        "image": {"type": "string"},
                        "end": {"type": "boolean"},
                        "selection": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "nextId": {
                                        "oneOf": [
                                            {"type": "integer"},
                                            {
                                                "type": "array",
                                                "items": {"type": "integer"},
                                                "minItems": 1,
                                            },
                                        ]
                                    },
                                    "text": {"type": "string"},
                                },
                                "required": ["text", "nextId"],
                            },
                            "minItems": 0,
                        },
                    },
                    "required": ["id", "text", "selection"],
                    "if": {"properties": {"end": {"const": False}}},
                    "then": {"properties": {"selection": {"minItems": 1}}},
                },
            },
        },
        "required": ["title", "description", "scenes"],
    }
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        print(f"ValidationError: {e.message}")
        raise e
    except SchemaError as e:
        print(f"SchemaError: {e.message}")
        raise e


@transact(app.config["ARGS"].database)
def import_scenario(db: sqlite3.Connection, scenario_json):
    with open(scenario_json, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)
    validate_json(scenario_data)
    cursor = db.cursor()

    # 既存のシーンと選択肢を削除
    existing_scenario = cursor.execute(
        "SELECT id FROM scenarios WHERE title = ?", (scenario_data["title"],)
    ).fetchone()
    if existing_scenario:
        cursor.execute(
            """
            DELETE FROM next_scenes WHERE selection_id IN
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

        for selection in scene["selection"]:
            next_ids = selection["nextId"]
            if isinstance(selection["nextId"], int):
                next_ids = [next_ids]

            cursor.execute(
                "INSERT INTO selections (scene_id, text) VALUES (?, ?)",
                (scene_id, selection["text"]),
            )
            selection_id = cursor.lastrowid
            for next_id in next_ids:
                cursor.execute(
                    "INSERT INTO next_scenes (selection_id, next_id) VALUES (?, ?)",
                    (selection_id, next_id),
                )
    cursor.close()

    return scenario_data["title"]


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("scenario_list"))
    return redirect(url_for("login"))


@app.route("/admin/login", methods=["GET", "POST"])
@transact(app.config["ARGS"].database)
def admin_login(db: sqlite3.Connection):
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        admin = db.execute(
            "SELECT * FROM admins WHERE username = ?", (username,)
        ).fetchone()

        if admin and check_password_hash(admin["password"], password):
            session["admin_id"] = admin["id"]
            return redirect(url_for("admin"))

        flash("Invalid username or password!", "alert")

    return render_template("login.html", admin=True)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
@transact(app.config["ARGS"].database)
def admin(db: sqlite3.Connection):
    users = db.execute("SELECT id, username FROM users ORDER BY id").fetchall()
    return render_template("admin.html", users=users)


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
@transact(app.config["ARGS"].database)
def user_list(db: sqlite3.Connection):
    if request.method == "POST":
        try:
            files = request.files.getlist("files[]")
            files = [file for file in files if file.filename.endswith(".csv")]
            if not files:
                flash("No CSV files were uploaded!", "alert")
            for file in files:
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
                file.save(filepath)
                register_from_csv(filepath)
                os.remove(filepath)
                flash("User registration successful!", "success")
        except Exception:
            flash("User registration failed!", "error")

    users = db.execute("SELECT id, username FROM users ORDER BY id").fetchall()
    return render_template("user_list.html", users=users)


@app.route("/admin/scenarios", methods=["GET", "POST"])
@admin_required
@transact(app.config["ARGS"].database)
def scenarios(db: sqlite3.Connection):
    if request.method == "POST":
        try:
            files = request.files.getlist("files[]")
            files = [file for file in files if file.filename.endswith(".json")]
            if not files:
                flash("No JSON files were uploaded!", "alert")
            for file in files:
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
                file.save(filepath)
                title = import_scenario(filepath)
                os.remove(filepath)
                flash(f"Scenario ({title}) registration successful!", "success")
        except Exception:
            flash("Scenario registration failed!", "error")

    scenarios = db.execute(
        """
        SELECT s.*,
        COUNT(CASE WHEN p.is_completed = 1 THEN 1 END) AS completed_users,
        COUNT(CASE WHEN p.is_completed = 0 THEN 1 END) AS uncompleted_users,
        (SELECT COUNT(*) FROM users) AS total_users
        FROM scenarios s
        LEFT JOIN play_history p ON s.id = p.scenario_id
        GROUP BY s.id
        ORDER BY s.id
        """
    ).fetchall()
    return render_template("scenario_list.html", scenarios=scenarios, admin=True)


@app.before_request
def handle_flash_message():
    if "flash_message" in session:
        message = session.pop("flash_message")
        flash(message["text"], message["type"])


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
@transact(app.config["ARGS"].database)
def change_user_password(db: sqlite3.Connection, user_id):
    data = request.get_json()
    new_password = data.get("password")
    error_type = data.get("error")

    if error_type == "passwords_mismatch":
        session["flash_message"] = {
            "type": "error",
            "text": "Passwords do not match!",
        }
        return jsonify({"message": "Passwords do not match"}), 400

    if not new_password:
        session["flash_message"] = {
            "type": "error",
            "text": "Password is required!",
        }
        return jsonify({"error": "Password is required"}), 400

    try:
        db.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
        # セッションに一時的なメッセージを保存
        session["flash_message"] = {
            "type": "success",
            "text": "Password updated successfully!",
        }
        return jsonify({"message": "Password updated successfully"})
    except Exception as e:
        db.rollback()
        session["flash_message"] = {
            "type": "error",
            "text": "Password update failed!",
        }
        return jsonify({"error": str(e)}), 500


@app.route("/admin/users/<int:user_id>")
@admin_required
@transact(app.config["ARGS"].database)
def user_info(db: sqlite3.Connection, user_id):
    user = db.execute(
        "SELECT id, username FROM users WHERE id= ?", (user_id,)
    ).fetchone()
    ended_scenarios = db.execute(
        """
        SELECT s.*, ph.current_scene_id, ph.is_completed,
            (SELECT scene_id FROM scenes WHERE scenario_id = s.id ORDER BY scene_id LIMIT 1) as first_scene_id
        FROM scenarios s
        LEFT JOIN play_history ph ON s.id = ph.scenario_id AND ph.is_completed AND ph.user_id = ?
        """,
        (user_id,),
    ).fetchall()

    return render_template("scenario_list.html", scenarios=ended_scenarios, user=user)


@app.route("/admin/users/<int:user_id>/<int:scenario_id>")
@admin_required
@transact(app.config["ARGS"].database)
def user_review(db: sqlite3.Connection, user_id, scenario_id):
    user = db.execute(
        "SELECT id, username FROM users WHERE id= ?", (user_id,)
    ).fetchone()

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
        (user_id, scenario_id),
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
        user=user,
    )


@app.route("/register", methods=["GET", "POST"])
@transact(app.config["ARGS"].database)
def register(db: sqlite3.Connection):
    if not app.config["ARGS"].registrable:
        abort(404)
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        try:
            db.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            flash("Registration successful!", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists!", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@transact(app.config["ARGS"].database)
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

        flash("Invalid username or password!", "alert")

    return render_template("login.html", registrable=app.config["ARGS"].registrable)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/scenarios")
@login_required
@transact(app.config["ARGS"].database)
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


@app.route(f"/{app.config['IMAGE_BASE']}/<path:path>")
@login_required
def send_image(path):
    return send_from_directory(app.config["IMAGE_FOLDER"], path)


@app.route("/play/<int:scenario_id>/start")
@login_required
@transact(app.config["ARGS"].database)
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
        flash("Scenario not found!", "error")
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
@transact(app.config["ARGS"].database)
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
@transact(app.config["ARGS"].database)
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
        flash("Invalid selection!", "alert")
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
    next_ids = db.execute(
        "SELECT next_id FROM next_scenes WHERE selection_id = ?", (selection_id,)
    ).fetchall()
    next_ids = list(map(lambda x: x["next_id"], next_ids))
    next_id = random.choice(next_ids)
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
@transact(app.config["ARGS"].database)
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
@transact(app.config["ARGS"].database)
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


def main():
    init_db()
    if app.config["ARGS"].admin:
        try:
            admin_register_from_csv(app.config["ARGS"].admin)
            print("Admin registration successful.")
        except Exception:
            print("Admin registration failed.")
    if app.config["ARGS"].register:
        try:
            register_from_csv(app.config["ARGS"].register)
            print("User registration successful.")
        except Exception:
            print("User registration failed.")
    for scenario_json in app.config["ARGS"].scenarios:
        try:
            title = import_scenario(scenario_json)
            print(f"Imported scenario: {title}")
        except Exception:
            print(f"Import scenario failed: {scenario_json}")

    app.run(host="0.0.0.0", port=app.config["ARGS"].port, debug=app.config["DEBUG"])


if __name__ == "__main__":
    main()
