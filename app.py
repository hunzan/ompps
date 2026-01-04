from __future__ import annotations

import os
import sqlite3
import re
from datetime import datetime
from io import BytesIO
from secrets import randbelow

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_file, session, jsonify
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "ompps.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

# ---------- DB ----------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS objectives (
                workspace_id INTEGER PRIMARY KEY,
                target_date TEXT NOT NULL,
                teaching_goal TEXT NOT NULL,
                category TEXT NOT NULL,              -- "定向" or "生活"
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS long_term_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                long_term_goal TEXT NOT NULL,
                ord INTEGER NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS short_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                ord INTEGER NOT NULL,
                FOREIGN KEY (group_id) REFERENCES long_term_groups(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                teach_date TEXT NOT NULL,
                teach_time TEXT NOT NULL,
                effectiveness TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            """
        )

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_ymd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def make_code() -> str:
    # 6 位數碼，避免太長；如重複就重生
    return f"{randbelow(1_000_000):06d}"


def create_workspace() -> sqlite3.Row:
    with get_conn() as conn:
        code = make_code()
        # 避免碰撞
        while conn.execute("SELECT 1 FROM workspaces WHERE code=?", (code,)).fetchone():
            code = make_code()

        conn.execute(
            "INSERT INTO workspaces(code, created_at) VALUES(?, ?)",
            (code, now_iso())
        )
        ws = conn.execute("SELECT * FROM workspaces WHERE code=?", (code,)).fetchone()
        return ws

def get_workspace_by_code(code: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM workspaces WHERE code=?", (code,)).fetchone()

def get_objectives(ws_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM objectives WHERE workspace_id=?", (ws_id,)).fetchone()

def get_records(ws_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM records WHERE workspace_id=? ORDER BY created_at ASC, id ASC",
            (ws_id,)
        ).fetchall()

def get_long_term_groups(ws_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM long_term_groups WHERE workspace_id=? ORDER BY ord ASC, id ASC",
            (ws_id,)
        ).fetchall()

def get_short_terms_by_group_ids(group_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    if not group_ids:
        return {}
    placeholders = ",".join(["?"] * len(group_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM short_terms
            WHERE group_id IN ({placeholders})
            ORDER BY group_id ASC, ord ASC, id ASC
            """,
            tuple(group_ids)
        ).fetchall()
    out: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        out.setdefault(r["group_id"], []).append(r)
    return out

init_db()

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/new/<module>")
def new_module(module: str):
    if module not in ("objectives", "records"):
        return redirect(url_for("home"))

    ws = create_workspace()
    session["last_code"] = ws["code"]
    session["code_ack"] = False

    # 建立 objectives 預設資料 + 預設一組長期目標群組
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO objectives(workspace_id, target_date, teaching_goal, category)
            VALUES(?, ?, ?, ?)
            """,
            (ws["id"], today_ymd(), "", "定向")
        )
        conn.execute(
            """
            INSERT INTO long_term_groups(workspace_id, long_term_goal, ord)
            VALUES(?, ?, ?)
            """,
            (ws["id"], "感官知覺/動作能力", 1)
        )

    flash(f"已建立新草稿，代碼：{ws['code']}（請記下來方便「繼續未完成」）")

    if module == "objectives":
        return redirect(url_for("objectives", code=ws["code"]))
    return redirect(url_for("records", code=ws["code"]))

@app.route("/continue/<module>", methods=["GET", "POST"])
def continue_module(module: str):
    if module not in ("objectives", "records"):
        return redirect(url_for("home"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        ws = get_workspace_by_code(code)
        if not ws:
            flash("找不到這個代碼，請確認後再試一次。")
            return render_template("code.html", module=module)
        if module == "objectives":
            return redirect(url_for("objectives", code=code))
        return redirect(url_for("records", code=code))

    return render_template("code.html", module=module)


@app.route("/objectives/<code>", methods=["GET", "POST"])
def objectives(code: str):
    ws = get_workspace_by_code(code)
    if not ws:
        flash("找不到這個代碼。")
        return redirect(url_for("home"))

    ws_id = ws["id"]
    obj = get_objectives(ws_id)

    if request.method == "POST":
        target_date = (request.form.get("target_date") or today_ymd()).strip()
        teaching_goal = (request.form.get("teaching_goal") or "").strip()
        category = (request.form.get("category") or "定向").strip()
        if category not in ("定向", "生活"):
            category = "定向"

        # 解析多個長期目標群組：long_term_goal_0, long_term_goal_1, ...
        group_idxs = []
        for k in request.form.keys():
            m = re.match(r"^long_term_goal_(\d+)$", k)
            if m:
                group_idxs.append(int(m.group(1)))
        group_idxs = sorted(set(group_idxs))

        if not group_idxs:
            flash("至少需要一個長期目標。")
            return redirect(url_for("objectives", code=code))

        groups_payload = []
        for idx in group_idxs:
            lt = (request.form.get(f"long_term_goal_{idx}") or "").strip()
            if not lt:
                continue
            sts = request.form.getlist(f"short_term_{idx}[]")
            sts = [s.strip() for s in sts if s.strip()]
            groups_payload.append((lt, sts))

        if not groups_payload:
            flash("長期目標不可全空白。")
            return redirect(url_for("objectives", code=code))

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO objectives(workspace_id, target_date, teaching_goal, category)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                  target_date=excluded.target_date,
                  teaching_goal=excluded.teaching_goal,
                  category=excluded.category
                """,
                (ws_id, target_date, teaching_goal, category)
            )

            # 清掉舊群組與短期目標（foreign key cascade 會清 short_terms）
            conn.execute("DELETE FROM long_term_groups WHERE workspace_id=?", (ws_id,))

            # 重建群組 + 其短期目標
            for ord_idx, (lt, sts) in enumerate(groups_payload, start=1):
                cur = conn.execute(
                    "INSERT INTO long_term_groups(workspace_id, long_term_goal, ord) VALUES(?, ?, ?)",
                    (ws_id, lt, ord_idx)
                )
                group_id = cur.lastrowid
                for st_ord, item in enumerate(sts, start=1):
                    conn.execute(
                        "INSERT INTO short_terms(group_id, item, ord) VALUES(?, ?, ?)",
                        (group_id, item, st_ord)
                    )

        flash("已儲存：教學目標（含多組長期/短期目標）")
        return redirect(url_for("objectives", code=code))

    # GET：拉群組與各群組短期目標
    groups = get_long_term_groups(ws_id)
    st_map = get_short_terms_by_group_ids([g["id"] for g in groups])

    return render_template(
        "objectives.html",
        code=code,
        obj=obj,
        groups=groups,
        st_map=st_map
    )


@app.route("/records/<code>", methods=["GET", "POST"])
def records(code: str):
    ws = get_workspace_by_code(code)
    if not ws:
        flash("找不到這個代碼。")
        return redirect(url_for("home"))

    ws_id = ws["id"]

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "add":
            teach_date = (request.form.get("teach_date") or today_ymd()).strip()
            teach_time = (request.form.get("teach_time") or "").strip()
            effectiveness = (request.form.get("effectiveness") or "").strip()

            if not teach_time:
                flash("教學時間不可空白（例如：14:00-16:00）。")
                return redirect(url_for("records", code=code))

            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO records(workspace_id, teach_date, teach_time, effectiveness, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (ws_id, teach_date, teach_time, effectiveness, now_iso())
                )
            flash("已新增一筆教學記錄。")
            return redirect(url_for("records", code=code))

        if action == "delete":
            rec_id = (request.form.get("rec_id") or "").strip()
            if rec_id.isdigit():
                with get_conn() as conn:
                    conn.execute(
                        "DELETE FROM records WHERE id=? AND workspace_id=?",
                        (int(rec_id), ws_id)
                    )
                flash("已刪除該筆記錄。")
            return redirect(url_for("records", code=code))

    recs = get_records(ws_id)
    return render_template("records.html", code=code, records=recs, today=today_ymd())


def build_export_text(ws_id: int) -> str:
    groups = get_long_term_groups(ws_id)
    st_map = get_short_terms_by_group_ids([g["id"] for g in groups])
    recs = get_records(ws_id)

    lines: list[str] = []

    # 教學目標
    lines.append("教學目標：")
    if groups:
        for i, g in enumerate(groups, start=1):
            lines.append(f"長期目標{i}. {g['long_term_goal']}")
            sts = st_map.get(g["id"], [])
            if sts:
                for j, st in enumerate(sts, start=1):
                    lines.append(f"  短期目標{j}. {st['item']}")
            else:
                lines.append("  （未填短期目標）")
            lines.append("")
    else:
        lines.append("（未填）")

    # 教學記錄
    lines.append("【教學記錄】")
    if not recs:
        lines.append("（尚未新增）")
    else:
        for idx, r in enumerate(recs, start=1):
            lines.append(f"第{idx}次")
            lines.append(f"教學日期：{r['teach_date']}")
            lines.append(f"教學時間：{r['teach_time']}")
            lines.append("教學成效評估：")
            lines.append(r["effectiveness"] or "")
            lines.append("")  # 分隔

    # 收尾空行
    lines.append("")
    return "\n".join(lines)


@app.route("/export/<code>")
def export(code: str):
    ws = get_workspace_by_code(code)
    if not ws:
        flash("找不到這個代碼。")
        return redirect(url_for("home"))

    ws_id = ws["id"]
    obj = get_objectives(ws_id)
    date_for_name = obj["target_date"] if obj else today_ymd()
    ymd = date_for_name.replace("-", "")

    filename = f"{ymd}_教學記錄_代碼{ws['code']}.txt"
    text = build_export_text(ws_id).encode("utf-8-sig")  # utf-8-sig 讓 Windows 記事本不亂碼

    return send_file(
        BytesIO(text),
        as_attachment=True,
        download_name=filename,
        mimetype="text/plain; charset=utf-8"
    )

@app.route("/ack-code", methods=["POST"])
def ack_code():
    # 使用者按下「我已記下」後，解除強制 modal
    session["code_ack"] = True
    # 你也可以選擇保留 last_code 不清，讓之後仍可在右上角看到
    # 若你想按一次就不再顯示、也不再提示，可以清掉 last_code：
    # session.pop("last_code", None)
    return jsonify({"ok": True})

@app.post("/api/delete-workspace")
def api_delete_workspace():
    code = (request.form.get("code") or request.json.get("code") if request.is_json else "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    with get_conn() as conn:
        ws = conn.execute("SELECT id FROM workspaces WHERE code=?", (code,)).fetchone()
        if not ws:
            return jsonify({"ok": False, "error": "not found"}), 404

        conn.execute("DELETE FROM workspaces WHERE id=?", (ws["id"],))
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
