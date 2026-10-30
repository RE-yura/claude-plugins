import json

from .runner import CdxError, checked


def query(runner, argv):
    text = checked(runner, ['hc', *argv])
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    raise CdxError(1, 'hc の JSON 応答が不正')


def run_bg(runner, name, worktree, command, mode):
    argv = ['run', '--bg', '--name', name, '--cwd', str(worktree)]
    if mode == 'child':
        argv += ['--outlive-parent', '--no-notify']
    return query(runner, argv + ['--', *command])


def wait(runner, name):
    return query(runner, ['wait', name, '--timeout', '300'])


def get(runner, name):
    return query(runner, ['get', name, '--json'])


def read(runner, name):
    result = runner.run(['hc', 'read', name, '--lines', '200'])
    if result.returncode:
        raise CdxError(1, 'terminal の記録を取得できない: ' + result.stderr.strip())
    return result.stdout


def remove(runner, name):
    checked(runner, ['hc', 'rm', name])


def kill_rm(runner, name):
    if get(runner, name).get('state') == 'live':
        checked(runner, ['hc', 'kill', name])
    remove(runner, name)
