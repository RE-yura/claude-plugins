from pathlib import Path

from .runner import CdxError, checked


def root(runner, repo):
    return Path(checked(runner, ['git', 'rev-parse', '--show-toplevel'], cwd=repo)).resolve()


def add_worktree(runner, repo, worktree, branch):
    checked(runner, ['git', 'worktree', 'add', '-b', branch, str(worktree), 'HEAD'], cwd=repo)


def exclude(runner, worktree):
    path = Path(checked(runner, ['git', 'rev-parse', '--git-path', 'info/exclude'], cwd=worktree))
    if not path.is_absolute():
        path = worktree / path
    text = path.read_text() if path.exists() else ''
    if '.ai/' not in text.splitlines():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ('\n' if text and not text.endswith('\n') else '') + '.ai/\n')


def final(runner, st, task_dir):
    target = task_dir / 'final'
    target.mkdir(exist_ok=True)
    checked(runner, ['git', 'add', '-N', '--', '.'], cwd=st.worktree)
    patch = runner.run(['git', 'diff', '--binary', st.base], cwd=st.worktree)
    if patch.returncode:
        raise CdxError(1, '最終 diff を保存できない: ' + patch.stderr.strip())
    (target / 'diff.patch').write_text(patch.stdout)
    status = checked(runner, ['git', 'status', '--short'], cwd=st.worktree)
    (target / 'status.txt').write_text(status + '\n')


def commit(runner, st, message):
    checked(runner, ['git', 'add', '-A'], cwd=st.worktree)
    checked(runner, ['git', 'commit', '-m', message], cwd=st.worktree)
    return checked(runner, ['git', 'rev-parse', 'HEAD'], cwd=st.worktree)


def remove_worktree(runner, st, force):
    if not force:
        merged = runner.run(['git', 'merge-base', '--is-ancestor', st.branch, 'HEAD'], cwd=st.repo)
        if merged.returncode == 1:
            raise CdxError(3, 'branch が未マージ。merge 後に cleanup、破棄なら --force を指定する')
        if merged.returncode:
            raise CdxError(1, 'マージ状態を確認できない: ' + merged.stderr.strip())
    argv = ['git', 'worktree', 'remove'] + (['--force'] if force else []) + [st.worktree]
    checked(runner, argv, cwd=st.repo)
    checked(runner, ['git', 'branch', '-D' if force else '-d', st.branch], cwd=st.repo)
