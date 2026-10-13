"""Download verified CLI-nesting release assets without FreeCAD/Qt dependencies."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

REPOSITORY = 'ingussp/CLI-nesting'
LATEST_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_UNPACKED = 64 * 1024 * 1024
RECEIPT = 'installation.json'


class Cancelled(Exception):
    pass


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise Cancelled('Download cancelled')


@dataclass(frozen=True)
class Target:
    folder: str
    executable: str
    caption: str
    machine: str = 'x86_64'

    @property
    def asset(self):
        return 'clinesting-' + self.folder + '.tar.gz'


def target_platform(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {'amd64': 'x86_64', 'x64': 'x86_64', 'aarch64': 'arm64'}.get(machine, machine)
    if system == 'Windows' and arch == 'x86_64':
        return Target('windows-x86_64', 'clinesting.exe', 'Windows x64')
    if system == 'Linux' and arch in ('x86_64', 'arm64'):
        return Target('linux-x86_64' if arch == 'x86_64' else 'linux-aarch64',
                      'clinesting', 'Linux ' + ('x64' if arch == 'x86_64' else 'ARM64'), arch)
    if system == 'Darwin' and arch in ('x86_64', 'arm64'):
        return Target('macos-universal2', 'clinesting', 'macOS Universal 2', arch)
    raise ValueError('Unsupported platform: %s / %s' % (system, machine))


def version_key(value):
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)', str(value).strip())
    if not match:
        raise ValueError('Invalid release version: ' + str(value))
    parts = [int(x) for x in match.group(1).split('.')]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def digest(path):
    checksum = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            checksum.update(block)
    return checksum.hexdigest()


def open_url(url):
    request = Request(url, headers={'User-Agent': 'Nesting1st-Engine-Updater',
                                   'Accept': 'application/vnd.github+json' if url == LATEST_URL else 'application/octet-stream'})
    response = urlopen(request, timeout=15)
    # GitHub assets redirect to its HTTPS asset delivery service.
    destination = urlsplit(response.geturl())
    host = destination.hostname or ''
    if destination.scheme != 'https' or not (host in ('github.com', 'api.github.com') or host.endswith('.githubusercontent.com')):
        response.close()
        raise ValueError('Unexpected download redirect')
    return response


def latest_release(target, cancelled=None, opener=open_url):
    _check_cancel(cancelled)
    with opener(LATEST_URL) as response:
        data = response.read(1024 * 1024 + 1)
    _check_cancel(cancelled)
    if len(data) > 1024 * 1024:
        raise ValueError('Release metadata exceeds the size limit')
    release = json.loads(data.decode('utf-8'))
    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('No stable release is available')
    tag = release['tag_name']
    version_key(tag)
    matches = [asset for asset in release.get('assets', []) if asset.get('name') == target.asset]
    if len(matches) != 1:
        raise ValueError('No matching release asset: ' + target.asset)
    asset = matches[0]
    expected_url = 'https://github.com/' + REPOSITORY + '/releases/download/' + quote(tag, safe='') + '/' + target.asset
    if asset.get('browser_download_url') != expected_url:
        raise ValueError('Unexpected release asset URL')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', str(asset.get('digest', ''))):
        raise ValueError('The release asset has no SHA-256 digest')
    size = asset.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ARCHIVE:
        raise ValueError('Invalid release asset size')
    return dict(tag=tag, version=str(tag).lstrip('v'), asset=dict(asset), target=target)


def probe_version(executable):
    try:
        run = subprocess.run([str(executable), '-v'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        text = run.stdout.decode('utf-8', errors='replace').strip()
        match = re.fullmatch(r'clinesting\s+(v?\d+(?:\.\d+)*)', text)
        return match.group(1).lstrip('v') if run.returncode == 0 and match else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def installed_info(workbench, target, probe=probe_version):
    # Runtime also recognises macOS architecture-specific fallback binaries.
    executable = _installed_path(workbench, target)
    if executable is None:
        return dict(version=None, digest=None, executable=None)
    checksum = digest(executable)
    if target.executable != 'clinesting.exe' and not os.access(executable, os.X_OK):
        return dict(version=None, digest=checksum, executable=executable)
    try:
        receipt = json.loads((Path(executable).parent / RECEIPT).read_text(encoding='utf-8'))
        if receipt['platform'] == target.folder and receipt['sha256'] == checksum:
            version_key(receipt['version'])
            return dict(version=receipt['version'], digest=checksum, executable=executable)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(version=probe(executable), digest=checksum, executable=executable)


def needs_update(release, installed):
    return installed['version'] is None or version_key(release['version']) > version_key(installed['version'])


def _installed_path(workbench, target):
    from Nesting1stRuntime import executable_candidates
    system = 'Windows' if target.folder.startswith('windows') else 'Linux' if target.folder.startswith('linux') else 'Darwin'
    return next((path for path in executable_candidates(workbench, system, target.machine)
                 if os.path.isfile(path)), None)


def validate_binary(path, target):
    data = path.read_bytes()
    if target.folder == 'windows-x86_64':
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('Invalid Windows executable')
        offset = struct.unpack_from('<I', data, 60)[0]
        if offset + 24 > len(data) or data[offset:offset + 4] != b'PE\0\0' or struct.unpack_from('<H', data, offset + 4)[0] != 0x8664:
            raise ValueError('The Windows executable is not x64')
    elif target.folder.startswith('linux-'):
        if len(data) < 64 or data[:5] != b'\x7fELF\x02' or data[5] not in (1, 2):
            raise ValueError('Invalid 64-bit Linux executable')
        machine = struct.unpack_from('<H' if data[5] == 1 else '>H', data, 18)[0]
        if machine != (183 if target.folder == 'linux-aarch64' else 62):
            raise ValueError('The Linux executable has the wrong architecture')
    else:
        if len(data) < 8 or data[:4] not in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
            raise ValueError('Invalid macOS Universal 2 executable')
        count = struct.unpack_from('>I', data, 4)[0]
        width = 32 if data[:4] == b'\xca\xfe\xba\xbf' else 20
        if count < 2 or count > 16 or 8 + count * width > len(data):
            raise ValueError('Invalid macOS architecture table')
        architectures = set()
        for index in range(count):
            start = 8 + index * width
            architectures.add(struct.unpack_from('>I', data, start)[0])
            offset, size = struct.unpack_from('>QQ' if width == 32 else '>II', data, start + 8)
            if not size or offset + size > len(data):
                raise ValueError('Invalid macOS architecture slice')
        if not {0x01000007, 0x0100000c}.issubset(architectures):
            raise ValueError('The macOS executable must support Intel and Apple Silicon')


@dataclass
class PreparedEngine:
    root: Path
    target: Target
    receipt: dict
    previous_digest: str | None
    previous_executable: str | None

    def cleanup(self):
        root = self.root.resolve()
        if (self.root.name.startswith('.engine-download-') and not self.root.is_symlink()
                and root.parent == self.root.parent.resolve() and root.parent.name == 'clinesting'):
            shutil.rmtree(root, ignore_errors=True)


def _storage(workbench):
    root = Path(workbench).resolve()
    parent = (root / 'clinesting').resolve()
    if not parent.is_relative_to(root):
        raise ValueError('The engine directory is outside the workbench')
    return parent


def prepare_download(workbench, release, installed, cancelled=None, opener=open_url, probe=probe_version):
    target = release['target']
    parent = _storage(workbench)
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='.engine-download-', dir=parent))
    prepared = PreparedEngine(root, target, {}, installed['digest'], installed['executable'])
    try:
        archive_path = root / 'download.tar.gz'
        asset = release['asset']
        downloaded = 0
        with opener(asset['browser_download_url']) as response, archive_path.open('wb') as output:
            while True:
                _check_cancel(cancelled)
                block = response.read(65536)
                if not block:
                    break
                downloaded += len(block)
                if downloaded > asset['size'] or downloaded > MAX_ARCHIVE:
                    raise ValueError('Download exceeds its declared size')
                output.write(block)
        _check_cancel(cancelled)
        if downloaded != asset['size'] or digest(archive_path) != asset['digest'].split(':', 1)[1].lower():
            raise ValueError('Release download failed its size or SHA-256 check')
        payload = root / 'payload'
        payload.mkdir()
        total, count, executable_found = 0, 0, False
        prefix = 'clinesting-' + target.folder
        seen = set()
        with tarfile.open(archive_path, 'r:gz') as archive:
            for member in archive:
                _check_cancel(cancelled)
                count += 1
                total += member.size
                name = PurePosixPath(member.name)
                if (count > 256 or total > MAX_UNPACKED or member.size < 0 or
                        name.is_absolute() or '..' in name.parts or '\\' in member.name or ':' in member.name or
                        not name.parts or name.parts[0] != prefix or not (member.isfile() or member.isdir())):
                    raise ValueError('Invalid release archive entry: ' + member.name)
                if member.isdir():
                    continue
                relative = PurePosixPath(*name.parts[1:])
                if relative.as_posix() in seen:
                    raise ValueError('Duplicate release archive entry')
                seen.add(relative.as_posix())
                if relative.as_posix() != target.executable and (len(relative.parts) != 2 or relative.parts[0] != 'licenses'):
                    continue
                destination = payload.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output, length=65536)
                if relative.as_posix() == target.executable:
                    executable_found = True
        if not executable_found:
            raise ValueError('The release archive has no nesting executable')
        executable = payload / target.executable
        validate_binary(executable, target)
        if target.executable != 'clinesting.exe':
            executable.chmod(0o755)
        _check_cancel(cancelled)
        version = probe(executable)
        _check_cancel(cancelled)
        if version is None or version_key(version) != version_key(release['version']):
            raise ValueError('The executable version does not match the release')
        prepared.receipt = dict(version=release['version'], tag=release['tag'], platform=target.folder,
                                sha256=digest(executable), asset_url=asset['browser_download_url'],
                                archive_sha256=asset['digest'].split(':', 1)[1].lower())
        (payload / RECEIPT).write_text(json.dumps(prepared.receipt, indent=2) + '\n', encoding='utf-8')
        return prepared
    except Exception:
        prepared.cleanup()
        raise


def install_prepared(workbench, prepared):
    """Called under the shared Qt job lock; roll back any incomplete replacement."""
    target = prepared.target
    current = _installed_path(workbench, target)
    current_digest = digest(current) if current else None
    if current_digest != prepared.previous_digest:
        prepared.cleanup()
        raise RuntimeError('The installed engine changed during the download. Check for updates again.')
    parent = _storage(workbench)
    destination = parent / prepared.target.folder
    if not destination.resolve().is_relative_to(parent):
        prepared.cleanup()
        raise ValueError('The platform directory is outside the workbench')
    destination.mkdir(parents=True, exist_ok=True)
    payload = prepared.root / 'payload'
    backups = prepared.root / 'backups'
    changed = []
    files = sorted(path for path in payload.rglob('*') if path.is_file())
    # Commit the executable last; other files are restored if replacement fails.
    files.sort(key=lambda path: path.name == prepared.target.executable)
    try:
        for source in files:
            relative = source.relative_to(payload)
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Installation path escapes the platform directory')
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backups / relative
            existed = target.exists()
            if existed:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            os.replace(source, target)
            changed.append((target, backup if existed else None))
        if digest(destination / prepared.target.executable) != prepared.receipt['sha256']:
            raise ValueError('Installed executable failed its SHA-256 check')
    except Exception:
        for target, backup in reversed(changed):
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)
        raise
    finally:
        prepared.cleanup()
    return str(destination / prepared.target.executable)
