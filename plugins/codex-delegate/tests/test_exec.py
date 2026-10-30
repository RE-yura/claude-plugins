import contextlib
import io
import json
import os

from support import RepoCase, SKILL
from cdx_lib import state


class ExecTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.env['PATH'] = str(SKILL.parents[1] / 'tests/fakes') + os.pathsep + self.env['PATH']
        self.env['FAKE_CODEX_CALLS'] = str(self.root / 'codex-calls.jsonl')
        self.current = state.round_dir(self.task, 1)
        self.current.mkdir()
        (self.current / 'PROMPT.md').write_text('テスト依頼\n')

    def execute(self, n=1):
        from cdx_lib.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['_exec', str(self.task), str(n)], env=self.env)
        return code, output.getvalue()

    def calls(self):
        return [json.loads(line) for line in (self.root / 'codex-calls.jsonl').read_text().splitlines()]

    def test_exec_round1_argv_and_files(self):
        code, output = self.execute()
        self.assertEqual(code, 0, output)
        want = ['exec', '--json', '-C', str(self.wt), '-o', str(self.current / 'DONE.json'),
                '--output-schema', str(SKILL / 'templates/done.schema.json'), '-']
        call = self.calls()[0]
        self.assertEqual(call['argv'], want)
        self.assertEqual(call['input'], 'テスト依頼\n')
        self.assertEqual(call['cwd'], str(self.wt))
        self.assertIn('session thread-123', output)
        self.assertIn('done (in 42 / out 7 tokens)', output)
        self.assertIn('not-json', (self.current / 'events.jsonl').read_text())
        self.assertEqual((self.current / 'exit_code').read_text().strip(), '0')
        self.assertEqual(json.loads((self.current / 'DONE.json').read_text())['status'], 'done')
        self.assertEqual((self.current / 'stderr.txt').read_text(), '')
        self.assertEqual(state.load(self.task).thread_id, 'thread-123')

    def test_exec_resume_argv(self):
        st = state.load(self.task)
        st.round, st.thread_id = 2, 'existing-thread'
        state.save(self.task, st)
        current = state.round_dir(self.task, 2)
        current.mkdir()
        (current / 'PROMPT.md').write_text('修正依頼')
        code, output = self.execute(2)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.calls()[0]['argv'], ['exec', 'resume', 'existing-thread', '--json',
                         '-o', str(current / 'DONE.json'), '--output-schema',
                         str(SKILL / 'templates/done.schema.json'), '-'])
        self.assertEqual(state.load(self.task).thread_id, 'existing-thread')

    def test_exec_records_nonzero_exit(self):
        self.env['FAKE_CODEX_SCENARIO'] = 'fail'
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual((self.current / 'exit_code').read_text().strip(), '1')
        self.assertIn('fake codex failed', (self.current / 'stderr.txt').read_text())
        self.assertFalse((self.current / 'DONE.json').exists())
