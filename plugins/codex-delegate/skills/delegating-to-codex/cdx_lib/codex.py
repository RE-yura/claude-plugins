from pathlib import Path

from . import render, state
from .runner import CdxError

SCHEMA = Path(__file__).resolve().parent.parent / 'templates' / 'done.schema.json'


def exec_argv(st, current):
    args = ['codex', 'exec']
    if st.round == 1:
        args += ['--json', '-C', st.worktree]
    else:
        if not st.thread_id:
            raise CdxError(3, 'resume 用 thread_id がない')
        args += ['resume', st.thread_id, '--json']
    return args + ['-o', str(current / 'DONE.json'), '--output-schema', str(SCHEMA), '-']


def execute(task_dir, n, runner):
    st = state.load(task_dir)
    if n != st.round:
        raise CdxError(3, '最新ラウンドだけ実行できる')
    current = state.round_dir(task_dir, n)
    argv = exec_argv(st, current)
    code = 1
    with (current / 'PROMPT.md').open() as prompt, \
            (current / 'events.jsonl').open('w') as events, \
            (current / 'stderr.txt').open('w') as stderr:
        def receive(text):
            events.write(text)
            events.flush()
            event = render.parse(text)
            if event is None:
                return
            if n == 1 and event.get('type') == 'thread.started' and isinstance(event.get('thread_id'), str):
                latest = state.load(task_dir)
                latest.thread_id = event['thread_id']
                state.save(task_dir, latest)
            display = render.line(event)
            if display is not None:
                print(display, flush=True)
        try:
            code = runner.stream(argv, cwd=st.worktree, input=prompt, stderr=stderr, on_line=receive)
        except OSError as exc:
            stderr.write(f'codex 起動失敗: {exc}\n')
        finally:
            (current / 'exit_code').write_text(str(code) + '\n')
    return code
