import contextlib
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import FakeRunner, RepoCase, SKILL
from cdx_lib import compat, state
from cdx_lib.cli import main
from cdx_lib.runner import CdxError


class StartTests(RepoCase):
    def test_task_id_uses_local_time(self):
        local = datetime(2026, 10, 31, 2, 31, 11, tzinfo=timezone(timedelta(hours=9)))
        data = self.start(now=local)
        self.assertEqual(data['branch'], 'ai/20261031-023111-example')
        self.assertEqual(state.load(self.task).created_at, '2026-10-31T02:31:11+09:00')

    def test_default_clock_uses_local_time(self):
        local = datetime(2026, 10, 31, 2, 31, 11)
        utc = datetime(2026, 10, 30, 17, 31, 11, tzinfo=timezone.utc)
        output = io.StringIO()
        try:
            with patch.dict(os.environ, {'TZ': 'Asia/Tokyo'}):
                time.tzset()
                with patch('cdx_lib.cli.datetime', wraps=datetime) as clock:
                    clock.now.side_effect = lambda tz=None: local if tz is None else utc.astimezone(tz)
                    with contextlib.redirect_stdout(output):
                        code = main(['start', '--repo', str(self.repo), '--name', 'local'],
                                    runner=self.runner, env=self.env)
                data = json.loads(output.getvalue())
                self.assertEqual(code, 0, data)
                self.assertEqual(data['branch'], 'ai/20261031-023111-local')
                self.assertEqual(state.load(Path(data['task_dir'])).created_at, '2026-10-31T02:31:11+09:00')
        finally:
            time.tzset()

    def test_entry_rejects_old_python(self):
        stub = ('import runpy, sys; sys.version_info = (3, 9, 6); '
                'runpy.run_path(sys.argv[1], run_name="__main__")')
        result = subprocess.run([sys.executable, '-c', stub, str(SKILL / 'cdx'), '--help'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), {'error': 'cdx は Python 3.11 以上が必要 (今は 3.9)'})

    def test_start_creates_worktree_state_and_exclude(self):
        data = self.start(env=dict(self.env, HC_TERMINAL_ID='caller'))
        self.assertEqual(data['mode'], 'child')
        self.assertEqual(data['branch'], 'ai/20261031-023111-example')
        self.assertEqual(self.wt, self.root / 'worktrees' / '20261031-023111-example')
        st = state.load(self.task)
        self.assertEqual((st.phase, st.round, st.caller_terminal), ('planning', 1, 'caller'))
        self.assertEqual(st.base, self.git('rev-parse', 'HEAD'))
        self.assertTrue((self.task / 'PLAN.md').read_text().startswith('#'))
        self.assertTrue((self.task / 'rounds').is_dir())
        self.assertEqual(self.git('branch', '--show-current', cwd=self.wt), data['branch'])
        state.save(self.task, st)
        self.assertEqual(state.load(self.task), st)
        self.assertEqual(state.round_dir(self.task, 3), self.task / 'rounds' / '03')
        code, second = self.invoke('start', '--repo', str(self.repo), now=self.now + timedelta(seconds=1))
        self.assertEqual((code, second['mode']), (0, 'hidden'))
        exclude = self.git('rev-parse', '--git-path', 'info/exclude', cwd=self.wt)
        exclude_path = self.wt / exclude
        self.assertEqual(exclude_path.read_text().splitlines().count('.ai/'), 1)
        self.assertEqual(self.git('status', '--porcelain', cwd=self.wt), '')
        code, status = self.invoke('status', '--task', str(self.task))
        self.assertEqual((code, status['phase'], status['round']), (0, 'planning', 1))
        self.assertEqual(status['round_files'], [])

    def test_start_refuses_existing_path(self):
        self.start()
        code, data = self.invoke('start', '--repo', str(self.repo), '--name', 'example')
        self.assertEqual(code, 3, data)
        self.assertEqual(len(self.git('worktree', 'list', '--porcelain').split('worktree ')), 3)

    def test_find_task_dir_from_worktree_subdir(self):
        self.start()
        subdir = self.wt / 'src' / 'nested'
        subdir.mkdir(parents=True)
        self.assertEqual(state.find_task_dir(subdir), self.task)
        (self.wt / '.ai/tasks/other').mkdir()
        with self.assertRaises(CdxError) as ctx:
            state.find_task_dir(subdir)
        self.assertEqual(ctx.exception.code, 3)
        with self.assertRaises(CdxError):
            state.find_task_dir(self.repo)

    def test_compat_ranges(self):
        for hc, codex, good in [('0.1.14', '0.164.0', True), ('0.2.0', '0.164.0', False),
                                ('0.1.14', '0.163.9', False), ('0.1.14', '0.166.0', True)]:
            with self.subTest(hc=hc, codex=codex):
                self.assertEqual(compat.check(FakeRunner(hc=hc, codex=codex)) == [], good)
        code, _ = self.invoke('start', '--repo', str(self.repo), runner=FakeRunner(hc='0.2.0'))
        self.assertEqual(code, 3)
        code, _ = self.invoke('start', '--repo', str(self.repo), '--allow-untested',
                              runner=FakeRunner(hc='0.2.0'))
        self.assertEqual(code, 0)

    def test_doctor_reports_project_scope(self):
        config = self.root / 'claude'
        (config / 'plugins').mkdir(parents=True)
        (config / 'plugins/installed_plugins.json').write_text(json.dumps({'version': 2, 'plugins': {
            'codex-delegate@re-yura': [{'scope': 'user'}, {'scope': 'project', 'projectPath': '/repo'}],
            'other@re-yura': [{'scope': 'project'}]}}))
        code, data = self.invoke('doctor', env=dict(self.env, CLAUDE_CONFIG_DIR=str(config)))
        self.assertEqual(code, 3, data)
        self.assertFalse(data['ok'])
        self.assertEqual(data['duplicate_scopes'], [{'scope': 'project', 'projectPath': '/repo'}])
        self.assertEqual(data['hc'], '0.1.14')

    def test_doctor_core_checks(self):
        for core, expected in [('0.1.14', True), ('down', False), ('0.1.13', False)]:
            with self.subTest(core=core):
                code, data = self.invoke('doctor', runner=FakeRunner(core=core),
                                         env=dict(self.env, CLAUDE_CONFIG_DIR=str(self.root / 'empty')))
                self.assertEqual(data['ok'], expected)
                self.assertEqual(code, 0 if expected else 3)
                self.assertEqual(data['hc_core'], None if core == 'down' else core)
                if not expected:
                    self.assertTrue(data['problems'])

    def test_start_rejects_invalid_name(self):
        code, _ = self.invoke('start', '--repo', str(self.repo), '--name', '../escape')
        self.assertEqual(code, 3)
        self.assertFalse((self.root / 'worktrees').exists())

    def test_doctor_reports_malformed_plugin_registry(self):
        config = self.root / 'claude'
        (config / 'plugins').mkdir(parents=True)
        registry = config / 'plugins/installed_plugins.json'
        for text in ('not json', '[]', '{"plugins":{"codex-delegate@re-yura":[null]}}'):
            with self.subTest(text=text):
                registry.write_text(text)
                code, data = self.invoke('doctor', env=dict(self.env, CLAUDE_CONFIG_DIR=str(config)))
                self.assertEqual(code, 3, data)
                self.assertFalse(data['ok'])
                self.assertTrue(data['problems'])
