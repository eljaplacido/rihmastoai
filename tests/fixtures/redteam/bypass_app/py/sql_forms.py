"""SQL built from data in shapes a constant-template test does not see."""

import pandas as pd
from sqlalchemy import text

FIND_USER = "SELECT id, email FROM users WHERE name = '%s'"
FIND_BY = "SELECT id, email FROM users WHERE name = '{}'"
BASE = "SELECT id, email FROM users"


def _q(name):
    return f"SELECT id FROM users WHERE name = '{name}'"


def constant_template(con, name):
    return con.execute(FIND_USER % name)  # seeded: RT-PY-SQL


def constant_format(con, name):
    return con.execute(FIND_BY.format(name))  # seeded: RT-PY-SQL


def alchemy(session, name):
    return session.execute(text(f"SELECT id FROM users WHERE name = '{name}'"))  # seeded: RT-PY-SQL


def frames(con, region):
    return pd.read_sql(f"SELECT * FROM sales WHERE region = '{region}'", con)  # seeded: RT-PY-SQL


def django(user_model, q):
    return user_model.objects.raw(f"SELECT * FROM auth_user WHERE username LIKE '%{q}%'")  # seeded: RT-PY-SQL


def helper(cur, name):
    return cur.execute(_q(name))  # seeded: RT-PY-SQL


def keywords_in_constant(cur, name):
    return cur.execute(f"{BASE} WHERE name = '{name}'")  # seeded: RT-PY-SQL


def joined(cur, name):
    return cur.execute(" ".join(["SELECT id FROM users WHERE name =", name]))  # seeded: RT-PY-SQL
