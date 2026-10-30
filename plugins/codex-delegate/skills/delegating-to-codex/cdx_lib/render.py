import json
from pathlib import Path


def parse(text):
    try:
        event = json.loads(text)
        return event if isinstance(event, dict) else None
    except ValueError:
        return None


def line(event: dict) -> str | None:
    if not isinstance(event, dict):
        return None
    kind = event.get('type')
    if kind == 'thread.started' and isinstance(event.get('thread_id'), str):
        return 'session ' + event['thread_id']
    if kind in ('error', 'turn.failed'):
        error = event.get('error')
        message = event.get('message') or (error.get('message') if isinstance(error, dict) else None)
        return f'error: {message}' if message else None
    if kind == 'turn.completed':
        usage = event.get('usage')
        if isinstance(usage, dict) and 'input_tokens' in usage and 'output_tokens' in usage:
            return f'done (in {usage["input_tokens"]} / out {usage["output_tokens"]} tokens)'
        return None
    item = event.get('item')
    if not isinstance(item, dict):
        return None
    item_type = item.get('type')
    if item_type == 'command_execution':
        if kind == 'item.started' and isinstance(item.get('command'), str):
            return '$ ' + item['command']
        if kind == 'item.completed' and 'exit_code' in item:
            return f'  → exit {item["exit_code"]}'
    if kind == 'item.completed' and item_type == 'agent_message' and isinstance(item.get('text'), str):
        return item['text'].split('\n', 1)[0][:200]
    if kind == 'item.completed' and item_type == 'file_change':
        changes = item.get('changes')
        if not isinstance(changes, list):
            return None
        lines = []
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get('path'), str) or 'kind' not in change:
                continue
            path = Path(change['path'])
            if path.is_absolute() and path.is_relative_to(Path.cwd()):
                path = path.relative_to(Path.cwd())
            lines.append(f'edit {change["kind"]} {path}')
        return '\n'.join(lines) or None
    return None
