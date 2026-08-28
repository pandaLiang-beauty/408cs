"""强化池的间隔重复调度：答对逐级拉长间隔、永不毕业。"""
from datetime import datetime, timezone, timedelta

LADDER = [0, 1, 2, 4, 8, 16, 32, 64, 128]  # 间隔天数阶梯


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def due_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def hours_ago_iso(h: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def update(conn, qid: int, result: str) -> None:
    """result ∈ {correct, fuzzy, wrong}。correct 推远一档；wrong 清零；fuzzy 原地略缩。首次仅错/模糊入池。"""
    row = conn.execute('SELECT level FROM review_schedule WHERE question_id=?', (qid,)).fetchone()
    if row is None:
        if result == 'correct':
            return
        level = 0 if result == 'wrong' else 1
        conn.execute(
            'INSERT INTO review_schedule(question_id,level,due_at,last_result,reps,updated_at)'
            ' VALUES(?,?,?,?,1,?)',
            (qid, level, due_iso(LADDER[level]), result, now_iso()),
        )
        return
    level = row['level']
    if result == 'correct':
        level = min(level + 1, len(LADDER) - 1)
    elif result == 'wrong':
        level = 0
    days = LADDER[level] if result != 'fuzzy' else max(1, LADDER[level] // 2)
    conn.execute(
        'UPDATE review_schedule SET level=?,due_at=?,last_result=?,reps=reps+1,updated_at=?'
        ' WHERE question_id=?',
        (level, due_iso(days), result, now_iso(), qid),
    )


def verdict_to_result(is_correct: int, fuzzy: int) -> str:
    if is_correct and not fuzzy:
        return 'correct'
    if is_correct:
        return 'fuzzy'
    return 'wrong'


CLEAR_K = 2  # 同一知识点连续做对 CLEAR_K 道不同题，才把间隔拉长一档（“做对多道才算掌握”）


def split_tags(raw: str):
    import re
    return [t.strip() for t in re.split(r'[,，、|]', raw or '') if t.strip()]


def update_point(conn, tag: str, result: str) -> None:
    """按知识点更新强化调度。做错/模糊才入池；做对累计 streak，够 CLEAR_K 才升级(间隔拉长)、永不毕业。"""
    if not tag:
        return
    row = conn.execute('SELECT level, streak FROM point_schedule WHERE tag=?', (tag,)).fetchone()
    if row is None:
        if result == 'correct':
            return  # 没做错过的知识点不入池
        level = 0 if result == 'wrong' else 1
        conn.execute(
            'INSERT INTO point_schedule(tag,level,due_at,streak,last_result,reps,updated_at)'
            ' VALUES(?,?,?,0,?,1,?)',
            (tag, level, due_iso(LADDER[level]), result, now_iso()),
        )
        return
    level, streak = row['level'], row['streak']
    if result == 'correct':
        streak += 1
        if streak >= CLEAR_K:
            level = min(level + 1, len(LADDER) - 1)
            streak = 0
        days = LADDER[level]
    elif result == 'wrong':
        level, streak, days = 0, 0, LADDER[0]
    else:  # fuzzy
        streak = 0
        days = max(1, LADDER[level] // 2)
    conn.execute(
        'UPDATE point_schedule SET level=?,due_at=?,streak=?,last_result=?,reps=reps+1,updated_at=?'
        ' WHERE tag=?',
        (level, due_iso(days), streak, result, now_iso(), tag),
    )
