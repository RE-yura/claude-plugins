import json
import os
import shutil
import subprocess

from support import RepoCase, SKILL


def ci_script(step):
    workflow = (SKILL.parents[3] / '.github/workflows/ci.yml').read_text()
    tail = workflow.split(f'        id: {step}\n', 1)[1].split('        run: |\n', 1)[1]
    lines = []
    for line in tail.splitlines():
        if line and not line.startswith('          '):
            break
        lines.append(line[10:])
    return '\n'.join(lines)


class CiTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.plugin = self.repo / 'plugins/codex-delegate'
        self.manifest = self.plugin / '.claude-plugin/plugin.json'
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({'name': 'codex-delegate', 'version': '1.0.0'}))
        (self.plugin / 'example.py').write_text('print("fixture")\n')

    def save(self, message):
        self.git('add', '-A')
        self.git('commit', '-m', message)

    def version_check(self, event='push', base=''):
        return subprocess.run(['bash', '-c', ci_script('version')], cwd=self.repo,
                              env=dict(os.environ, EVENT_NAME=event, PR_BASE=base),
                              capture_output=True, text=True)

    def test_version_gate_initial_change_and_bump(self):
        self.save('プラグイン追加')
        self.assertEqual(self.version_check().returncode, 0)
        base = self.git('rev-parse', 'HEAD')
        (self.plugin / 'example.py').write_text('print("changed")\n')
        self.save('版を変えずに実装変更')
        self.assertEqual(self.version_check().returncode, 1)
        (self.repo / 'README.md').write_text('文書更新\n')
        self.save('プラグイン外のみ更新')
        self.assertEqual(self.version_check().returncode, 0)
        self.assertEqual(self.version_check('pull_request', base).returncode, 1)
        self.manifest.write_text(json.dumps({'name': 'codex-delegate', 'version': '1.0.1'}))
        self.save('版を更新')
        self.assertEqual(self.version_check().returncode, 0)
        self.assertEqual(self.version_check('pull_request', base).returncode, 0)

    def test_manifest_gate(self):
        marketplace = self.repo / '.claude-plugin/marketplace.json'
        marketplace.parent.mkdir()
        good = {'name': 're-yura', 'plugins': [
            {'name': 'codex-delegate', 'source': './plugins/codex-delegate'}]}
        marketplace.write_text(json.dumps(good))
        schema = self.plugin / 'skills/delegating-to-codex/templates/done.schema.json'
        schema.parent.mkdir(parents=True)
        shutil.copyfile(SKILL / 'templates/done.schema.json', schema)

        def check():
            return subprocess.run(['bash', '-c', ci_script('manifests')], cwd=self.repo,
                                  capture_output=True, text=True).returncode

        self.assertEqual(check(), 0)
        extra = self.repo / 'plugins/unlisted'
        extra.mkdir()
        self.assertNotEqual(check(), 0)
        extra.rmdir()
        self.manifest.write_text('{"name":"codex-delegate"}')
        self.assertNotEqual(check(), 0)
        self.manifest.write_text('{"name":"codex-delegate","version":"1.0.0"}')
        good['plugins'][0]['source'] = './wrong'
        marketplace.write_text(json.dumps(good))
        self.assertNotEqual(check(), 0)
