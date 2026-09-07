"""集中配置：从 .env.local / .env 读环境，暴露路径与设置。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]   # .../cs408/backend
DATA_DIR = BASE_DIR / 'data'
DRAFTS_DIR = DATA_DIR / 'drafts'
NOTE_IMAGES_DIR = DATA_DIR / 'note_images'
RAW_DIR = DATA_DIR / 'raw'
DB_PATH = DATA_DIR / 'study.db'
# 生产单端口部署：后端直接托管前端构建产物（开发时由 Vite 提供，此目录不存在则跳过）。
DIST_DIR = BASE_DIR.parent / 'frontend' / 'dist'


def _load_env_files():
    """把 .env.local / .env 载入环境（不覆盖已存在的变量）。真实密钥放 .env.local(gitignore)。"""
    for p in [BASE_DIR.parent / '.env.local', BASE_DIR / '.env.local', BASE_DIR.parent / '.env']:
        if p.exists():
            for line in p.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env_files()


class Settings:
    INITIAL_PASSWORD = os.environ.get('STUDY_INITIAL_PASSWORD', '')
    SESSION_SECRET = os.environ.get('SESSION_SECRET', 'dev-insecure-change-me')
    SESSION_MAX_AGE = int(os.environ.get('SESSION_MAX_AGE', str(30 * 24 * 3600)))
    GRADE_BASE_URL = (os.environ.get('GRADE_BASE_URL') or 'https://vyceai.com/v1').rstrip('/')
    GRADE_API_KEY = os.environ.get('GRADE_API_KEY', '')
    GRADE_MODEL = os.environ.get('GRADE_MODEL') or 'gpt-5.6-luna'
    PORT = int(os.environ.get('STUDY_PORT', '8408'))
    # 手机扫码上传草稿用的对外地址。留空=自动取局域网 IP:PORT；上线后填公网地址(如 https://x.com/cs408)
    PUBLIC_BASE = os.environ.get('STUDY_PUBLIC_BASE', '')


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
NOTE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
