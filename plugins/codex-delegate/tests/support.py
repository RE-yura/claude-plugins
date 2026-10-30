from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'delegating-to-codex'
sys.path.insert(0, str(SKILL))
from cdx_lib.cli import main
from cdx_lib.runner import Runner


class FakeRunner(Runner):
    def __init__(self, hc='0.1.14', codex='0.164.0', core='0.1.14'):
        self.hc, self.codex, self.core = hc, codex, core
        self.calls = []

    def which(self, name):
        return '/fake/' + name if name in ('hc', 'codex') else super().which(name)

    def run(self, argv, cwd=None, input=None, env=None):
        self.calls.append(argv)
        if argv == ['hc', '--version']:
            return subprocess.CompletedProcess(argv, 0, 'hc ' + self.hc, '')
        if argv == ['codex', '--version']:
            return subprocess.CompletedProcess(argv, 0, 'codex-cli ' + self.codex, '')
        if argv == ['hc', 'server', 'status', '--json']:
            return subprocess.CompletedProcess(argv, int(self.core == 'down'),
                                               json.dumps({'version': self.core}), '')
        if argv[0] in ('hc', 'codex'):
            raise AssertionError('予期しない実コマンド: ' + repr(argv))
        return super().run(argv, cwd=cwd, input=input, env=env)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cdx-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'CDX Test')
        self.git('config', 'user.email', 'cdx@example.invalid')
        self.git('config', 'core.hooksPath', '/dev/null')
        self.git('config', 'commit.gpgsign', 'false')
        (self.repo / 'tracked.txt').write_text('initial\n')
        self.git('add', 'tracked.txt')
        self.git('commit', '-m', 'fixture')
        self.runner = FakeRunner()
        self.now = datetime(2026, 10, 31, 2, 31, 11, tzinfo=timezone.utc)
        self.env = dict(os.environ)
        self.env.pop('HC_TERMINAL_ID', None)

    def git(self, *args, cwd=None):
        result = subprocess.run(['git', *args], cwd=cwd or self.repo,
                                text=True, capture_output=True, check=True)
        return result.stdout.strip()

    def invoke(self, *args, runner=None, now=None, env=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args), runner=runner or self.runner,
                        now=now or self.now, env=self.env if env is None else env)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1, output.getvalue())
        return code, json.loads(lines[0])

    def start(self, **kwargs):
        code, data = self.invoke('start', '--repo', str(self.repo), '--name', 'example', **kwargs)
        self.assertEqual(code, 0, data)
        self.task = Path(data['task_dir'])
        self.wt = Path(data['worktree'])
        return data


class FakesCase(RepoCase):
    def setUp(self):
        super().setUp()
        self.env.update(PATH=str(SKILL.parents[1] / 'tests/fakes') + os.pathsep + self.env['PATH'],
                        FAKE_HC_DIR=str(self.root / 'hc'),
                        FAKE_CODEX_CALLS=str(self.root / 'codex-calls.jsonl'))
        self.runner = Runner(env=self.env)
        self.start()

    def hc_calls(self):
        path = self.root / 'hc/calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()]

    def terminal(self, name, live=True):
        path = self.root / 'hc' / (name + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'name': name, 'address': name, 'parent': None,
                                   'state': 'live' if live else 'finished', 'exit_code': None if live else 0}))
        return path
