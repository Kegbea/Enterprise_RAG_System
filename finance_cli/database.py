"""数据层：建表、增删查、统计查询"""

import sqlite3

DB_PATH = "data.db"


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（短连接模式）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，首次运行自动建表"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            note TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def add_transaction(amount: float, category: str, date: str, note: str) -> None:
    """添加一条账目"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO transactions (amount, category, date, note) VALUES (?, ?, ?, ?)",
        (amount, category, date, note),
    )
    conn.commit()
    conn.close()


def get_transactions(
    month: str | None = None, categories: list[str] | None = None
) -> list[dict]:
    """查询账目列表，可按月份和分类筛选，按日期降序"""
    conn = _get_conn()
    query = "SELECT * FROM transactions WHERE 1=1"
    params: list = []

    if month:
        query += " AND substr(date, 1, 7) = ?"
        params.append(month)

    if categories:
        placeholders = ",".join(["?"] * len(categories))
        query += f" AND category IN ({placeholders})"
        params.extend(categories)

    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_transaction(tid: int) -> bool:
    """按 ID 删除账目，返回是否删除成功"""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_months() -> list[str]:
    """获取所有有记录的月份，降序排列"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT substr(date, 1, 7) AS m FROM transactions ORDER BY m DESC"
    ).fetchall()
    conn.close()
    return [row["m"] for row in rows]


def get_stats(month: str) -> list[dict]:
    """获取指定月份的分类统计：每个分类的笔数和合计金额"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT category,
                  SUM(amount) AS total,
                  COUNT(*) AS count
           FROM transactions
           WHERE substr(date, 1, 7) = ?
           GROUP BY category
           ORDER BY total DESC""",
        (month,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
