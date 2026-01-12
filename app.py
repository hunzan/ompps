from __future__ import annotations

import os
import sqlite3
import re
from datetime import datetime, timedelta
from io import BytesIO
from secrets import randbelow
from urllib.parse import quote

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_file, session, jsonify
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "ompps.db")

RETENTION_DAYS = 60

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

# ---------- DB ----------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def migrate_objectives_table(conn: sqlite3.Connection) -> None:

    # 0️⃣ workspaces 不存在就別搬（防爆）
    ws_tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces';"
    ).fetchone()
    if not ws_tbl:
        return

    # 1️⃣ objectives 不存在就不用搬
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='objectives';"
    ).fetchone()
    if not row:
        return

    cols = conn.execute("PRAGMA table_info(objectives);").fetchall()
    col_names = {c["name"] for c in cols}

    # 判斷是否已經是「複合主鍵」新版：
    # SQLite composite PK 會讓 pk 欄位出現 1,2,...（>=2 代表複合）
    pk_count = sum(1 for c in cols if int(c["pk"]) > 0)
    if pk_count >= 2:
        return  # 已是新版，不搬

    # 舊版通常 workspace_id 是唯一主鍵（pk_count==1 且 workspace_id pk==1）
    ws_pk = next((c for c in cols if c["name"] == "workspace_id"), None)
    if not ws_pk or int(ws_pk["pk"]) != 1:
        return  # 不是我們認得的舊版結構，就別亂搬

    # 這些欄位舊版應該會有（教學日期/文字）
    if "target_date" not in col_names or "teaching_goal" not in col_names:
        return

    # 舊版可能沒有 category 欄位，沒有就補預設 '定向'
    has_category = "category" in col_names

    # 建新表（用 tmp 名，避免重複搬表）
    conn.executescript("""
    DROP TABLE IF EXISTS objectives_new_tmp;

    CREATE TABLE objectives_new_tmp (
      workspace_id INTEGER NOT NULL,
      category TEXT NOT NULL,
      target_date TEXT NOT NULL,
      teaching_goal TEXT NOT NULL,
      PRIMARY KEY (workspace_id, category),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
    );
    """)

    if has_category:
        conn.execute("""
          INSERT OR REPLACE INTO objectives_new_tmp(workspace_id, category, target_date, teaching_goal)
          SELECT o.workspace_id, o.category, o.target_date, o.teaching_goal
          FROM objectives o
          JOIN workspaces w ON w.id = o.workspace_id
        """)
    else:
        conn.execute("""
          INSERT OR REPLACE INTO objectives_new_tmp(workspace_id, category, target_date, teaching_goal)
          SELECT o.workspace_id, '定向', o.target_date, o.teaching_goal
          FROM objectives o
          JOIN workspaces w ON w.id = o.workspace_id
        """)

    # 換表
    conn.executescript("""
    DROP TABLE objectives;
    ALTER TABLE objectives_new_tmp RENAME TO objectives;
    """)

def init_db() -> None:
    with get_conn() as conn:
        # SQLite foreign_keys 是連線層級
        conn.execute("PRAGMA foreign_keys = ON;")

        # 1) 建表（新裝/空 DB 會直接用這套）
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );

            -- objectives： (workspace_id, category) 複合主鍵
            CREATE TABLE IF NOT EXISTS objectives (
              workspace_id INTEGER NOT NULL,
              category TEXT NOT NULL,
              target_date TEXT NOT NULL,
              teaching_goal TEXT NOT NULL,
              PRIMARY KEY (workspace_id, category),
              FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS long_term_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                category TEXT NOT NULL,
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
                category TEXT NOT NULL,
                teach_date TEXT NOT NULL,
                teach_time TEXT NOT NULL,
                effectiveness TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            """
        )

        # 2) workspaces：安全升級補欄位
        for sql in [
            "ALTER TABLE workspaces ADD COLUMN student_name TEXT;",
            "ALTER TABLE workspaces ADD COLUMN agency TEXT;",
            "ALTER TABLE workspaces ADD COLUMN updated_at TEXT;",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        # 3) 舊 DB：long_term_groups / records 補 category 欄位（最穩：先允許 NULL）
        for sql in [
            "ALTER TABLE long_term_groups ADD COLUMN category TEXT;",
            "ALTER TABLE records ADD COLUMN category TEXT;",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        # 4) 補舊資料預設值（避免查不到）
        conn.execute("UPDATE long_term_groups SET category='定向' WHERE category IS NULL OR category='';")
        conn.execute("UPDATE records SET category='定向' WHERE category IS NULL OR category='';")

        # 5) UNIQUE：避免同一學員+單位重複建檔
        try:
            conn.execute("CREATE UNIQUE INDEX ux_student_agency ON workspaces(student_name, agency);")
        except sqlite3.OperationalError:
            pass

        # 6) objectives 搬表（舊版 workspace_id 單一 PK 那種）
        #    搬表會牽涉 FK：最穩做法是搬表時暫關 FK
        conn.execute("PRAGMA foreign_keys = OFF;")
        try:
            migrate_objectives_table(conn)
        finally:
            conn.execute("PRAGMA foreign_keys = ON;")

        for sql in [
            "CREATE INDEX IF NOT EXISTS ix_objectives_ws_cat ON objectives(workspace_id, category);",
            "CREATE INDEX IF NOT EXISTS ix_groups_ws_cat ON long_term_groups(workspace_id, category, ord);",
            "CREATE INDEX IF NOT EXISTS ix_records_ws_cat ON records(workspace_id, category, created_at);",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_ymd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def make_code() -> str:
    # 6 位數碼，避免太長；如重複就重生
    return f"{randbelow(1_000_000):06d}"


def find_workspace_by_student(student_name: str, agency: str) -> sqlite3.Row | None:
    sn = (student_name or "").strip()
    ag = (agency or "").strip()
    if not sn or not ag:
        return None
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM workspaces WHERE student_name=? AND agency=? ORDER BY id DESC LIMIT 1",
            (sn, ag)
        ).fetchone()


def create_workspace(student_name: str, agency: str) -> sqlite3.Row:
    sn = (student_name or "").strip()
    ag = (agency or "").strip()
    if not sn or not ag:
        raise ValueError("student_name/agency required")

    with get_conn() as conn:
        code = make_code()
        while conn.execute("SELECT 1 FROM workspaces WHERE code=?", (code,)).fetchone():
            code = make_code()

        conn.execute(
            "INSERT INTO workspaces(code, created_at, updated_at, student_name, agency) VALUES(?, ?, ?, ?, ?)",
            (code, now_iso(), now_iso(), sn, ag)
        )
        ws = conn.execute("SELECT * FROM workspaces WHERE code=?", (code,)).fetchone()
        return ws

def get_workspace_by_code(code: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM workspaces WHERE code=?", (code,)).fetchone()

def norm_cat(category: str) -> str:
    c = (category or "").strip()
    return c if c in ("定向", "生活") else "定向"

def get_objectives(ws_id: int, category: str) -> sqlite3.Row | None:
    cat = norm_cat(category)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM objectives WHERE workspace_id=? AND category=?",
            (ws_id, cat)
        ).fetchone()


def get_records(ws_id: int, category: str) -> list[sqlite3.Row]:
    cat = norm_cat(category)
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT * FROM records
            WHERE workspace_id=? AND category=?
            ORDER BY created_at ASC, id ASC
            """,
            (ws_id, cat)
        ).fetchall()


def get_long_term_groups(ws_id: int, category: str) -> list[sqlite3.Row]:
    cat = norm_cat(category)
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT * FROM long_term_groups
            WHERE workspace_id=? AND category=?
            ORDER BY ord ASC, id ASC
            """,
            (ws_id, cat)
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

def init_workspace_defaults(ws_id: int) -> None:
    """新建 workspace 後的預設資料：定向/生活 各一筆 objectives + 各一組預設長期目標"""
    with get_conn() as conn:
        # objectives：兩類別各一筆
        for cat in ("定向", "生活"):
            conn.execute(
                """
                INSERT OR IGNORE INTO objectives(workspace_id, category, target_date, teaching_goal)
                VALUES(?, ?, ?, ?)
                """,
                (ws_id, cat, today_ymd(), "")
            )

            # long_term_groups：兩類別各至少一組
            conn.execute(
                """
                INSERT INTO long_term_groups(workspace_id, category, long_term_goal, ord)
                VALUES(?, ?, ?, ?)
                """,
                (ws_id, cat, "感官知覺/動作能力", 1)
            )

def cleanup_expired_workspaces() -> int:
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM workspaces
            WHERE COALESCE(updated_at, created_at) < ?
            """,
            (cutoff,)
        )
    return cur.rowcount

init_db()

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/student", methods=["GET", "POST"])
def student():
    if request.method == "GET":
        nxt = request.args.get("next", "objectives")
        return render_template("student.html", next=nxt)

    nxt = request.form.get("next", "objectives")
    student_name = request.form.get("student_name", "").strip()
    agency = request.form.get("agency", "").strip()

    if not student_name or not agency:
        flash("請填學員姓名與派案單位。")
        return redirect(url_for("student", next=nxt))

    ws = find_workspace_by_student(student_name, agency)

    if not ws:
        try:
            ws = create_workspace(student_name, agency)
            init_workspace_defaults(ws["id"])
        except sqlite3.IntegrityError:
            ws = find_workspace_by_student(student_name, agency)

    # 只在「新建成功」時提示代碼（避免每次進來都跳 modal）
    if session.get("last_code") != ws["code"]:
        session["last_code"] = ws["code"]
        session["code_ack"] = False

    # 導向你原本的頁面
    if nxt == "records":
        return redirect(url_for("records", code=ws["code"]))
    return redirect(url_for("objectives", code=ws["code"]))

@app.route("/new/<module>")
def new_module(module: str):
    if module not in ("objectives", "records"):
        return redirect(url_for("home"))
    return redirect(url_for("student", next=module))

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
    # 用同一個 key：cat（GET/POST 都吃）
    cat = (request.args.get("cat") or request.form.get("cat") or "定向").strip()
    if cat not in ("定向", "生活"):
        cat = "定向"

    ws = get_workspace_by_code(code)
    if not ws:
        flash("找不到這個代碼。")
        return redirect(url_for("home"))

    ws_id = ws["id"]
    obj = get_objectives(ws_id, cat)

    if request.method == "POST":
        target_date = (request.form.get("target_date") or today_ymd()).strip()
        teaching_goal = (request.form.get("teaching_goal") or "").strip()

        # 解析多個長期目標群組：long_term_goal_0, long_term_goal_1, ...
        group_idxs: list[int] = []
        for k in request.form.keys():
            m = re.match(r"^long_term_goal_(\d+)$", k)
            if m:
                group_idxs.append(int(m.group(1)))
        group_idxs = sorted(set(group_idxs))

        if not group_idxs:
            flash("至少需要一個長期目標。")
            return redirect(url_for("objectives", code=code, cat=cat))

        groups_payload: list[tuple[str, list[str]]] = []
        for idx in group_idxs:
            lt = (request.form.get(f"long_term_goal_{idx}") or "").strip()
            if not lt:
                continue
            sts = request.form.getlist(f"short_term_{idx}[]")
            sts = [s.strip() for s in sts if s.strip()]
            groups_payload.append((lt, sts))

        if not groups_payload:
            flash("長期目標不可全空白。")
            return redirect(url_for("objectives", code=code, cat=cat))

        with get_conn() as conn:
            ts = now_iso()

            # objectives：同一個 ws 允許 定向/生活 各一筆
            conn.execute(
                """
                INSERT INTO objectives(workspace_id, category, target_date, teaching_goal)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(workspace_id, category) DO UPDATE SET
                  target_date=excluded.target_date,
                  teaching_goal=excluded.teaching_goal
                """,
                (ws_id, cat, target_date, teaching_goal)
            )

            # ✅ 只清掉本 cat 的群組（一定要在迴圈外）
            conn.execute(
                "DELETE FROM long_term_groups WHERE workspace_id=? AND category=?",
                (ws_id, cat)
            )

            # ✅ 重建群組 + short_terms
            for ord_idx, (lt, sts) in enumerate(groups_payload, start=1):
                cur = conn.execute(
                    """
                    INSERT INTO long_term_groups(workspace_id, category, long_term_goal, ord)
                    VALUES(?, ?, ?, ?)
                    """,
                    (ws_id, cat, lt, ord_idx)
                )
                group_id = cur.lastrowid

                for st_ord, item in enumerate(sts, start=1):
                    conn.execute(
                        "INSERT INTO short_terms(group_id, item, ord) VALUES(?, ?, ?)",
                        (group_id, item, st_ord)
                    )

            conn.execute(
                "UPDATE workspaces SET updated_at=? WHERE id=?",
                (ts, ws_id)
            )

        flash(f"已儲存：教學目標（{cat}）")
        return redirect(url_for("objectives", code=code, cat=cat))

    # GET
    groups = get_long_term_groups(ws_id, cat)
    st_map = get_short_terms_by_group_ids([g["id"] for g in groups])

    return render_template(
        "objectives.html",
        code=code,
        cat=cat,
        ws=ws,
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

    cat = (request.args.get("cat") or request.form.get("cat") or "定向").strip()
    if cat not in ("定向", "生活"):
        cat = "定向"

    ws_id = ws["id"]

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "add":
            teach_date = (request.form.get("teach_date") or today_ymd()).strip()
            teach_time = (request.form.get("teach_time") or "").strip()
            effectiveness = (request.form.get("effectiveness") or "").strip()

            if not teach_time:
                flash("教學時間不可空白（例如：14:00-16:00）。")
                return redirect(url_for("records", code=code, cat=cat))

            ts = now_iso()
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO records(workspace_id, category, teach_date, teach_time, effectiveness, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (ws_id, cat, teach_date, teach_time, effectiveness, ts)
                )
                conn.execute("UPDATE workspaces SET updated_at=? WHERE id=?", (ts, ws_id))

            flash("已新增一筆教學記錄。")
            return redirect(url_for("records", code=code, cat=cat))

        if action == "delete":
            rec_id = (request.form.get("rec_id") or "").strip()
            if rec_id.isdigit():
                with get_conn() as conn:
                    conn.execute(
                        "DELETE FROM records WHERE id=? AND workspace_id=? AND category=?",
                        (int(rec_id), ws_id, cat)
                    )
                flash("已刪除該筆記錄。")

            return redirect(url_for("records", code=code, cat=cat))

    recs = get_records(ws_id, cat)
    return render_template(
        "records.html",
        code=code,
        ws=ws,
        records=recs,
        today=today_ymd(),
        category=cat
    )

def build_export_text(ws_id: int, category: str) -> str:
    lines: list[str] = []

    def one(cat: str):
        obj = get_objectives(ws_id, cat)
        groups = get_long_term_groups(ws_id, cat)
        st_map = get_short_terms_by_group_ids([g["id"] for g in groups])
        recs = get_records(ws_id, cat)

        lines.append(f"【教學目標｜{cat}】")
        if obj:
            lines.append(f"訂定日期：{obj['target_date']}")
            lines.append("教學目標：")
            lines.append(obj["teaching_goal"] or "（未填）")
        else:
            lines.append("（尚未填寫）")
        lines.append("")

        lines.append("長期目標與短期目標：")
        if groups:
            for i, g in enumerate(groups, start=1):
                lines.append(f"長期目標{i}. {g['long_term_goal']}")
                sts = st_map.get(g["id"], [])
                if sts:
                    for j, st in enumerate(sts, start=1):
                        lines.append(f"  {j}. {st['item']}")
                else:
                    lines.append("  （未填短期目標）")
                lines.append("")
        else:
            lines.append("（未填長期/短期目標）")
            lines.append("")

        lines.append(f"【教學記錄｜{cat}】")
        if not recs:
            lines.append("（尚未新增）")
        else:
            for idx, r in enumerate(recs, start=1):
                lines.append(f"第{idx}次")
                lines.append(f"教學日期：{r['teach_date']}")
                lines.append(f"教學時間：{r['teach_time']}")
                lines.append("教學成效評估：")
                lines.append(r["effectiveness"] or "")
                lines.append("")
        lines.append("")
        lines.append("========")
        lines.append("")

    if category == "both":
        one("定向")
        one("生活")
    else:
        one(category)

    return "\n".join(lines)

@app.route("/export/<code>")
def export(code: str):
    ws = get_workspace_by_code(code)
    if not ws:
        flash("找不到這個代碼。")
        return redirect(url_for("home"))

    cat = (request.args.get("category") or "定向").strip()
    if cat not in ("定向", "生活", "both"):
        cat = "定向"

    ws_id = ws["id"]
    # 檔名日期：定向/生活取自己的；both 取「有填的那個」(優先定向，沒有就生活)
    if cat == "both":
        obj_a = get_objectives(ws_id, "定向")
        obj_b = get_objectives(ws_id, "生活")

        dates = []
        if obj_a: dates.append(obj_a["target_date"])
        if obj_b: dates.append(obj_b["target_date"])

        date_for_name = max(dates) if dates else today_ymd()
    else:
        obj = get_objectives(ws_id, cat)
        date_for_name = obj["target_date"] if obj else today_ymd()

    ymd = date_for_name.replace("-", "")

    student = safe_name(ws["student_name"] or "未填姓名")
    filename = f"{ymd}_{student}_{cat}_{ws['code']}.txt"

    text = build_export_text(ws_id, cat).encode("utf-8-sig")
    return send_file(
        BytesIO(text),
        as_attachment=True,
        download_name=filename,
        mimetype="text/plain; charset=utf-8",
    )

def safe_name(s: str) -> str:
    # 讓檔名乾淨（把不適合的字元換掉）
    return "".join(ch if ch.isalnum() or ch in " _-." or "\u4e00" <= ch <= "\u9fff" else "_" for ch in s).strip() or "未填姓名"

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
    data = request.get_json(silent=True) or {}
    code = (request.form.get("code") or data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    with get_conn() as conn:
        ws = conn.execute("SELECT id FROM workspaces WHERE code=?", (code,)).fetchone()
        if not ws:
            return jsonify({"ok": False, "error": "not found"}), 404
        conn.execute("DELETE FROM workspaces WHERE id=?", (ws["id"],))
    return jsonify({"ok": True})

try:
    n = cleanup_expired_workspaces()
    if n:
        print(f"[cleanup] removed {n} workspaces")
except Exception as e:
    print("[cleanup] failed:", e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
