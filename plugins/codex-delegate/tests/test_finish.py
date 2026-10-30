from support import FakesCase
from cdx_lib import state


class FinishTests(FakesCase):
    def ready(self, approved=True):
        code, data = self.invoke('run', '--task', str(self.task), '--wait')
        self.assertEqual(code, 0, data)
        if approved:
            (state.round_dir(self.task, 1) / 'REVIEW.md').write_text('Status: APPROVED\n')

    def test_finish_requires_latest_approved(self):
        self.ready(approved=False)
        before = self.git('rev-parse', 'HEAD', cwd=self.wt)
        review = state.round_dir(self.task, 1) / 'REVIEW.md'
        # REVIEW 欠落、差し戻し、古いラウンドの承認を順に拒否する。
        for kind in ('missing', 'changes', 'older'):
            with self.subTest(kind=kind):
                if kind == 'changes':
                    review.write_text('Status: CHANGES_REQUESTED\n')
                elif kind == 'older':
                    self.invoke('fix', '--task', str(self.task))
                    review.write_text('Status: APPROVED\n')
                code, _ = self.invoke('finish', '--task', str(self.task), '-m', '禁止されるコミット')
                self.assertEqual(code, 3)
                self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.wt), before)

    def test_finish_commits_and_cleans_terminals(self):
        self.ready()
        (self.wt / 'tracked.txt').write_text('changed\n')
        (self.wt / 'new.txt').write_text('new content\n')
        own = self.terminal('owned-live')
        unrelated = self.terminal('unrelated-live')
        st = state.load(self.task)
        st.terminals = ['owned-live']
        state.save(self.task, st)
        code, data = self.invoke('finish', '--task', str(self.task), '-m', '実装完了')
        self.assertEqual(code, 0, data)
        self.assertEqual(data['commit'], self.git('rev-parse', 'HEAD', cwd=self.wt))
        self.assertEqual(data['branch'], st.branch)
        self.assertEqual(self.git('log', '-1', '--format=%s', cwd=self.wt), '実装完了')
        self.assertEqual(self.git('show', 'HEAD:new.txt', cwd=self.wt), 'new content')
        self.assertEqual(self.git('ls-files', '.ai', cwd=self.wt), '')
        patch = (self.task / 'final/diff.patch').read_text()
        self.assertIn('+changed', patch)
        self.assertIn('+new content', patch)
        self.assertIn('new.txt', (self.task / 'final/status.txt').read_text())
        self.assertEqual(state.load(self.task).phase, 'finished')
        self.assertEqual(state.load(self.task).terminals, [])
        self.assertFalse(own.exists())
        self.assertTrue(unrelated.exists())
        self.assertIn(['kill', 'owned-live'], self.hc_calls())
        self.assertNotIn(['kill', 'unrelated-live'], self.hc_calls())
        self.assertTrue(data['next_step'])

    def test_abort_records_final(self):
        before = self.git('rev-parse', 'HEAD', cwd=self.wt)
        (self.wt / 'untracked.txt').write_text('abort content\n')
        own = self.terminal('abort-owned')
        st = state.load(self.task)
        st.terminals = ['abort-owned']
        state.save(self.task, st)
        code, data = self.invoke('abort', '--task', str(self.task))
        self.assertEqual(code, 0, data)
        self.assertEqual(state.load(self.task).phase, 'aborted')
        self.assertIn('+abort content', (self.task / 'final/diff.patch').read_text())
        self.assertTrue((self.task / 'final/status.txt').is_file())
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.wt), before)
        self.assertFalse(own.exists())
        self.assertEqual(state.load(self.task).terminals, [])

    def test_cleanup_guards(self):
        code, _ = self.invoke('cleanup', '--task', str(self.task), '--force')
        self.assertEqual(code, 3)
        self.assertTrue(self.wt.exists())
        st = state.load(self.task)
        st.phase, st.terminals = 'aborted', ['still-live']
        self.terminal('still-live')
        state.save(self.task, st)
        code, _ = self.invoke('cleanup', '--task', str(self.task), '--force')
        self.assertEqual(code, 3)
        self.assertTrue(self.wt.exists())

    def test_cleanup_removes_worktree_and_branch(self):
        self.ready()
        (self.wt / 'tracked.txt').write_text('completed\n')
        code, data = self.invoke('finish', '--task', str(self.task), '-m', 'fixture 完了')
        self.assertEqual(code, 0, data)
        st = state.load(self.task)
        code, _ = self.invoke('cleanup', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertTrue(self.wt.exists())
        self.git('merge', '--ff-only', st.branch)
        other = self.root / 'other-worktree'
        self.git('worktree', 'add', '-b', 'other', str(other))
        unrelated = self.terminal('unrelated')
        code, data = self.invoke('cleanup', '--task', str(self.task))
        self.assertEqual(code, 0, data)
        self.assertFalse(self.wt.exists())
        self.assertNotIn(str(self.wt), self.git('worktree', 'list', '--porcelain'))
        self.assertEqual(self.git('branch', '--list', st.branch), '')
        self.assertTrue(other.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(self.git('branch', '--list', '--format=%(refname:short)', 'other'), 'other')

    def test_cleanup_force_aborted(self):
        (self.wt / 'tracked.txt').write_text('discarded\n')
        st = state.load(self.task)
        self.invoke('abort', '--task', str(self.task))
        code, data = self.invoke('cleanup', '--task', str(self.task), '--force')
        self.assertEqual(code, 0, data)
        self.assertFalse(self.wt.exists())
        self.assertEqual(self.git('branch', '--list', st.branch), '')

    def test_wait_does_not_reopen_finished_or_aborted(self):
        self.ready()
        (self.wt / 'tracked.txt').write_text('done\n')
        self.invoke('finish', '--task', str(self.task), '-m', 'fixture 完了')
        code, _ = self.invoke('wait', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertEqual(state.load(self.task).phase, 'finished')
        # 中止済みの task も wait では review に戻さない。
        st = state.load(self.task)
        st.phase = 'aborted'
        state.save(self.task, st)
        code, _ = self.invoke('wait', '--task', str(self.task))
        self.assertEqual(code, 3)
        self.assertEqual(state.load(self.task).phase, 'aborted')
