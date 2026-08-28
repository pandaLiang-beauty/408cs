"""AI 大题批改 + 打标签共用的网关客户端。支持 3 种 API 格式：openai | anthropic | responses。
配置来自 DB(llm_config)，调用方把 cfg 传进来；脚本无 DB 时用 cfg_from_settings() 走环境变量。"""
import json
import re
import urllib.request

from .config import settings

SYSTEM_PROMPT = (
    '你是严格的考研408阅卷老师。批改步骤：先把【参考答案】拆成若干评分点（每个小问/关键步骤/代码实现各算一点），'
    '再逐点核对【学生作答】是否真正命中；只要有小问、步骤或代码实现缺失就必须扣分，'
    '绝不能因为“方向/思路对”就给满分。只输出 JSON：'
    '{"verdict":"对|部分对|错","score_ratio":0到1的小数,"comment":"逐点说明命中了哪些、缺了哪些"}。'
)


def cfg_from_settings() -> dict:
    return {'api_format': 'openai', 'base_url': settings.GRADE_BASE_URL,
            'api_key': settings.GRADE_API_KEY, 'model': settings.GRADE_MODEL, 'temperature': 0.2}


def configured(cfg: dict | None = None) -> bool:
    cfg = cfg or cfg_from_settings()
    return bool(cfg.get('api_key') and cfg.get('base_url') and cfg.get('model'))


def _split(messages):
    """把 OpenAI 风格 messages 拆成 (system_text, 非system消息列表)。"""
    sys_parts = [m['content'] for m in messages if m['role'] == 'system']
    rest = [m for m in messages if m['role'] != 'system']
    return '\n'.join(sys_parts), rest


def _post(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                                          **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def chat(cfg: dict, messages, temperature: float | None = None, timeout: int = 120) -> str:
    """发一次对话补全，返回助手文本。按 cfg['api_format'] 适配请求/解析。网关常拒默认 UA，故带浏览器 UA。"""
    base = (cfg.get('base_url') or '').rstrip('/')
    model = cfg.get('model') or ''
    key = cfg.get('api_key') or ''
    temp = cfg.get('temperature', 0.2) if temperature is None else temperature
    fmt = cfg.get('api_format', 'openai')

    if fmt == 'anthropic':
        system, rest = _split(messages)
        body = {'model': model, 'max_tokens': 2048, 'temperature': temp,
                'messages': [{'role': m['role'], 'content': m['content']} for m in rest]}
        if system:
            body['system'] = system
        d = _post(base + '/messages', {'x-api-key': key, 'anthropic-version': '2023-06-01'}, body, timeout)
        parts = [b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text']
        return ''.join(parts) or json.dumps(d)[:400]

    if fmt == 'responses':
        system, rest = _split(messages)
        user_text = '\n\n'.join(m['content'] for m in rest)
        body = {'model': model, 'temperature': temp, 'input': user_text}
        if system:
            body['instructions'] = system
        d = _post(base + '/responses', {'Authorization': 'Bearer ' + key}, body, timeout)
        if isinstance(d.get('output_text'), str):
            return d['output_text']
        # 回退：从 output[].content[].text 里拼
        out = []
        for item in d.get('output', []):
            for cblk in item.get('content', []):
                if cblk.get('text'):
                    out.append(cblk['text'])
        return ''.join(out) or json.dumps(d)[:400]

    # 默认 openai 兼容
    body = {'model': model, 'stream': False, 'temperature': temp, 'messages': messages}
    d = _post(base + '/chat/completions', {'Authorization': 'Bearer ' + key}, body, timeout)
    return d['choices'][0]['message']['content']


# 兼容旧脚本（tag_simulate 等）：无 cfg 时走环境变量的 openai 配置。
def _chat(messages, temperature: float = 0.2, timeout: int = 120) -> str:
    return chat(cfg_from_settings(), messages, temperature, timeout)


def _strip_html(h: str) -> str:
    t = re.sub(r'(?is)<(script|style).*?</\1>', ' ', h or '')
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _extract_json(text: str):
    m = re.search(r'\{.*\}', text or '', re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def grade(cfg: dict, stem_html: str, reference_html: str, student: str) -> dict:
    stem = _strip_html(stem_html)[:2000]
    reference = _strip_html(reference_html)[:4500]
    user_p = f'【题干】{stem}\n【参考答案】{reference}\n【学生作答】{student[:4000]}'
    content = chat(cfg, [
        {'role': 'system', 'content': cfg.get('grade_prompt') or SYSTEM_PROMPT},
        {'role': 'user', 'content': user_p},
    ])
    return _extract_json(content) or {'verdict': '部分对', 'score_ratio': 0.5, 'comment': content[:200]}


def list_models(cfg: dict, timeout: int = 30) -> list:
    """拉取网关可用模型列表。按格式访问 /models（anthropic 用 x-api-key）。"""
    base = (cfg.get('base_url') or '').rstrip('/')
    key = cfg.get('api_key') or ''
    fmt = cfg.get('api_format', 'openai')
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    if fmt == 'anthropic':
        headers['x-api-key'] = key
        headers['anthropic-version'] = '2023-06-01'
    else:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(base + '/models', headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode('utf-8'))
    data = d.get('data', d if isinstance(d, list) else [])
    ids = []
    for m in data:
        mid = m.get('id') if isinstance(m, dict) else m
        if mid:
            ids.append(mid)
    return sorted(set(ids))
