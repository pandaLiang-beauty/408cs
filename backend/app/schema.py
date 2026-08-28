"""建表 SQL 与初始化。单用户应用，业务表不带 user_id。

模型（4 个概念）：
  question       题库，稳定不变。
  session        一场做题：真题套卷(exam,含 year) 或 强化卷(reinforce)；有 doing/graded 状态。
  session_item   一次做题记录 = (session, question) 一行。同一题在不同卷里各占一行，
                 各自的 chosen/fuzzy/批改结果/草稿。刷新靠它恢复。
  note           笔记，一题多条，挂 question_id → 按题聚合成「笔记库」。
  review_schedule SRS，按 question_id 一份 = 这题的整体掌握度，不随卷分裂。
"""

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL DEFAULT 'me',
  password_hash TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  year         INTEGER NOT NULL,
  subject      TEXT NOT NULL DEFAULT '',
  number       INTEGER NOT NULL,
  qtype        TEXT NOT NULL DEFAULT 'choice',   -- choice | subjective
  source       TEXT NOT NULL DEFAULT 'exam',      -- exam(真题) | simulate(模拟卷) | exercise(练习)
  stem_html    TEXT NOT NULL,
  options_json TEXT NOT NULL DEFAULT '[]',
  answer       TEXT NOT NULL DEFAULT '',          -- 选择题正确选项
  answer_html  TEXT NOT NULL DEFAULT '',          -- 大题参考答案(HTML)
  tags         TEXT NOT NULL DEFAULT '',
  source_url   TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_q_year ON questions(year, number);
CREATE INDEX IF NOT EXISTS idx_q_type ON questions(qtype);
CREATE INDEX IF NOT EXISTS idx_q_source ON questions(source);

CREATE TABLE IF NOT EXISTS sessions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL DEFAULT 'exam',        -- exam | reinforce
  year       INTEGER,                             -- exam 卷所属年份；reinforce 为 NULL
  status     TEXT NOT NULL DEFAULT 'doing',       -- doing | graded
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  graded_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sess_open ON sessions(kind, year, status);

CREATE TABLE IF NOT EXISTS session_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  position    INTEGER NOT NULL DEFAULT 0,
  chosen      TEXT NOT NULL DEFAULT '',
  fuzzy       INTEGER NOT NULL DEFAULT 0,
  is_correct  INTEGER,                            -- 交卷/批改后才有
  result      TEXT NOT NULL DEFAULT '',           -- correct | wrong | fuzzy
  draft_path  TEXT NOT NULL DEFAULT '',           -- 本次做题的草稿纸(每场各存一份)
  answer_text TEXT NOT NULL DEFAULT '',           -- 大题：本次作答原文
  verdict     TEXT NOT NULL DEFAULT '',           -- 大题：AI 判定(对/部分对/错)
  comment     TEXT NOT NULL DEFAULT '',           -- 大题：AI 点评
  updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(session_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_si_q ON session_items(question_id);

CREATE TABLE IF NOT EXISTS notes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  session_id  INTEGER REFERENCES sessions(id) ON DELETE SET NULL,  -- 写它时的做题上下文(可空)
  body        TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_note_q ON notes(question_id, created_at);

CREATE TABLE IF NOT EXISTS review_schedule (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  level       INTEGER NOT NULL DEFAULT 0,
  due_at      TEXT NOT NULL,
  last_result TEXT NOT NULL DEFAULT '',
  reps        INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rev_due ON review_schedule(due_at);

-- 强化以「知识点」为单位：做错/模糊的知识点入池，做对多道同知识点题才逐级拉长间隔（间隔重复、不毕业）。
CREATE TABLE IF NOT EXISTS point_schedule (
  tag         TEXT PRIMARY KEY,
  level       INTEGER NOT NULL DEFAULT 0,
  due_at      TEXT NOT NULL,
  streak      INTEGER NOT NULL DEFAULT 0,   -- 自上次做错以来连续做对的同知识点题数
  last_result TEXT NOT NULL DEFAULT '',
  reps        INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pt_due ON point_schedule(due_at);

-- 大模型配置：在线动态改（单行，id=1）。api_format ∈ openai | anthropic | responses。
-- 保留作历史迁移来源；现用 llm_profiles(多档) + app_settings(选中哪档/全局提示词)。
CREATE TABLE IF NOT EXISTS llm_config (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  api_format   TEXT NOT NULL DEFAULT 'openai',
  base_url     TEXT NOT NULL DEFAULT '',
  api_key      TEXT NOT NULL DEFAULT '',
  model        TEXT NOT NULL DEFAULT '',
  temperature  REAL NOT NULL DEFAULT 0.2,
  grade_prompt TEXT NOT NULL DEFAULT '',
  updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 多档大模型配置：可存多个(vyceai / 自建IP直连 / 白鹿 …)，用 app_settings.active_profile_id 选一个用。
CREATE TABLE IF NOT EXISTS llm_profiles (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL DEFAULT '',
  api_format  TEXT NOT NULL DEFAULT 'openai',
  base_url    TEXT NOT NULL DEFAULT '',
  api_key     TEXT NOT NULL DEFAULT '',
  model       TEXT NOT NULL DEFAULT '',
  temperature REAL NOT NULL DEFAULT 0.2,
  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 全局单行设置：当前选中的大模型档 + 大题批改提示词(与具体网关无关，故全局)。
CREATE TABLE IF NOT EXISTS app_settings (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  active_profile_id INTEGER REFERENCES llm_profiles(id) ON DELETE SET NULL,
  grade_prompt      TEXT NOT NULL DEFAULT ''
);

-- 草稿纸手机上传令牌：电脑上生成二维码 → 手机扫码打开上传页 → 图片写回对应做题记录。
-- token 本身就是凭据（不可猜、单次、短时效），故上传页无需登录。
CREATE TABLE IF NOT EXISTS draft_tokens (
  token       TEXT PRIMARY KEY,
  session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at  TEXT NOT NULL,
  used_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dt_exp ON draft_tokens(expires_at);

-- 学习排程：只安排「天」，不排钟点。一天套卷、一天强化交替；近三年真题留作考前模考。
CREATE TABLE IF NOT EXISTS plan_config (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  exam_date  TEXT NOT NULL DEFAULT '2026-12-19',
  start_date TEXT NOT NULL DEFAULT '',          -- 排程起始日（首次生成时写今天）
  mock_years TEXT NOT NULL DEFAULT '2024,2025,2026',
  mock_days  INTEGER NOT NULL DEFAULT 21        -- 考前多少天开始安排模考
);

CREATE TABLE IF NOT EXISTS daily_tasks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_date  TEXT NOT NULL,                     -- YYYY-MM-DD（本地日期）
  kind       TEXT NOT NULL,                     -- exam(精做真题) | mock(模考) | reinforce(强化)
  ref_year   INTEGER,                           -- 真题/模考年份；强化为 NULL
  session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
  status     TEXT NOT NULL DEFAULT 'todo',      -- todo | done
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_date ON daily_tasks(plan_date, status);
"""


def initialize(conn) -> None:
    _pre_migrate(conn)          # 先给老表补列，之后 SCHEMA_SQL 里引用 source 的索引才不会报错
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _pre_migrate(conn) -> None:
    """轻量迁移：给已存在的表补齐新增列（老库不会因 CREATE IF NOT EXISTS 得到新列）。"""
    has_q = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='questions'").fetchone()
    if not has_q:
        return
    cols = {r[1] for r in conn.execute('PRAGMA table_info(questions)')}
    if 'source' not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN source TEXT NOT NULL DEFAULT 'exam'")
    has_llm = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_config'").fetchone()
    if has_llm:
        lcols = {r[1] for r in conn.execute('PRAGMA table_info(llm_config)')}
        if 'grade_prompt' not in lcols:
            conn.execute("ALTER TABLE llm_config ADD COLUMN grade_prompt TEXT NOT NULL DEFAULT ''")
