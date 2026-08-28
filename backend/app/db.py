"""SQLite 连接与依赖。"""
import sqlite3

from .config import DB_PATH


def connect() -> sqlite3.Connection:
    # check_same_thread=False：FastAPI 同步依赖/端点跑在线程池，建立与销毁可能不在同一线程；
    # 每请求独占一个连接、不跨请求共享，故关闭线程校验是安全的。
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def get_db():
    """FastAPI 依赖：每请求一个连接。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
