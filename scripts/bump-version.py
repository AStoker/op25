#!/usr/bin/env python3
"""Set — or verify — the one version number this project has.

Three files carry it and they must agree, because two of them are read by
machines that fail unhelpfully when they disagree:

  addons/op25/config.yaml   what Supervisor pulls. `.github/workflows/addon.yml`
                            refuses to publish unless this equals the release
                            tag, so a stale value here means no image at all.
  addons/op25/CHANGELOG.md  what the add-on store shows the user. A release with
                            no section is a release nobody can read.
  op25/.../www/app/package.json  baked into the UI at build time and shown in
                            the About dialog, which is how you tell what a
                            running install actually is.

Usage:
    scripts/bump-version.py 0.0.5     # set all three, stub the changelog
    scripts/bump-version.py --check   # verify they agree (used by CI)
    scripts/bump-version.py --show    # print the current version

Deliberately does no git work. Tagging and releasing are the steps that are
awkward to undo, and the release is what triggers the image build — see the
next-steps block this prints on a successful bump.

stdlib only, and no PyYAML: this has to run on a bare macOS python3 as well as
on a CI runner, and the fields it touches are one-line scalars.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG_YAML = ROOT / 'addons' / 'op25' / 'config.yaml'
CHANGELOG   = ROOT / 'addons' / 'op25' / 'CHANGELOG.md'
PACKAGE_JSON = ROOT / 'op25' / 'gr-op25_repeater' / 'www' / 'app' / 'package.json'

# Home Assistant compares add-on versions with AwesomeVersion, which copes with
# a lot, but the workflow's tag check is a plain string compare — so keep it to
# the shape a `vX.Y.Z` tag strips down to.
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')

# `version: "0.0.3"` — anchored so it cannot match a version key nested in some
# other block further down the file.
CONFIG_VERSION_RE = re.compile(r'^version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
PACKAGE_VERSION_RE = re.compile(r'^(\s*)"version":\s*"([^"]+)"', re.MULTILINE)
CHANGELOG_HEADING_RE = re.compile(r'^## +(\S+)', re.MULTILINE)

STUB = '- TODO: describe this release before publishing it.'


def fail(msg: str) -> None:
    sys.stderr.write('error: %s\n' % msg)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def read_config_version() -> str:
    m = CONFIG_VERSION_RE.search(CONFIG_YAML.read_text())
    if not m:
        fail('no top-level `version:` in %s' % CONFIG_YAML)
    return m.group(1)


def read_package_version() -> str:
    m = PACKAGE_VERSION_RE.search(PACKAGE_JSON.read_text())
    if not m:
        fail('no `"version":` in %s' % PACKAGE_JSON)
    return m.group(2)


def changelog_versions() -> list[str]:
    return CHANGELOG_HEADING_RE.findall(CHANGELOG.read_text())


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_config_version(version: str) -> None:
    text = CONFIG_YAML.read_text()
    # Quoted, always: bare 1.10 is a YAML float and would reach Supervisor as
    # "1.1".
    CONFIG_YAML.write_text(
        CONFIG_VERSION_RE.sub('version: "%s"' % version, text, count=1))


def write_package_version(version: str) -> None:
    text = PACKAGE_JSON.read_text()
    # Rewritten in place rather than through json.dump, which would reformat
    # and reorder the whole file for a two-character change.
    PACKAGE_JSON.write_text(
        PACKAGE_VERSION_RE.sub(r'\1"version": "%s"' % version, text, count=1))


def add_changelog_section(version: str) -> bool:
    """Insert a stub section for *version*. Returns False if it already exists."""
    text = CHANGELOG.read_text()
    if version in changelog_versions():
        return False

    lines = text.splitlines(keepends=True)
    # Insert above the first existing section, so the newest release stays at
    # the top where the add-on store shows it.
    for i, line in enumerate(lines):
        if CHANGELOG_HEADING_RE.match(line):
            insert_at = i
            break
    else:
        insert_at = len(lines)

    section = '## %s\n\n%s\n\n' % (version, STUB)
    CHANGELOG.write_text(''.join(lines[:insert_at]) + section + ''.join(lines[insert_at:]))
    return True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_check() -> int:
    """Verify the three files agree. Silent success, loud specifics on failure."""
    config  = read_config_version()
    package = read_package_version()
    log     = changelog_versions()

    problems: list[str] = []
    if config != package:
        problems.append(
            'config.yaml says %s but package.json says %s '
            '(run scripts/bump-version.py %s)' % (config, package, config))
    if config not in log:
        problems.append(
            'CHANGELOG.md has no `## %s` section — the add-on store would show '
            'this release with no notes' % config)
    if not VERSION_RE.match(config):
        problems.append(
            'version %r is not X.Y.Z; the release workflow compares it to the '
            'git tag as a plain string' % config)

    if problems:
        for p in problems:
            sys.stderr.write('error: %s\n' % p)
        return 1

    print('version %s is consistent across config.yaml, CHANGELOG.md and package.json'
          % config)
    return 0


def cmd_bump(version: str) -> int:
    if version.startswith('v'):
        version = version[1:]          # accept the tag spelling
    if not VERSION_RE.match(version):
        fail('version must be X.Y.Z (got %r)' % version)

    current = read_config_version()
    if version == current:
        print('already at %s' % version)
    else:
        print('%s → %s' % (current, version))

    write_config_version(version)
    write_package_version(version)
    stubbed = add_changelog_section(version)

    print('  addons/op25/config.yaml')
    print('  op25/gr-op25_repeater/www/app/package.json')
    print('  addons/op25/CHANGELOG.md%s' % (' (new section, stubbed)' if stubbed
                                            else ' (section already present)'))

    if stubbed:
        print('\nWrite the changelog section before releasing — `--check` fails '
              'while it is missing, and the store shows it to users.')

    print("""
The UI carries this version too, so rebuild the committed artifact:

    cd op25/gr-op25_repeater/www/app && yarn build

Then, once the notes are written:

    git commit -am 'chore(addon): bump to %(v)s'
    git push
    git tag v%(v)s && git push origin v%(v)s
    gh release create v%(v)s --generate-notes    # this is what builds the image

Publishing the release is the trigger — a tag alone builds nothing, and editing
an existing release does not re-fire it.""" % {'v': version})
    return 0


def cmd_show() -> int:
    print(read_config_version())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Set or verify the project version.',
        epilog='With no arguments, --check is assumed.')
    parser.add_argument('version', nargs='?', help='new version, X.Y.Z')
    parser.add_argument('--check', action='store_true',
                        help='verify every file agrees; exit 1 if not')
    parser.add_argument('--show', action='store_true',
                        help='print the current version and exit')
    args = parser.parse_args()

    if args.show:
        return cmd_show()
    if args.version:
        if args.check:
            fail('--check takes no version argument')
        return cmd_bump(args.version)
    return cmd_check()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
