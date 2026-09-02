"""学习排程：按北京时间 08:00 切换学习日。

规则（用户拍板）：
- 一天套卷、一天强化，交替推进。
- 真题从旧到新精做（2009→2023），近三年（2024/2025/2026）留到考前当模考。
- 没做完不清零：过期未完成的任务一直挂着显示为「补做」。
- 未完成当前任务时，不生成下一项；完成后才推进到强化或下一套真题。

任务在所属学习日的次日 08:00 前有效；未来只预排下一项待做任务，避免把尚未完成的真题误显示为后续强化。
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .schema import dedupe_daily_tasks

WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
BEIJING_TZ = ZoneInfo('Asia/Shanghai')
STUDY_DAY_BOUNDARY_HOUR = 8


def today_str(now: datetime | None = None) -> str:
    """当前学习日：北京时间次日 08:00 前仍归属前一天的任务。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(BEIJING_TZ)
    if local.hour < STUDY_DAY_BOUNDARY_HOUR:
        return (local.date() - timedelta(days=1)).isoformat()
    return local.date().isoformat()


def calendar_today_str(now: datetime | None = None) -> str:
    """真实北京时间日期，供倒计时、页头与日历高亮使用。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(BEIJING_TZ).date().isoformat()


def _d(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def weekday_cn(s: str) -> str:
    return WEEKDAYS[_d(s).weekday()]


def task_deadline_at(task_day: str) -> str:
    """任务结束于所属学习日的次日北京时间 08:00，以 UTC ISO 返回给前端。"""
    deadline = datetime.combine(
        _d(task_day) + timedelta(days=1),
        time(hour=STUDY_DAY_BOUNDARY_HOUR),
        tzinfo=BEIJING_TZ,
    )
    return deadline.astimezone(timezone.utc).isoformat()


def next_study_boundary_at(now: datetime | None = None) -> str:
    """下一个北京时间 08:00 边界，以 UTC ISO 返回，供前端定时刷新。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(BEIJING_TZ)
    boundary = datetime.combine(local.date(), time(hour=STUDY_DAY_BOUNDARY_HOUR), tzinfo=BEIJING_TZ)
    if local >= boundary:
        boundary += timedelta(days=1)
    return boundary.astimezone(timezone.utc).isoformat()


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
    """给某一天决定任务；存在未完成旧任务时不生成下一项。"""
    if overdue:
        return None
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


def _remove_premature_reinforcements(conn) -> int:
    """清掉旧版在未完成真题后自动排出的、尚未开始的强化任务。"""
    cur = conn.execute(
        "DELETE FROM daily_tasks "
        "WHERE kind='reinforce' AND status='todo' AND session_id IS NULL "
        "AND EXISTS ("
        "  SELECT 1 FROM daily_tasks earlier "
        "  WHERE earlier.plan_date < daily_tasks.plan_date "
        "    AND earlier.kind IN ('exam', 'mock') AND earlier.status='todo'"
        ")"
    )
    return cur.rowcount


def ensure_through_today(conn) -> dict:
    """确保今天至多一项任务；未完成时不按漏掉的日期回填后续任务。"""
    cfg = ensure_config(conn)
    refresh_status(conn)
    dedupe_daily_tasks(conn)
    _remove_premature_reinforcements(conn)

    day = today_str()
    current = conn.execute('SELECT 1 FROM daily_tasks WHERE plan_date=?', (day,)).fetchone()
    overdue = len(_overdue_rows(conn, day))
    if not current and not overdue:
        used = _used_years(conn)
        decision = _decide(conn, cfg, day, _prev_kind(conn, day), overdue, used)
        if decision:
            kind, year = decision
            conn.execute('INSERT OR IGNORE INTO daily_tasks(plan_date, kind, ref_year) VALUES(?,?,?)',
                         (day, kind, year))
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


def point_progress(conn) -> dict:
    """知识点进度：总量 / 已练过 / 已掌握 / 待强化。

    分母取真题选择题上出现过的全部知识点（大题暂无标签，故不计入）。
    「已练」= 出现在任一已交卷记录里；「待强化」= 还在薄弱池中；两者之差即「已掌握」。
    """
    from . import scheduler
    total, covered = set(), set()
    for r in conn.execute("SELECT tags FROM questions WHERE source='exam' AND qtype='choice'"):
        total.update(scheduler.split_tags(r['tags']))
    for r in conn.execute(
            'SELECT DISTINCT q.tags FROM session_items si'
            ' JOIN questions q ON q.id=si.question_id'
            ' JOIN sessions s ON s.id=si.session_id'
            " WHERE s.status='graded' AND q.qtype='choice'"):
        covered.update(scheduler.split_tags(r['tags']))
    covered &= total
    weak = {r['tag'] for r in conn.execute('SELECT tag FROM point_schedule')} & total
    return {'points_total': len(total), 'points_covered': len(covered),
            'points_weak': len(weak), 'points_ok': len(covered - weak)}


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
            'session_id': r['session_id'], 'deadline_at': task_deadline_at(r['plan_date']), **d}


def _last_materialized_kind(conn) -> str:
    r = conn.execute('SELECT kind FROM daily_tasks ORDER BY plan_date DESC, id DESC LIMIT 1').fetchone()
    return r['kind'] if r else ''


def simulate_range(conn, cfg, from_d: date, to_d: date) -> list:
    """预排下一项待做任务（不落库）；当前任务完成后才推算后续。"""
    if from_d > to_d or _overdue_rows(conn, from_d.isoformat()):
        return []
    used = set(_used_years(conn))
    prev_kind = _last_materialized_kind(conn)
    day = from_d.isoformat()
    decision = _decide(conn, cfg, day, prev_kind, 0, used)
    if not decision:
        return []
    kind, year = decision
    return [{'date': day, 'weekday': weekday_cn(day), 'kind': kind, 'ref_year': year,
             **describe(conn, kind, year)}]


def upcoming(conn, cfg, days: int = 7) -> list:
    """未来若干天的预排（不落库；按当前进度推算，会随实际完成情况自我校正）。"""
    t = _d(today_str())
    return simulate_range(conn, cfg, t + timedelta(days=1), t + timedelta(days=days))


def calendar(conn, ym: Optional[str] = None) -> dict:
    """某个月的排程日历：已过去与今天用落库数据，未来用预排。ym 形如 2026-08。"""
    cfg = ensure_through_today(conn)
    refresh_status(conn)
    actual_today = calendar_today_str()
    study_day = today_str()
    y, m = (int(x) for x in (ym or actual_today[:7]).split('-'))
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)

    days = {}
    for r in conn.execute('SELECT * FROM daily_tasks WHERE plan_date BETWEEN ? AND ? ORDER BY id',
                          (first.isoformat(), last.isoformat())):
        days[r['plan_date']] = {**task_public(conn, r), 'planned': False}
    if last >= _d(study_day) + timedelta(days=1):
        for e in simulate_range(conn, cfg, _d(study_day) + timedelta(days=1), last):
            if first <= _d(e['date']) <= last:
                days.setdefault(e['date'], {**e, 'status': 'plan', 'planned': True, 'id': None,
                                            'session_id': None})
    return {'month': f'{y:04d}-{m:02d}', 'first_weekday': first.weekday(),
            'days_in_month': last.day, 'today': actual_today, 'study_day': study_day,
            'exam_date': cfg['exam_date'], 'next_study_boundary_at': next_study_boundary_at(),
            'days': [days[k] for k in sorted(days)]}


def view(conn) -> dict:
    """首页排程视图：倒计时 + 今日任务 + 补做 + 未来预排 + 进度。"""
    cfg = ensure_through_today(conn)
    refresh_status(conn)
    actual_today = calendar_today_str()
    study_day = today_str()
    today_rows = conn.execute('SELECT * FROM daily_tasks WHERE plan_date=? ORDER BY id', (study_day,)).fetchall()
    overdue_rows = _overdue_rows(conn, study_day)
    main, mocks = _pools(conn, cfg)
    done_years = {r['ref_year'] for r in conn.execute(
        "SELECT DISTINCT ref_year FROM daily_tasks WHERE status='done' AND ref_year IS NOT NULL")}
    return {
        'exam_date': cfg['exam_date'],
        'days_left': (_d(cfg['exam_date']) - _d(actual_today)).days,
        'today': actual_today, 'weekday': weekday_cn(actual_today), 'study_day': study_day,
        'next_study_boundary_at': next_study_boundary_at(),
        'tasks': [task_public(conn, r) for r in today_rows],
        'overdue': [task_public(conn, r) for r in overdue_rows],
        'upcoming': upcoming(conn, cfg),
        'progress': {'papers_total': len(main) + len(mocks), 'papers_done': len(done_years),
                     **point_progress(conn)},
    }
