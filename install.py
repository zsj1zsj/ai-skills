"""Install the reviewed payload only; no network, credentials or settings changes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys


def safe(path):
    path = Path(os.path.abspath(path))
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('Network/device paths are not supported')
    for node in (path, *path.parents):
        if node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
            raise ValueError(f'Symlink/junction is not supported: {node}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path(os.environ.get('PI_CODING_AGENT_DIR', str(Path.home() / '.pi' / 'agent'))))
    parser.add_argument('--dry-run', action='store_true', help='Verify and list changes without writing')
    parser.add_argument('--overwrite', action='store_true', help='Back up and replace conflicting files')
    args = parser.parse_args()
    root = safe(Path(__file__).parent)
    target = safe(args.target)
    manifest = json.loads((root / 'payload-manifest.json').read_text(encoding='utf-8'))
    operations, conflicts = [], []
    for relative, digest in manifest['sha256'].items():
        parts = PurePosixPath(relative).parts
        if '\\' in relative or ':' in relative or relative.startswith('/') or any(x in ('', '.', '..') for x in relative.split('/')):
            raise ValueError(f'Invalid payload path: {relative}')
        if not (relative.startswith('skills/trip-plan/') or relative == 'extensions/trip-plan.ts' or relative in ['agents/' + n + '.md' for n in ('researcher', 'itinerary-synthesizer', 'itinerary-critic', 'itinerary-designer', 'itinerary-generator')]):
            raise ValueError(f'Unexpected install destination: {relative}')
        src, dst = safe(root / 'payload' / Path(*parts)), safe(target / Path(*parts))
        if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Payload checksum mismatch: {relative}')
        if dst.exists() and not dst.is_file():
            raise ValueError(f'Destination is not a file: {dst}')
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            print('UNCHANGED', relative)
            continue
        if dst.exists():
            conflicts.append((src, dst, relative))
        operations.append((src, dst, relative))
        print('REPLACE' if dst.exists() else 'ADD', relative)
    print('Target:', target)
    if args.dry_run:
        print(f'Dry run: {len(operations)} changes; {len(conflicts)} conflicts; no files written.')
        return 0
    if conflicts and not args.overwrite:
        print('Existing files differ. Review conflicts, then use --overwrite to back up and replace.', file=sys.stderr)
        return 2
    if conflicts:
        backup = safe(target / '.trip-plan-install-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        for _, dst, relative in conflicts:
            saved = safe(backup / (relative + '.bak'))
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, saved)
        print('Backup:', backup)
    for src, dst, _ in operations:
        safe(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f'Installed {len(operations)} files. Restart Pi or run /reload after prerequisites are configured.')
    print('This installer does NOT install Herdr/pi-herdr-agents, authenticate models or apply the optional Windows patch.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Install failed: {exc}', file=sys.stderr)
        sys.exit(2)
