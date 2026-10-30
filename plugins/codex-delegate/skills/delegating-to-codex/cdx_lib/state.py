from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from .runner import CdxError


@dataclass
class State:
    task_id: str
    repo: str
    worktree: str
    branch: str
    base: str
    mode: str
    caller_terminal: str | None
    phase: str
    round: int
    thread_id: str | None
    rounds: list[dict]
    terminals: list[str]
    created_at: str


def load(task_dir: Path) -> State:
    try:
        return State(**json.loads((task_dir / 'state.json').read_text()))
    except (OSError, ValueError, TypeError) as exc:
        raise CdxError(3, f'state.json を読めない: {task_dir}') from exc


def save(task_dir: Path, st: State):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=task_dir,
                                     prefix='.state-', delete=False) as out:
        json.dump(asdict(st), out, ensure_ascii=False, indent=2)
        out.write('\n')
    Path(out.name).replace(task_dir / 'state.json')


def find_task_dir(start: Path) -> Path:
    for root in (start.resolve(), *start.resolve().parents):
        if (root / '.git').exists():
            tasks = root / '.ai' / 'tasks'
            dirs = sorted(p for p in tasks.iterdir() if p.is_dir()) if tasks.is_dir() else []
            if len(dirs) == 1:
                return dirs[0]
            raise CdxError(3, 'task が未作成または複数ある。--task を指定する')
    raise CdxError(3, 'worktree が見つからない。--task を指定する')


def round_dir(task_dir: Path, n: int) -> Path:
    return task_dir / 'rounds' / f'{n:02d}'


@contextmanager
def lock(task_dir: Path):
    # state.json は rename するので、安定した task ディレクトリをロックする。
    fd = os.open(task_dir, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CdxError(3, '別の cdx run が準備中') from exc
        yield
    finally:
        os.close(fd)
