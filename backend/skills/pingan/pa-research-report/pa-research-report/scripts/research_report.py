#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研报检索工具 - 从平安证券研报知识库检索相关研报片段

用法:
    python research_report.py [关键词] [top_k] [threshold]

示例:
    python research_report.py 半导体 10 0.3
    python research_report.py AI芯片 5 0.4

标签预筛选(SPEC 第4点):
    脚本先到同目录 label_value_ids 中按关键词匹配「标签值(第四列)→标签ID(第三列)」,
    用标签ID做预筛选召回(并集);若召回为空再回退全库召回。

凭据(SPEC 第5点):
    api_key 优先读环境变量 PINGAN_SKILL_APIKEY,其次读同目录 .env 中的 PINGAN_SKILL_APIKEY。
"""

import io
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error

# Windows 终端 UTF-8 编码修复
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 默认配置:api_key 已移至 .env / 环境变量 PINGAN_SKILL_APIKEY(见 SPEC 第5点),不在此硬编码
DEFAULT_CONFIG = {
    'api_url': 'https://ai.stock.pingan.com/restapi/yanbao/e-server-transfer-service/dify/retrieval',
    'knowledge_id': '1_5_520_v2',
    'auth_token': 'e4c34022e6a64e0d83dfea24b1540415',
    'top_k': 10,
    'similarity_threshold': 0.3,
    'display_size': 5,
    'timeout': 30,
}

# 其余可选项(.env / 环境变量覆盖)。api_key 单独走 PINGAN_SKILL_APIKEY,见 load_config_from_env
_ENV_OVERRIDES = {
    'api_url': 'RESEARCH_API_URL',
    'knowledge_id': 'RESEARCH_KNOWLEDGE_ID',
    'auth_token': 'RESEARCH_TOKEN',
}

_LABELS_FILENAME = 'label_value_ids'


def _load_env_file(env_file_path):
    """读取 .env 文件,返回键值字典。"""
    env = {}
    if env_file_path and os.path.exists(env_file_path):
        with open(env_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env[key.strip()] = value.strip()
    return env


def load_config_from_env(env_path=None):
    """加载配置。api_key 优先环境变量 PINGAN_SKILL_APIKEY,其次 .env(SPEC 第5点)。"""
    config = DEFAULT_CONFIG.copy()
    env = _load_env_file(env_path)
    api_key = os.environ.get('PINGAN_SKILL_APIKEY') or env.get('PINGAN_SKILL_APIKEY')
    if api_key:
        config['api_key'] = api_key
    for cfg_key, env_key in _ENV_OVERRIDES.items():
        value = os.environ.get(env_key) or env.get(env_key)
        if value:
            config[cfg_key] = value
    return config


def _to_float(value, default=0.0):
    """安全转 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _doc_name(record):
    """提取文档名:title 优先,其次 metadata.description。"""
    metadata = record.get('metadata') or {}
    return record.get('title') or metadata.get('description') or '未知文档'


def _load_label_map(labels_path):
    """加载 label_value_ids,返回 [(label_value, label_id, label_name), ...]。

    文件每行格式(空白分隔): parent_id  label_name  label_id  label_value
    映射关系: 第四列(标签值) -> 第三列(标签 id)。
    """
    mapping = []
    if not labels_path or not os.path.exists(labels_path):
        return mapping
    with open(labels_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _parent, name, vid, value = parts[0], parts[1], parts[2], parts[3].strip()
            try:
                label_id = int(vid)
            except ValueError:
                continue
            mapping.append((value, label_id, name))
    return mapping


def _match_label_ids(keyword, label_map):
    """根据关键词匹配标签值,返回 [(value, label_id), ...](精确匹配优先,去重)。"""
    if not keyword:
        return []
    kw = keyword.strip()
    if not kw:
        return []
    matched, seen = [], set()

    def _add(value, label_id):
        if label_id not in seen:
            seen.add(label_id)
            matched.append((value, label_id))

    # 第一轮:精确匹配(关键词 == 标签值)
    for value, label_id, _name in label_map:
        if value == kw:
            _add(value, label_id)
    # 第二轮:子串匹配(关键词含标签值 或 标签值含关键词)
    for value, label_id, _name in label_map:
        if value != kw and (kw in value or value in kw):
            _add(value, label_id)
    return matched


def _build_query_value(keyword, label_matches):
    """构造 query 入参:有标签匹配时返回 JSON 字符串,否则返回纯关键词字符串。"""
    if label_matches:
        label_ids = [lid for _val, lid in label_matches]
        return json.dumps({'question': keyword, 'label_value_ids': label_ids}, ensure_ascii=False)
    return keyword


def _do_retrieval(query_value, config):
    """发起一次检索请求。返回 (records, error):成功时 error=None,records 为原始列表(可能为空)。"""
    api_url = config.get('api_url', DEFAULT_CONFIG['api_url'])
    knowledge_id = config.get('knowledge_id', DEFAULT_CONFIG['knowledge_id'])
    top_k = config.get('top_k', DEFAULT_CONFIG['top_k'])
    threshold = config.get('similarity_threshold', DEFAULT_CONFIG['similarity_threshold'])
    timeout = config.get('timeout', DEFAULT_CONFIG['timeout'])

    payload = {
        'knowledge_id': knowledge_id,
        'query': query_value,
        'retrieval_setting': {
            'top_k': top_k,
            'score_threshhold': threshold,  # 接口字段名为 score_threshhold
        },
    }
    request_id = 'skill_%d_%s' % (int(time.time()), uuid.uuid4().hex[:8])
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': config.get('api_key'),
        'Authorization': 'Bearer %s' % config.get('auth_token', DEFAULT_CONFIG['auth_token']),
        'requestID': request_id,
    }
    try:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(api_url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_data = json.loads(response.read().decode('utf-8'))
        records = resp_data.get('records', []) or []
        msg = resp_data.get('msg')
        if not records and msg:
            return [], '接口返回业务错误 - %s' % msg
        return records, None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        detail = body
        try:
            parsed = json.loads(body)
            detail = parsed.get('error_message') or parsed.get('error_code') or body
        except (ValueError, TypeError):
            pass
        hint = ''
        if e.code == 401:
            hint = ' (API Key 无效,请检查 PINGAN_SKILL_APIKEY)'
        elif e.code in (403, 404):
            hint = ' (请检查 knowledge_id 或访问权限)'
        elif e.code >= 500:
            hint = ' (知识库服务异常,请稍后重试)'
        return [], 'HTTP %d - %s%s' % (e.code, detail, hint)
    except urllib.error.URLError as e:
        return [], '网络请求失败 - %s,请检查网络连接' % e.reason
    except Exception as e:  # noqa: BLE001
        return [], str(e)


def _process_records(records, threshold):
    """阈值过滤 + 降序排序 + 文档级去重。返回 (filtered, unique)。"""
    filtered = [r for r in records if _to_float(r.get('score')) >= threshold]
    filtered.sort(key=lambda r: _to_float(r.get('score')), reverse=True)
    unique, seen = [], set()
    for record in filtered:
        name = _doc_name(record)
        if name in seen:
            continue
        seen.add(name)
        unique.append(record)
    return filtered, unique


def _format_output(keyword, filtered, unique, display_size, mode, label_matches):
    """按 Markdown 模板组装检索结果。mode: label-filter / fallback / plain。"""
    tag_desc = ', '.join('%s=%d' % (v, i) for v, i in label_matches) if label_matches else ''
    lines = []
    lines.append('## 检索结果汇总')
    lines.append('')
    lines.append('**关键词**: %s' % keyword)
    if mode == 'label-filter':
        lines.append('**召回模式**: 标签过滤(%s)' % tag_desc)
    elif mode == 'fallback':
        lines.append('**召回模式**: 全库召回(标签过滤无有效结果,已回退;曾尝试标签:%s)' % tag_desc)
    else:  # plain
        lines.append('**召回模式**: 全库召回(未匹配到相关标签)')
    lines.append('**检索到 %d 条结果,去重后 %d 篇文档**' % (len(filtered), len(unique)))
    lines.append('')
    lines.append('### 相关文档')
    doc_counts = {}
    for record in unique:
        name = _doc_name(record)
        doc_counts[name] = doc_counts.get(name, 0) + 1
    for name, count in doc_counts.items():
        lines.append('- %s (%d条)' % (name, count))
    lines.append('')
    lines.append('### 核心摘要')
    for i, record in enumerate(unique[:display_size], 1):
        score = _to_float(record.get('score'))
        content = (record.get('content') or '').strip()
        if len(content) > 300:
            content = content[:300] + '...'
        name = _doc_name(record)
        lines.append('')
        lines.append('**结果 %d** (相似度: %.4f)' % (i, score))
        lines.append('')
        lines.append(content if content else '(无正文内容)')
        lines.append('')
        lines.append('**文档**: %s' % name)
    lines.append('')
    lines.append('> 以上内容来源于平安证券研报知识库,仅供参考学习,不构成任何投资建议。投资有风险,决策需谨慎。')
    return '\n'.join(lines)


def search_reports(keyword, config=None):
    """搜索研报:优先标签过滤召回,无有效结果时回退全库召回。返回格式化结果字符串,失败返回 None。"""
    if config is None:
        config = load_config_from_env()

    api_key = config.get('api_key')
    if not api_key:
        print('错误: 未找到 PINGAN_SKILL_APIKEY。请设置环境变量,或在 scripts/.env 中配置 PINGAN_SKILL_APIKEY。',
              file=sys.stderr)
        return None

    display_size = config.get('display_size', DEFAULT_CONFIG['display_size'])
    threshold = config.get('similarity_threshold', DEFAULT_CONFIG['similarity_threshold'])

    # 标签匹配(SPEC 第4点):关键词 -> label_value_ids
    script_dir = os.path.dirname(os.path.abspath(__file__))
    label_map = _load_label_map(os.path.join(script_dir, _LABELS_FILENAME))
    label_matches = _match_label_ids(keyword, label_map)

    label_error = None
    if label_matches:
        # 尝试 1:标签过滤召回
        records, error = _do_retrieval(_build_query_value(keyword, label_matches), config)
        if error:
            label_error = error
        else:
            filtered, unique = _process_records(records, threshold)
            if unique:
                return _format_output(keyword, filtered, unique, display_size, 'label-filter', label_matches)
        # 标签过滤无有效结果或报错 -> 回退全库

    # 尝试 2:全库召回
    records, error = _do_retrieval(_build_query_value(keyword, None), config)
    if error:
        print('错误: %s' % error, file=sys.stderr)
        return None
    filtered, unique = _process_records(records, threshold)
    if unique:
        mode = 'fallback' if label_matches else 'plain'
        return _format_output(keyword, filtered, unique, display_size, mode, label_matches)

    # 全部为空
    if label_error:
        print('错误(标签过滤阶段): %s' % label_error, file=sys.stderr)
    print('未找到相关文档(query="%s", threshold=%s)。可尝试降低相似度阈值(如 0.2)或扩展关键词。'
          % (keyword, threshold), file=sys.stderr)
    return None


def main():
    """主函数。"""
    if len(sys.argv) < 2:
        print('用法: python research_report.py [关键词] [top_k] [threshold]')
        print('  关键词     必填,搜索主题,如"半导体"、"新能源"、"AI芯片"')
        print('  top_k      可选,返回结果数量,默认 10')
        print('  threshold  可选,相似度阈值(0.1-0.9),默认 0.3')
        return

    keyword = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONFIG['top_k']
    threshold = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CONFIG['similarity_threshold']

    # 加载配置(脚本同目录下的 .env)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    config = load_config_from_env(env_path)
    config['top_k'] = top_k
    config['similarity_threshold'] = threshold

    # 执行搜索
    result = search_reports(keyword, config)
    if result:
        print(result)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
