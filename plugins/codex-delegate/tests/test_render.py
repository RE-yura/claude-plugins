import contextlib
import io
from pathlib import Path
from unittest.mock import patch
import unittest

import support
from cdx_lib.cli import main
from cdx_lib import render


class RenderTests(unittest.TestCase):
    def test_render_lines(self):
        cases = [
            ({'type': 'thread.started', 'thread_id': 'abc'}, 'session abc'),
            ({'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'ls src'}}, '$ ls src'),
            ({'type': 'item.completed', 'item': {'type': 'command_execution', 'exit_code': 2}}, '  → exit 2'),
            ({'type': 'item.completed', 'item': {'type': 'file_change', 'changes': [
                {'path': str(Path.cwd() / 'src/a.py'), 'kind': 'update'},
                {'path': 'b.py', 'kind': 'add'}]}}, 'edit update src/a.py\nedit add b.py'),
            ({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'hello\nworld'}}, 'hello'),
            ({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'x' * 201}}, 'x' * 200),
            ({'type': 'turn.completed', 'usage': {'input_tokens': 42, 'output_tokens': 7,
                                                'cached_input_tokens': 1, 'reasoning_output_tokens': 2}},
             'done (in 42 / out 7 tokens)'),
            ({'type': 'error', 'message': 'bad'}, 'error: bad'),
            ({'type': 'turn.failed', 'error': {'message': 'failed'}}, 'error: failed'),
        ]
        for event, want in cases:
            with self.subTest(event=event):
                self.assertEqual(render.line(event), want)

    def test_render_ignores_unknown(self):
        stream = 'bad json\n{"type":"future"}\n[]\n{"type":"item.completed","item":null}\n'
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(stream)), contextlib.redirect_stdout(output):
            self.assertEqual(main(['render']), 0)
        self.assertEqual(output.getvalue(), '')
        self.assertIsNone(render.line({'type': 'turn.started'}))
