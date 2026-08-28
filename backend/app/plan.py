"""学习排程：只安排「天」，不排钟点。

规则（用户拍板）：
- 一天套卷、一天强化，交替推进。
- 真题从旧到新精做（2009→2023），近三年（2024/2025/2026）留到考前当模考。
- 没做完不清零：过期未完成的任务一直挂着显示为「补做」。
- 自适应：欠账 ≥2 个时，新的一天只排强化，不再压新卷。

只把「到今天为止」的任务落库；往后 7 天是按当前进度算出来的预排（不落库，会自动自我校正）。
"""
from datetime import date, datetime, timedelta
from typing import Optional

WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _d(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def weekday_cn(s: str) -> str:
    return WEEKDAYS[_d(s).weekday()]


def ensure_config(conn) -> dict:
    r = conn.execute('SELECT * FROM plan_config WHERE id=1').fetchone()
    if not r:
        conn.execute('INSERT INTO plan_config(id, start_date) VALUES(1, ?)', (today_str(),))
        conn.commit()
        r = conn.execute('SELECT * FROM plan_config WHERE id=1').fetchone()
    if not r['start_date']:
        conn.execute('UPDATE plan_config SET start_date=? WHERE id=1', (today_str(),))
        conn.commit()
        r = conn.execute('SELECT * FROM plan_config WHERE id=1').fetchone()
    return {'exam_date': r['exam_date'], 'start_date': r['start_date'],
            'mock_years': [int(x) for x in r['mock_years'].split(',') if x.strip()],
            'mock_days': r['mock_days']}


def _pools(conn, cfg):
    years = [r['year'] for r in
             conn.execute("SELECT DISTINCT year FROM questions WHERE source='exam' ORDER BY year")]
    mocks = [y for y in years if y in cfg['mock_years']]
    main = [y for y in years if y not in cfg['mock_years']]
    return main, mocks


def _used_years(conn):
    return {r['ref_year'] for r in
            conn.execute('SELECT DISTINCT ref_year FROM daily_tasks WHERE ref_year IS NOT NULL')}


def _decide(conn, cfg, day: str, prev_kind: str, overdue: int, used: set):
    """给某一天决定任务：返回 (kind, ref_year)。"""
    if overdue >= 2:
        return ('reinforce', None)
    if prev_kind in ('exam', 'mock'):
        return ('reinforce', None)          # 套卷次日必为强化
    main, mocks = _pools(conn, cfg)
    left = (_d(cfg['exam_date']) - _d(day)).days
    if left <= cfg['mock_days']:
        for y in mocks:
            if y not in used:
                return ('mock', y)
    for y in main:
        if y not in used:
            return ('exam', y)
    # 精做卷做完后不提前动模考：中间的日子全用来强化，模考留到考前 mock_days 内
    return ('reinforce', None)


def _prev_kind(conn, day: str) -> str:
    r = conn.execute('SELECT kind FROM daily_tasks WHERE plan_date < ? ORDER BY plan_date DESC, id DESC'
                     ' LIMIT 1', (day,)).fetchone()
    return r['kind'] if r else ''


def _overdue_rows(conn, day: str):
    return conn.execute("SELECT * FROM daily_tasks WHERE plan_date < ? AND status='todo'"
                        ' ORDER BY plan_date', (day,)).fetchall()


def ensure_through_today(conn) -> dict:
    """把 start_date..今天 之间缺失的日子补齐落库（每天一项）。"""
    cfg = ensure_config(conn)
    cur, end = _d(cfg['start_date']), _d(today_str())
    if cur > end:
        cur = end
    while cur <= end:
        day = cur.isoformat()
        if not conn.execute('SELECT 1 FROM daily_tasks WHERE plan_date=?', (day,)).fetchone():
            used = _used_years(conn)
            overdue = len(_overdue_rows(conn, day))
            kind, year = _decide(conn, cfg, day, _prev_kind(conn, day), overdue, used)
            conn.execute('INSERT INTO daily_tasks(plan_date, kind, ref_year) VALUES(?,?,?)',
                         (day, kind, year))
        cur += timedelta(days=1)
    conn.commit()
    return cfg


def refresh_status(conn) -> None:
    """任务是否完成由其绑定的 session 是否已交卷推导，避免两处状态打架。"""
    conn.execute("UPDATE daily_tasks SET status='done' WHERE session_id IS NOT NULL AND status!='done'"
                 " AND session_id IN (SELECT id FROM sessions WHERE status='graded')")
    conn.commit()


def _counts(conn, year):
    r = conn.execute("SELECT SUM(qtype='choice') c, SUM(qtype='subjective') s FROM questions"
                     " WHERE source='exam' AND year=?", (year,)).fetchone()
    return (r['c'] or 0), (r['s'] or 0)


def _due_points(conn) -> int:
    from . import scheduler
    return conn.execute('SELECT COUNT(*) c FROM point_schedule WHERE due_at<=?',
                        (scheduler.now_iso(),)).fetchone()['c']


def describe(conn, kind: str, ref_year) -> dict:
    if kind in ('exam', 'mock'):
        c, s = _counts(conn, ref_year)
        title = f'{ref_year} 年真题' + (' · 全真模考' if kind == 'mock' else '')
        return {'title': title, 'detail': f'整套 {c + s} 题（单选 {c} · 综合 {s}）· 满分 150'}
    due = _due_points(conn)
    return {'title': '强化训练（按知识点）',
            'detail': f'{due} 个到期薄弱知识点 · 同知识点新题穿插原错题' if due
                      else '暂无到期知识点，可自选「练全部薄弱点」'}


def task_public(conn, r) -> dict:
    d = describe(conn, r['kind'], r['ref_year'])
    return {'id': r['id'], 'date': r['plan_date'], 'weekday': weekday_cn(r['plan_date']),
            'kind': r['kind'], 'ref_year': r['ref_year'], 'status': r['status'],
            'session_id': r['session_id'], **d}


def _last_materialized_kind(conn) -> str:
    r = conn.execute('SELECT kind FROM daily_tasks ORDER BY plan_date DESC, id DESC LIMIT 1').fetchone()
    return r['kind'] if r else ''


def simulate_range(conn, cfg, from_d: date, to_d: date) -> list:
    """推算 [from_d, to_d] 每天的任务（不落库）。按当前进度往前滚，会自我校正。"""
    used = set(_used_years(conn))
    prev_kind = _last_materialized_kind(conn)
    overdue = len(_overdue_rows(conn, today_str()))
    out, d = [], from_d
    while d <= to_d:
        s = d.isoformat()
        kind, year = _decide(conn, cfg, s, prev_kind, overdue, used)
        if year:
            used.add(year)
        out.append({'date': s, 'weekday': weekday_cn(s), 'kind': kind, 'ref_year': year,
                    **describe(conn, kind, year)})
        prev_kind = kind
        d += timedelta(days=1)
    return out


def upcoming(conn, cfg, days: int = 7) -> list:
    """未来若干天的预排（不落库；按当前进度推算，会随实际完成情况自我校正）。"""
    t = _d(today_str())
    return simulate_range(conn, cfg, t + timedelta(days=1), t + timedelta(days=days))


def calendar(conn, ym: Optional[str] = None) -> dict:
    """某个月的排程日历：已过去与今天用落库数据，未来用预排。ym 形如 2026-08。"""
    cfg = ensure_through_today(conn)
    refresh_status(conn)
    t = today_str()
    y, m = (int(x) for x in (ym or t[:7]).split('-'))
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)

    days = {}
    for r in conn.execute('SELECT * FROM daily_tasks WHERE plan_date BETWEEN ? AND ? ORDER BY id',
                          (first.isoformat(), last.isoformat())):
        days[r['plan_date']] = {**task_public(conn, r), 'planned': False}
    td = _d(t)
    if last > td:
        # 必须从今天之后连续推算到本月末再筛选，否则跨月时"已用年份"链会断（会重复排同一年）
        for e in simulate_range(conn, cfg, td + timedelta(days=1), last):
            if first <= _d(e['date']) <= last:
                days.setdefault(e['date'], {**e, 'status': 'plan', 'planned': True, 'id': None,
                                            'session_id': None})
    return {'month': f'{y:04d}-{m:02d}', 'first_weekday': first.weekday(),
            'days_in_month': last.day, 'today': t, 'exam_date': cfg['exam_date'],
            'days': [days[k] for k in sorted(days)]}


def view(conn) -> dict:
    """首页排程视图：倒计时 + 今日任务 + 补做 + 未来预排 + 进度。"""
    cfg = ensure_through_today(conn)
    refresh_status(conn)
    t = today_str()
    today_rows = conn.execute('SELECT * FROM daily_tasks WHERE plan_date=? ORDER BY id', (t,)).fetchall()
    overdue_rows = _overdue_rows(conn, t)
    main, mocks = _pools(conn, cfg)
    done_years = {r['ref_year'] for r in conn.execute(
        "SELECT DISTINCT ref_year FROM daily_tasks WHERE status='done' AND ref_year IS NOT NULL")}
    return {
        'exam_date': cfg['exam_date'],
        'days_left': (_d(cfg['exam_date']) - _d(t)).days,
        'today': t, 'weekday': weekday_cn(t),
        'tasks': [task_public(conn, r) for r in today_rows],
        'overdue': [task_public(conn, r) for r in overdue_rows],
        'upcoming': upcoming(conn, cfg),
        'progress': {'papers_total': len(main) + len(mocks), 'papers_done': len(done_years)},
    }
