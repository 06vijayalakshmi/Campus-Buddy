from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
from functools import wraps
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Change this before deploying the project publicly.
app.secret_key = "campusbuddy-secret-key"

DATABASE = "campusbuddy.db"


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db()

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            branch TEXT DEFAULT 'CSE',
            year INTEGER DEFAULT 1,
            bio TEXT DEFAULT '',
            teach_skills TEXT DEFAULT '',
            learn_skills TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            deadline TEXT NOT NULL,
            importance TEXT NOT NULL DEFAULT 'Medium',
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            skill TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(sender_id, receiver_id, skill),

            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        );
    """)

    connection.commit()
    connection.close()


# --------------------------------------------------
# USER HELPERS
# --------------------------------------------------

def get_current_user():
    if "user_id" not in session:
        return None

    connection = get_db()

    user = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    connection.close()

    return user


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if not get_current_user():
            return redirect("/login")

        return function(*args, **kwargs)

    return wrapper


# --------------------------------------------------
# TASK PRIORITY
# --------------------------------------------------

def calculate_priority(task):

    importance_score = {
        "High": 3,
        "Medium": 2,
        "Low": 1
    }

    score = importance_score.get(
        task["importance"],
        1
    )

    try:
        deadline = datetime.strptime(
            task["deadline"],
            "%Y-%m-%d"
        ).date()

        days_left = (
            deadline - date.today()
        ).days

        if days_left <= 0:
            score += 3

        elif days_left == 1:
            score += 2

        else:
            score += 1

    except ValueError:
        pass

    return score


# --------------------------------------------------
# SKILLS
# --------------------------------------------------

def split_skills(skills):

    return [
        skill.strip()
        for skill in (skills or "").split(",")
        if skill.strip()
    ]


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():

    if get_current_user():
        return redirect("/dashboard")

    return render_template(
        "index.html",
        page="landing",
        user=None
    )


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if get_current_user():
        return redirect("/dashboard")

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        branch = request.form.get(
            "branch",
            "CSE"
        )

        year = request.form.get(
            "year",
            "1"
        )

        if not name or not email or len(password) < 6:

            return render_template(
                "index.html",
                page="register",
                user=None,
                error="Please enter all details and use a password with at least 6 characters."
            )

        connection = get_db()

        try:

            cursor = connection.execute(
                """
                INSERT INTO users
                (name, email, password, branch, year)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    generate_password_hash(password),
                    branch,
                    int(year)
                )
            )

            connection.commit()

            session["user_id"] = cursor.lastrowid

        except sqlite3.IntegrityError:

            connection.close()

            return render_template(
                "index.html",
                page="register",
                user=None,
                error="An account with this email already exists."
            )

        connection.close()

        return redirect("/dashboard")

    return render_template(
        "index.html",
        page="register",
        user=None
    )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if get_current_user():
        return redirect("/dashboard")

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        connection = get_db()

        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        connection.close()

        if not user or not check_password_hash(
            user["password"],
            password
        ):

            return render_template(
                "index.html",
                page="login",
                user=None,
                error="Invalid email or password."
            )

        session["user_id"] = user["id"]

        return redirect("/dashboard")

    return render_template(
        "index.html",
        page="login",
        user=None
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    user = get_current_user()

    connection = get_db()

    tasks = connection.execute(
        """
        SELECT *
        FROM tasks
        WHERE user_id = ?
        ORDER BY completed, deadline
        """,
        (user["id"],)
    ).fetchall()

    pending_requests = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM requests
        WHERE receiver_id = ?
        AND status = 'Pending'
        """,
        (user["id"],)
    ).fetchone()["total"]

    connection.close()

    task_list = []

    for task in tasks:

        task_data = dict(task)

        task_data["score"] = calculate_priority(task)

        task_list.append(task_data)

    open_tasks = [
        task
        for task in task_list
        if not task["completed"]
    ]

    open_tasks.sort(
        key=lambda task: (
            -task["score"],
            task["deadline"]
        )
    )

    top_task = (
        open_tasks[0]
        if open_tasks
        else None
    )

    completed = sum(
        task["completed"]
        for task in task_list
    )

    progress = (
        round(
            completed / len(task_list) * 100
        )
        if task_list
        else 0
    )

    return render_template(
        "index.html",
        page="dashboard",
        user=user,
        tasks=task_list,
        top_task=top_task,
        progress=progress,
        pending_requests=pending_requests
    )


# --------------------------------------------------
# ADD TASK
# --------------------------------------------------

@app.route("/tasks/add", methods=["POST"])
@login_required
def add_task():

    title = request.form["title"].strip()

    deadline = request.form["deadline"]

    importance = request.form.get(
        "importance",
        "Medium"
    )

    if title and deadline:

        connection = get_db()

        connection.execute(
            """
            INSERT INTO tasks
            (user_id, title, deadline, importance)
            VALUES (?, ?, ?, ?)
            """,
            (
                session["user_id"],
                title,
                deadline,
                importance
            )
        )

        connection.commit()
        connection.close()

    return redirect("/dashboard")


# --------------------------------------------------
# COMPLETE / UNCOMPLETE TASK
# --------------------------------------------------

@app.route(
    "/tasks/<int:task_id>/toggle",
    methods=["POST"]
)
@login_required
def toggle_task(task_id):

    connection = get_db()

    connection.execute(
        """
        UPDATE tasks
        SET completed =
            CASE completed
                WHEN 0 THEN 1
                ELSE 0
            END
        WHERE id = ?
        AND user_id = ?
        """,
        (
            task_id,
            session["user_id"]
        )
    )

    connection.commit()
    connection.close()

    return redirect("/dashboard")


# --------------------------------------------------
# DELETE TASK
# --------------------------------------------------

@app.route(
    "/tasks/<int:task_id>/delete",
    methods=["POST"]
)
@login_required
def delete_task(task_id):

    connection = get_db()

    connection.execute(
        """
        DELETE FROM tasks
        WHERE id = ?
        AND user_id = ?
        """,
        (
            task_id,
            session["user_id"]
        )
    )

    connection.commit()
    connection.close()

    return redirect("/dashboard")


# --------------------------------------------------
# MY SKILLS
# --------------------------------------------------

@app.route("/skills", methods=["GET", "POST"])
@login_required
def skills():

    user = get_current_user()

    if request.method == "POST":

        teach_skills = request.form.get(
            "teach_skills",
            ""
        )

        learn_skills = request.form.get(
            "learn_skills",
            ""
        )

        connection = get_db()

        connection.execute(
            """
            UPDATE users
            SET teach_skills = ?,
                learn_skills = ?
            WHERE id = ?
            """,
            (
                teach_skills,
                learn_skills,
                user["id"]
            )
        )

        connection.commit()
        connection.close()

        return redirect("/skills")

    return render_template(
        "index.html",
        page="skills",
        user=user
    )


# --------------------------------------------------
# SKILL MATCHING
# --------------------------------------------------

@app.route("/matches")
@login_required
def matches():

    user = get_current_user()

    wanted_skills = {
        skill.lower()
        for skill in split_skills(
            user["learn_skills"]
        )
    }

    if not wanted_skills:

        return render_template(
            "index.html",
            page="matches",
            user=user,
            matches=[]
        )

    connection = get_db()

    other_users = connection.execute(
        """
        SELECT *
        FROM users
        WHERE id != ?
        """,
        (user["id"],)
    ).fetchall()

    connection.close()

    matches = []

    for other_user in other_users:

        teaching = split_skills(
            other_user["teach_skills"]
        )

        matched_skills = [
            skill
            for skill in teaching
            if skill.lower() in wanted_skills
        ]

        if matched_skills:

            score = min(
                99,
                70 + len(matched_skills) * 10
            )

            matches.append({
                "id": other_user["id"],
                "name": other_user["name"],
                "branch": other_user["branch"],
                "year": other_user["year"],
                "bio": other_user["bio"],
                "skills": matched_skills,
                "score": score
            })

    matches.sort(
        key=lambda item: -item["score"]
    )

    return render_template(
        "index.html",
        page="matches",
        user=user,
        matches=matches
    )


# --------------------------------------------------
# SEND SKILL REQUEST
# --------------------------------------------------

@app.route(
    "/request/<int:receiver_id>/<skill>",
    methods=["POST"]
)
@login_required
def send_request(receiver_id, skill):

    if receiver_id == session["user_id"]:
        return redirect("/matches")

    connection = get_db()

    connection.execute(
        """
        INSERT OR IGNORE INTO requests
        (sender_id, receiver_id, skill)
        VALUES (?, ?, ?)
        """,
        (
            session["user_id"],
            receiver_id,
            skill
        )
    )

    connection.commit()
    connection.close()

    return redirect("/matches")


# --------------------------------------------------
# REQUESTS
# --------------------------------------------------

@app.route(
    "/requests",
    methods=["GET", "POST"]
)
@login_required
def requests_page():

    user = get_current_user()

    connection = get_db()

    if request.method == "POST":

        request_id = request.form["request_id"]

        status = request.form["status"]

        if status in (
            "Accepted",
            "Declined"
        ):

            connection.execute(
                """
                UPDATE requests
                SET status = ?
                WHERE id = ?
                AND receiver_id = ?
                """,
                (
                    status,
                    request_id,
                    user["id"]
                )
            )

            connection.commit()

    incoming = connection.execute(
        """
        SELECT
            r.*,
            u.name AS sender_name,
            u.branch AS sender_branch
        FROM requests r
        JOIN users u
            ON u.id = r.sender_id
        WHERE r.receiver_id = ?
        ORDER BY r.created_at DESC
        """,
        (user["id"],)
    ).fetchall()

    outgoing = connection.execute(
        """
        SELECT
            r.*,
            u.name AS receiver_name
        FROM requests r
        JOIN users u
            ON u.id = r.receiver_id
        WHERE r.sender_id = ?
        ORDER BY r.created_at DESC
        """,
        (user["id"],)
    ).fetchall()

    connection.close()

    return render_template(
        "index.html",
        page="requests",
        user=user,
        incoming=incoming,
        outgoing=outgoing
    )


# --------------------------------------------------
# PROFILE
# --------------------------------------------------

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():

    user = get_current_user()

    if request.method == "POST":

        name = request.form["name"].strip()

        branch = request.form["branch"]

        year = int(request.form["year"])

        bio = request.form.get(
            "bio",
            ""
        ).strip()

        connection = get_db()

        connection.execute(
            """
            UPDATE users
            SET name = ?,
                branch = ?,
                year = ?,
                bio = ?
            WHERE id = ?
            """,
            (
                name,
                branch,
                year,
                bio,
                user["id"]
            )
        )

        connection.commit()
        connection.close()

        return redirect("/profile")

    return render_template(
        "index.html",
        page="profile",
        user=user
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/api/health")
def health():

    return jsonify({
        "status": "ok",
        "application": "CampusBuddy"
    })


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    init_db()

    app.run(
        debug=True
    )