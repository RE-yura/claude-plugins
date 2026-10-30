from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from support import FakesCase, SKILL
from cdx_lib import hc, state
from cdx_lib.cli import main


class RunTests(FakesCase):
    def test_round_times_use_local_time(self):
        local = datetime(2026, 10, 31, 2, 31, 11, tzinfo=timezone(timedelta(hours=9)))
        try:
            with patch.dict(os.environ, {'TZ': 'Asia/Tokyo'}):
                time.tzset()
                code, data = self.invoke('run', '--task', str(self.task), '--wait', now=local)
                self.assertEqual(code, 0, data)
                record = state.load(self.task).rounds[0]
                self.assertEqual(record['started_at'], '2026-10-31T02:31:11+09:00')
                self.assertTrue(record['ended_at'].endswith('+09:00'), record['ended_at'])
        finally:
            time.tzset()

    def run_wait(self):
        return self.invoke('run', '--task', str(self.task), '--wait')

    def review(self, text='Status: CHANGES_REQUESTED\n\n## Required fixes\n修正する。'):
        st = state.load(self.task)
        current = state.round_dir(self.task, st.round)
        (current / 'REVIEW.md').write_text(text)

    def test_run_wait_done(self):
        st = state.load(self.task)
        st.mode, st.caller_terminal = 'child', 'caller'
        state.save(self.task, st)
        code, data = self.run_wait()
        self.assertEqual((code, data['round'], data['status']), (0, 1, 'done'))
        self.assertEqual(data['terminal'], 'cdx-1031023111-r01')
        self.assertEqual(data['done']['status'], 'done')
        st = state.load(self.task)
        self.assertEqual((st.phase, st.thread_id, st.terminals), ('review', 'thread-123', []))
        self.assertEqual(st.rounds[0]['status'], 'done')
        self.assertEqual(st.rounds[0]['exit_code'], 0)
        self.assertTrue(st.rounds[0]['started_at'])
        self.assertTrue(st.rounds[0]['ended_at'])
        self.assertFalse((self.root / 'hc' / (data['terminal'] + '.json')).exists())
        run = next(call for call in self.hc_calls() if call[:1] == ['run'])
        self.assertEqual(run, ['run', '--bg', '--name', 'cdx-1031023111-r01', '--cwd', str(self.wt),
                              '--outlive-parent', '--no-notify', '--', sys.executable, str(SKILL / 'cdx'), '_exec',
                              str(self.task), '1'])
        prompt = (state.round_dir(self.task, 1) / 'PROMPT.md').read_text()
        self.assertIn('.ai/tasks/20261031-023111-example/PLAN.md', prompt)

    def test_run_uses_caller_interpreter(self):
        code, data = self.run_wait()
        self.assertEqual(code, 0, data)
        run = next(call for call in self.hc_calls() if call[:1] == ['run'])
        self.assertEqual(run[run.index('--') + 1:],
                         [sys.executable, str(SKILL / 'cdx'), '_exec', str(self.task), '1'])

    def test_run_wait_blocked(self):
        self.env['FAKE_CODEX_SCENARIO'] = 'blocked'
        code, data = self.run_wait()
        self.assertEqual((code, data['status']), (2, 'blocked'))
        self.assertEqual(state.load(self.task).phase, 'review')

    def test_wait_failed_round(self):
        self.env['FAKE_CODEX_SCENARIO'] = 'fail'
        code, data = self.run_wait()
        self.assertEqual((code, data['status'], data['done']), (1, 'failed', None))
        self.assertIn('fake codex failed', data['stderr_tail'])
        self.assertEqual(state.load(self.task).rounds[0]['status'], 'failed')
        self.assertEqual(state.load(self.task).terminals, [])

    def test_wait_saves_terminal_when_exec_died(self):
        code, data = self.invoke('run', '--task', str(self.task))
        self.assertEqual(code, 0, data)
        current = state.round_dir(self.task, 1)
        for name in ('exit_code', 'stderr.txt', 'DONE.json', 'events.jsonl'):
            (current / name).unlink()
        lines = [f'terminal line {n}' for n in range(205)] + ['Python import failed']
        self.env['FAKE_HC_SCREEN'] = '\n'.join(lines) + '\n'
        code, failed = self.invoke('wait', '--task', str(self.task))
        self.assertEqual((code, failed['status'], failed['done']), (1, 'failed', None))
        self.assertEqual((current / 'terminal.txt').read_text(), '\n'.join(lines[-200:]) + '\n')
        self.assertEqual(failed['stderr_tail'], '\n'.join(lines[-20:]))
        calls = self.hc_calls()
        self.assertLess(calls.index(['read', data['terminal'], '--lines', '200']),
                        calls.index(['rm', data['terminal']]))
        self.assertEqual(state.load(self.task).terminals, [])
        code, again = self.invoke('wait', '--task', str(self.task))
        self.assertEqual((code, again['stderr_tail']), (1, failed['stderr_tail']))

    def test_wait_prefers_stderr_when_exit_code_missing(self):
        self.invoke('run', '--task', str(self.task))
        current = state.round_dir(self.task, 1)
        (current / 'exit_code').unlink()
        (current / 'stderr.txt').write_text('stderr explains failure\n')
        self.env['FAKE_HC_SCREEN'] = 'terminal fallback\n'
        code, data = self.invoke('wait', '--task', str(self.task))
        self.assertEqual((code, data['stderr_tail']), (1, 'stderr explains failure'))
        self.assertEqual((current / 'terminal.txt').read_text(), 'terminal fallback\n')

    def test_wait_missing_done_and_nonzero_with_done_fail(self):
        for n, scenario in enumerate(('missing', 'nonzero_done'), 1):
            if n == 2:
                self.review()
                code, _ = self.invoke('fix', '--task', str(self.task))
                self.assertEqual(code, 0)
            self.env['FAKE_CODEX_SCENARIO'] = scenario
            code, data = self.run_wait()
            self.assertEqual((code, data['status']), (1, 'failed'), data)

    def test_run_refuses_duplicate(self):
        code, data = self.invoke('run', '--task', str(self.task))
        self.assertEqual(code, 0, data)
        code, _ = self.invoke('run', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertEqual(sum(call[:1] == ['run'] for call in self.hc_calls()), 1)
        self.invoke('wait', '--task', str(self.task))
        code, _ = self.invoke('run', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.review()
        self.invoke('fix', '--task', str(self.task))
        previous = 'earlier-live'
        self.terminal(previous)
        st = state.load(self.task)
        st.terminals.append(previous)
        st.rounds[0]['terminal'] = previous
        state.save(self.task, st)
        code, _ = self.invoke('run', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertEqual(sum(call[:1] == ['run'] for call in self.hc_calls()), 1)

    def test_retry_failed_round(self):
        self.env['FAKE_CODEX_SCENARIO'] = 'fail'
        code, _ = self.run_wait()
        self.assertEqual(code, 1)
        old = state.load(self.task).rounds[0]
        current = state.round_dir(self.task, 1)
        (current / 'PROMPT.md').write_text('Claude が編集した依頼\n')
        (current / 'DONE.json').write_text('{"status":"done"}')
        (current / 'terminal.txt').write_text('old terminal')
        code, _ = self.run_wait()
        self.assertEqual(code, 3)
        launch = hc.run_bg

        def check_files(*args):
            for name in ('events.jsonl', 'DONE.json', 'exit_code', 'stderr.txt', 'terminal.txt'):
                self.assertFalse((current / name).exists(), name)
            self.assertEqual((current / 'PROMPT.md').read_text(), 'Claude が編集した依頼\n')
            return launch(*args)

        self.env['FAKE_CODEX_SCENARIO'] = 'done'
        with patch('cdx_lib.hc.run_bg', side_effect=check_files):
            code, data = self.invoke('run', '--task', str(self.task), '--retry', '--wait')
        self.assertEqual((code, data['status'], data['round']), (0, 'done', 1))
        st = state.load(self.task)
        self.assertEqual((st.phase, st.round, st.terminals), ('review', 1, []))
        self.assertEqual(len(st.rounds), 1)
        attempts = st.rounds[0]['attempts']
        self.assertEqual([a['status'] for a in attempts], ['failed', 'done'])
        for field in ('terminal', 'started_at', 'ended_at', 'exit_code', 'status'):
            self.assertEqual(attempts[0][field], old[field])
        self.assertEqual((st.rounds[0]['status'], attempts[1]['exit_code']), ('done', 0))
        calls = [json.loads(line) for line in (self.root / 'codex-calls.jsonl').read_text().splitlines()]
        self.assertTrue(all(call['argv'][:2] == ['exec', '--json'] for call in calls))
        self.assertEqual(calls[1]['input'], 'Claude が編集した依頼\n')

    def test_retry_refused_when_not_failed(self):
        retry = ('run', '--task', str(self.task), '--retry')
        code, _ = self.invoke(*retry)
        self.assertEqual(code, 3)
        self.invoke('run', '--task', str(self.task))
        code, _ = self.invoke(*retry)
        self.assertEqual(code, 3)
        self.invoke('wait', '--task', str(self.task))
        code, _ = self.invoke(*retry)
        self.assertEqual(code, 3)
        self.review()
        self.invoke('fix', '--task', str(self.task))
        self.env['FAKE_CODEX_SCENARIO'] = 'blocked'
        self.run_wait()
        code, _ = self.invoke(*retry)
        self.assertEqual(code, 3)
        st = state.load(self.task)
        st.rounds[-1]['status'] = 'failed'
        st.terminals = [st.rounds[-1]['terminal']]
        state.save(self.task, st)
        for live in (True, False):
            self.terminal(st.terminals[0], live=live)
            code, _ = self.invoke(*retry)
            self.assertEqual(code, 3)
        self.assertEqual(sum(call[:1] == ['run'] for call in self.hc_calls()), 2)

    def test_retry_fix_round_uses_resume(self):
        self.run_wait()
        self.review()
        self.invoke('fix', '--task', str(self.task))
        self.env['FAKE_CODEX_SCENARIO'] = 'fail'
        code, _ = self.run_wait()
        self.assertEqual(code, 1)
        self.env['FAKE_CODEX_SCENARIO'] = 'done'
        code, data = self.invoke('run', '--task', str(self.task), '--retry', '--wait')
        self.assertEqual((code, data['round']), (0, 2))
        st = state.load(self.task)
        self.assertEqual([a['status'] for a in st.rounds[1]['attempts']], ['failed', 'done'])
        calls = [json.loads(line) for line in (self.root / 'codex-calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls[2]['argv'][:3], ['exec', 'resume', 'thread-123'])

    def test_run_requires_plan(self):
        (self.task / 'PLAN.md').write_text(' \n')
        code, _ = self.run_wait()
        self.assertEqual(code, 3)
        self.assertFalse(any(call[:1] == ['run'] for call in self.hc_calls()))

    def test_fix_creates_round_and_limit(self):
        self.run_wait()
        self.review('Status: APPROVED\n')
        code, _ = self.invoke('fix', '--task', str(self.task))
        self.assertEqual(code, 3)
        for n in (2, 3, 4):
            self.review()
            code, data = self.invoke('fix', '--task', str(self.task))
            self.assertEqual(code, 0, data)
            prompt = state.round_dir(self.task, n) / 'PROMPT.md'
            self.assertEqual(data['prompt'], str(prompt))
            self.assertIn(f'rounds/{n - 1:02d}/REVIEW.md', prompt.read_text())
            self.assertIn('Required fixes', prompt.read_text())
            self.run_wait()
        self.review()
        code, _ = self.invoke('fix', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertEqual(state.load(self.task).round, 4)
        self.assertFalse(state.round_dir(self.task, 5).exists())

    def test_fix_round_uses_resume(self):
        self.run_wait()
        self.review()
        self.invoke('fix', '--task', str(self.task))
        prompt = state.round_dir(self.task, 2) / 'PROMPT.md'
        prompt.write_text(prompt.read_text() + '\nClaude からの追記\n')
        code, data = self.run_wait()
        self.assertEqual(code, 0, data)
        calls = [json.loads(line) for line in (self.root / 'codex-calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls[1]['argv'][:3], ['exec', 'resume', 'thread-123'])
        self.assertIn('Claude からの追記', calls[1]['input'])

    def test_run_version_gate_and_wait_timeout(self):
        self.env['FAKE_CODEX_VERSION'] = '0.163.9'
        code, _ = self.run_wait()
        self.assertEqual(code, 3)
        self.env['FAKE_HC_WAIT'] = 'timeout'
        code, data = self.invoke('run', '--task', str(self.task), '--wait', '--allow-untested')
        self.assertEqual((code, data['status']), (0, 'done'))
        self.assertTrue(any(call[:1] == ['get'] for call in self.hc_calls()))

    def test_concurrent_run_starts_once(self):
        initial_load = state.load
        barrier, local = threading.Barrier(2), threading.local()

        def load(path):
            st = initial_load(path)
            if not getattr(local, 'loaded', False):
                local.loaded = True
                barrier.wait(timeout=5)
            return st

        def launch(_):
            return main(['run', '--task', str(self.task)], runner=self.runner, now=self.now, env=self.env)

        output = io.StringIO()
        with patch('cdx_lib.state.load', side_effect=load), contextlib.redirect_stdout(output):
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = list(pool.map(launch, range(2)))
        self.assertEqual(sorted(codes), [0, 3], output.getvalue())
        self.assertEqual(sum(call[:1] == ['run'] for call in self.hc_calls()), 1)
        self.assertEqual(len(state.load(self.task).rounds), 1)

    def test_wait_checks_finished_after_observation_error(self):
        self.env['FAKE_HC_WAIT'] = 'error'
        code, data = self.run_wait()
        self.assertEqual((code, data.get('status')), (0, 'done'), data)
        self.assertTrue(any(call[:1] == ['get'] for call in self.hc_calls()))
