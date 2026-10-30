from __future__ import annotations

import re

HC_SERIES = (0, 1)
CODEX_MIN = (0, 164, 0)


def inspect(runner):
    versions, problems = {}, []
    for name in ('hc', 'codex'):
        version = None
        if runner.which(name):
            result = runner.run([name, '--version'])
            match = re.search(r'\b(\d+\.\d+\.\d+)\b', result.stdout)
            if result.returncode == 0 and match:
                version = match[1]
        versions[name] = version
        if version is None:
            problems.append(f'{name} の版を確認できない')
            continue
        numbers = tuple(map(int, version.split('.')))
        if (name == 'hc' and numbers[:2] != HC_SERIES) or (name == 'codex' and numbers < CODEX_MIN):
            problems.append(f'{name} {version} は未検証。--allow-untested が必要')
    return versions, problems


def check(runner) -> list[str]:
    return inspect(runner)[1]
