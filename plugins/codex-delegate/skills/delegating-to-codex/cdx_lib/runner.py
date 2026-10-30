from __future__ import annotations

import shutil
import subprocess


class CdxError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Runner:
    def __init__(self, env=None):
        self.env = env

    def run(self, argv, cwd=None, input=None, env=None):
        return subprocess.run(argv, cwd=cwd, input=input, env=env or getattr(self, 'env', None),
                              capture_output=True, text=True)

    def which(self, name):
        env = getattr(self, 'env', None)
        return shutil.which(name, path=env.get('PATH') if env is not None else None)

    def stream(self, argv, cwd, input, stderr, on_line):
        with subprocess.Popen(argv, cwd=cwd, stdin=input, stdout=subprocess.PIPE,
                              stderr=stderr, text=True, encoding='utf-8', errors='replace',
                              env=getattr(self, 'env', None)) as process:
            for line in process.stdout:
                on_line(line)
            return process.wait()


def checked(runner, argv, cwd=None):
    result = runner.run(argv, cwd=cwd)
    if result.returncode:
        raise CdxError(1, f'{argv[0]} 失敗: {result.stderr.strip()}')
    return result.stdout.strip()
