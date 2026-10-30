from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys

from . import codex, compat, git, hc, render, state
from .runner import CdxError, Runner, checked

SKILL = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL / 'templates'


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CdxError(3, f'引数を確認する: {message}')


def parser():
    result = Parser(prog='cdx', add_help=False, description='Codex への実装委譲')
    result.add_argument('--task', type=Path)
    commands = result.add_subparsers(dest='command', required=True)
    for name in ('start', 'status', 'doctor', 'render', '_exec', 'run', 'wait', 'fix',
                 'finish', 'abort', 'cleanup'):
        sub = commands.add_parser(name, add_help=False)
        sub.add_argument('--task', type=Path, default=argparse.SUPPRESS)
        if name == 'start':
            sub.add_argument('--repo', type=Path, default=Path.cwd())
            sub.add_argument('--name', default='task')
            sub.add_argument('--allow-untested', action='store_true')
        elif name == '_exec':
            sub.add_argument('task_dir', type=Path)
            sub.add_argument('n', type=int)
        elif name == 'run':
            sub.add_argument('--wait', action='store_true')
            sub.add_argument('--allow-untested', action='store_true')
            sub.add_argument('--retry', action='store_true')
        elif name == 'finish':
            sub.add_argument('-m', required=True)
        elif name == 'cleanup':
            sub.add_argument('--force', action='store_true')
    return result


def start(args, runner, now, env):
    if not re.fullmatch('[a-z0-9-]{1,20}', args.name):
        raise CdxError(3, 'name は a-z0-9- の1〜20文字にする')
    problems = compat.check(runner)
    if problems and not args.allow_untested:
        raise CdxError(3, ' / '.join(problems))
    repo = git.root(runner, args.repo)
    task_id = now.strftime('%Y%m%d-%H%M%S-') + args.name
    worktree = repo.parent / 'worktrees' / task_id
    if worktree.exists():
        raise CdxError(3, f'worktree が既にある: {worktree}')
    branch = 'ai/' + task_id
    base = checked(runner, ['git', 'rev-parse', 'HEAD'], cwd=repo)
    git.add_worktree(runner, repo, worktree, branch)
    git.exclude(runner, worktree)
    task_dir = worktree / '.ai' / 'tasks' / task_id
    (task_dir / 'rounds').mkdir(parents=True)
    shutil.copyfile(TEMPLATES / 'PLAN.md', task_dir / 'PLAN.md')
    caller = env.get('HC_TERMINAL_ID') or None
    st = state.State(task_id, str(repo), str(worktree), branch, base,
                     'child' if caller else 'hidden', caller, 'planning', 1,
                     None, [], [], now.isoformat())
    state.save(task_dir, st)
    return 0, {'task_dir': str(task_dir), 'worktree': str(worktree), 'branch': branch, 'mode': st.mode}


def doctor(runner, env):
    versions, problems = compat.inspect(runner)
    core = None
    if runner.which('hc'):
        result = runner.run(['hc', 'server', 'status', '--json'])
        try:
            core = json.loads(result.stdout)['version'] if not result.returncode else None
        except (ValueError, KeyError, TypeError):
            pass
    if core is None:
        problems.append('hc core に繋がらない')
    elif core != versions['hc']:
        problems.append('hc core と CLI の版が一致しない')
    config = Path(env.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    installed = config / 'plugins' / 'installed_plugins.json'
    duplicates = []
    if installed.exists():
        try:
            registry = json.loads(installed.read_text())
            if not isinstance(registry, dict) or not isinstance(registry.get('plugins', {}), dict):
                raise ValueError('registry')
            entries = registry.get('plugins', {}).get('codex-delegate@re-yura', [])
            if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
                raise ValueError('entries')
            duplicates = [entry for entry in entries if entry.get('scope') != 'user']
        except (OSError, ValueError):
            problems.append('installed_plugins.json を確認できない。形式と権限を確認する')
    if duplicates:
        problems.append('user 以外の scope に codex-delegate がある。重複を解消する')
    return (3 if problems else 0), dict(ok=not problems, problems=problems,
                                       **versions, hc_core=core, duplicate_scopes=duplicates)


def prompt(task_dir, st):
    current = state.round_dir(task_dir, st.round)
    current.mkdir(parents=True, exist_ok=True)
    target = current / 'PROMPT.md'
    if not target.exists():
        template = 'PROMPT-initial.md' if st.round == 1 else 'PROMPT-fix.md'
        relative = task_dir.relative_to(Path(st.worktree))
        target.write_text((TEMPLATES / template).read_text().format(
            task_id=st.task_id, task_dir_rel=relative, round=st.round,
            previous_round=f'{st.round - 1:02d}'))
    return target


def prepare_run(args, task_dir, st, runner, now):
    record = next((r for r in st.rounds if r['n'] == st.round), None)
    expected_phase = 'planning' if st.round == 1 else 'review'
    if args.retry:
        if (st.phase != 'review' or record is None or record['status'] != 'failed' or
                record['terminal'] in st.terminals):
            raise CdxError(3, '--retry は failed かつ terminal 削除済みのラウンドだけに使える')
    elif st.phase != expected_phase or record is not None:
        raise CdxError(3, 'このラウンドは開始済み、または開始できる phase ではない')
    plan = task_dir / 'PLAN.md'
    if st.round == 1 and (not plan.exists() or not plan.read_text().strip()):
        raise CdxError(3, 'PLAN.md が空。計画を記入する')
    if st.round > 1 and not state.round_dir(task_dir, st.round).is_dir():
        raise CdxError(3, 'cdx fix で次のラウンドを作成する')
    for name in st.terminals:
        if hc.get(runner, name).get('state') == 'live':
            raise CdxError(3, f'前ラウンドの terminal が稼働中: {name}')
    problems = compat.check(runner)
    if problems and not args.allow_untested:
        raise CdxError(3, ' / '.join(problems))
    if st.round > 1 and not st.thread_id:
        raise CdxError(3, 'resume 用 thread_id がない')
    prompt(task_dir, st)
    stamp = datetime.strptime(st.task_id[:15], '%Y%m%d-%H%M%S').strftime('%m%d%H%M%S')
    name = f'cdx-{stamp}-r{st.round:02d}'
    attempt = dict(terminal=name, started_at=now.isoformat(), ended_at=None,
                   exit_code=None, status='running')
    if args.retry:
        current = state.round_dir(task_dir, st.round)
        for filename in ('events.jsonl', 'DONE.json', 'exit_code', 'stderr.txt', 'terminal.txt'):
            (current / filename).unlink(missing_ok=True)
        previous = {key: value for key, value in record.items() if key not in ('n', 'attempts')}
        record.setdefault('attempts', [previous]).append(attempt)
        record.update(attempt)
    else:
        st.rounds.append(dict(n=st.round, **attempt))
    st.terminals.append(name)
    st.phase = 'running'
    state.save(task_dir, st)
    return name


def run(args, task_dir, st, runner, now):
    with state.lock(task_dir):
        st = state.load(task_dir)
        name = prepare_run(args, task_dir, st, runner, now)
    hc.run_bg(runner, name, st.worktree,
              [sys.executable, str(SKILL / 'cdx'), '_exec', str(task_dir), str(st.round)], st.mode)
    if args.wait:
        return wait(task_dir, state.load(task_dir), runner)
    return 0, {'round': st.round, 'status': 'running', 'terminal': name}


def wait(task_dir, st, runner):
    if st.phase in ('finished', 'aborted'):
        raise CdxError(3, '終了済みの task は wait できない。cdx status で確認する')
    record = next((r for r in st.rounds if r['n'] == st.round), None)
    if record is None:
        raise CdxError(3, 'このラウンドは未開始。cdx run を実行する')
    terminal = record['terminal']
    if terminal in st.terminals:
        while True:
            try:
                result = hc.wait(runner, terminal)
            except CdxError:
                if hc.get(runner, terminal).get('state') == 'finished':
                    break
                raise
            if result.get('reason') == 'exit' or hc.get(runner, terminal).get('state') == 'finished':
                break
    current = state.round_dir(task_dir, st.round)
    if not (current / 'exit_code').exists() and terminal in st.terminals:
        (current / 'terminal.txt').write_text(hc.read(runner, terminal))
    try:
        exit_code = int((current / 'exit_code').read_text().strip())
    except (OSError, ValueError):
        exit_code = None
    try:
        done = json.loads((current / 'DONE.json').read_text())
        if not isinstance(done, dict):
            done = None
    except (OSError, ValueError):
        done = None
    status, code = 'failed', 1
    if exit_code == 0 and done:
        if done.get('status') == 'done':
            status, code = 'done', 0
        elif done.get('status') == 'blocked':
            status, code = 'blocked', 2
    # _exec が保存した thread_id を古い state で上書きしない。
    st = state.load(task_dir)
    record = next(r for r in st.rounds if r['n'] == st.round)
    result = dict(status=status, exit_code=exit_code, ended_at=datetime.now().astimezone().isoformat())
    record.update(result)
    if 'attempts' in record:
        record['attempts'][-1].update(result)
    st.phase = 'review'
    state.save(task_dir, st)
    if terminal in st.terminals:
        hc.remove(runner, terminal)
        st.terminals.remove(terminal)
        state.save(task_dir, st)
    data = dict(round=st.round, status=status, done=done, terminal=terminal)
    if code == 1:
        stderr = current / 'stderr.txt'
        text = stderr.read_text() if stderr.exists() else ''
        if not text.strip() and (current / 'terminal.txt').exists():
            text = (current / 'terminal.txt').read_text()
        data['stderr_tail'] = '\n'.join(text.splitlines()[-20:])
    return code, data


def review_status(task_dir, st):
    review = state.round_dir(task_dir, st.round) / 'REVIEW.md'
    lines = review.read_text().splitlines() if review.exists() else []
    return lines[0] if lines else ''


def fix(task_dir, st):
    if st.phase != 'review' or review_status(task_dir, st) != 'Status: CHANGES_REQUESTED':
        raise CdxError(3, '最新 REVIEW.md の先頭行を Status: CHANGES_REQUESTED にする')
    if st.round >= 4:
        raise CdxError(3, '修正は3回まで。人の判断が必要')
    st.round += 1
    target = prompt(task_dir, st)
    state.save(task_dir, st)
    return 0, {'round': st.round, 'prompt': str(target)}


def owned(task_dir, st, runner):
    worktree = Path(st.worktree)
    expected = Path(st.repo).parent / 'worktrees' / st.task_id
    if (worktree != expected or st.branch != 'ai/' + st.task_id or
            task_dir != worktree / '.ai' / 'tasks' / st.task_id or
            git.root(runner, worktree) != worktree or
            checked(runner, ['git', 'branch', '--show-current'], cwd=worktree) != st.branch):
        raise CdxError(3, 'task の worktree / branch と現在の Git 状態が一致しない')


def stop_terminals(task_dir, st, runner):
    for name in list(st.terminals):
        hc.kill_rm(runner, name)
        st.terminals.remove(name)
        state.save(task_dir, st)


def finish(args, task_dir, st, runner):
    if st.phase != 'review' or review_status(task_dir, st) != 'Status: APPROVED':
        raise CdxError(3, 'phase review と最新 REVIEW.md の Status: APPROVED が必要')
    owned(task_dir, st, runner)
    git.final(runner, st, task_dir)
    commit = git.commit(runner, st, args.m)
    stop_terminals(task_dir, st, runner)
    st.phase = 'finished'
    state.save(task_dir, st)
    return 0, dict(branch=st.branch, commit=commit, worktree=st.worktree,
                   next_step='merge / PR / reject は人が選ぶ。merge 後に cdx cleanup')


def abort(task_dir, st, runner):
    owned(task_dir, st, runner)
    stop_terminals(task_dir, st, runner)
    # _exec の終了直前に保存された thread_id も保持する。
    st = state.load(task_dir)
    git.final(runner, st, task_dir)
    st.phase = 'aborted'
    state.save(task_dir, st)
    return 0, {'phase': st.phase, 'final': str(task_dir / 'final')}


def cleanup(args, task_dir, st, runner):
    if st.phase not in ('finished', 'aborted'):
        raise CdxError(3, 'cleanup は finished / aborted の task だけに使える')
    for name in st.terminals:
        if hc.get(runner, name).get('state') != 'finished':
            raise CdxError(3, f'terminal が終了していない: {name}')
    owned(task_dir, st, runner)
    for name in list(st.terminals):
        hc.remove(runner, name)
        st.terminals.remove(name)
        state.save(task_dir, st)
    git.remove_worktree(runner, st, args.force)
    return 0, {'removed_worktree': st.worktree, 'removed_branch': st.branch}


def main(argv=None, runner=None, now=None, env=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ) if env is None else env
    runner = Runner(env=env) if runner is None else runner
    now = datetime.now().astimezone() if now is None else now
    try:
        cli = parser()
        if '--help' in argv or '-h' in argv:
            print(json.dumps({'help': cli.format_help()}, ensure_ascii=False))
            return 0
        args = cli.parse_args(argv)
        if args.command == 'render':
            for text in sys.stdin:
                display = render.line(render.parse(text))
                if display is not None:
                    print(display, flush=True)
            return 0
        if args.command == '_exec':
            return codex.execute(args.task_dir.resolve(), args.n, runner)
        if args.command == 'start':
            code, data = start(args, runner, now, env)
        elif args.command == 'doctor':
            code, data = doctor(runner, env)
        else:
            task_dir = args.task.resolve() if args.task else state.find_task_dir(Path.cwd())
            st = state.load(task_dir)
            if args.command == 'run':
                code, data = run(args, task_dir, st, runner, now)
            elif args.command == 'wait':
                code, data = wait(task_dir, st, runner)
            elif args.command == 'fix':
                code, data = fix(task_dir, st)
            elif args.command == 'finish':
                code, data = finish(args, task_dir, st, runner)
            elif args.command == 'abort':
                code, data = abort(task_dir, st, runner)
            elif args.command == 'cleanup':
                code, data = cleanup(args, task_dir, st, runner)
            else:
                current = state.round_dir(task_dir, st.round)
                code, data = 0, dict(asdict(st), round_files=sorted(p.name for p in current.iterdir())
                                    if current.exists() else [])
    except CdxError as exc:
        code, data = exc.code, {'error': str(exc)}
    except (OSError, ValueError, TypeError) as exc:
        code, data = 1, {'error': f'実行失敗: {exc}'}
    print(json.dumps(data, ensure_ascii=False))
    return code
