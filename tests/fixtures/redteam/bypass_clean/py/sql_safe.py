"""Queries whose formatted parts cannot carry data."""

TABLES = {"loans": "loans", "people": "people"}
BASE = "SELECT id, email FROM users"


def placeholders(cur, ids):
    marks = ",".join("?" for _ in ids)
    return cur.execute(f"SELECT id FROM users WHERE id IN ({marks})", ids)


def table_allowlist(cur, kind):
    table = TABLES[kind]
    return cur.execute(f"SELECT COUNT(*) FROM {table}")


def constant_base(cur, name):
    return cur.execute(f"{BASE} WHERE name = ?", (name,))


def log_line(log, name):
    log.execute(f"{name} started")
