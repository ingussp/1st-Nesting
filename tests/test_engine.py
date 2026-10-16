"""Release selection, bounded downloads, cancellation and transactional install."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Nesting1stEngine as E


def binary(target):
    if target.folder.startswith('windows'):
        value = bytearray(128)
        value[:2] = b'MZ'
        struct.pack_into('<I', value, 60, 64)
        value[64:68] = b'PE\0\0'
        struct.pack_into('<H', value, 68, 0x8664)
    elif target.folder.startswith('linux'):
        value = bytearray(64)
        value[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', value, 18, 183 if target.machine == 'arm64' else 62)
    else:
        value = bytearray(128)
        value[:8] = struct.pack('>II', 0xcafebabe, 2)
        struct.pack_into('>IIIII', value, 8, 0x01000007, 0, 64, 32, 0)
        struct.pack_into('>IIIII', value, 28, 0x0100000c, 0, 96, 32, 0)
    return bytes(value)


def archive(target, additional=None, executable=None):
    stream = io.BytesIO()
    prefix = 'clinesting-' + target.folder
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, data in [(prefix + '/' + target.executable, binary(target) if executable is None else executable),
                           (prefix + '/licenses/Clipper2.txt', b'licence')]:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        if additional:
            tar.addfile(additional, io.BytesIO(b'x' * additional.size) if additional.isfile() else None)
    return stream.getvalue()


class Response(io.BytesIO):
    pass


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = E.target_platform('Windows', 'AMD64')
        self.previous = self.root / 'clinesting' / self.target.folder / self.target.executable
        self.previous.parent.mkdir(parents=True)
        self.previous.write_bytes(b'old executable')
        self.installed = dict(version=None, digest=E.digest(self.previous), executable=str(self.previous))
        self.content = archive(self.target)
        self.data = dict(tag_name='v1.0', draft=False, prerelease=False, assets=[dict(
            name=self.target.asset, size=len(self.content), digest='sha256:' + hashlib.sha256(self.content).hexdigest(),
            browser_download_url='https://github.com/ingussp/CLI-nesting/releases/download/v1.0/' + self.target.asset)])
        self.release = E.latest_release(self.target, opener=lambda _: Response(json.dumps(self.data).encode()))

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, content=None, release=None, cancelled=None, probe=lambda _: '1'):
        return E.prepare_download(self.root, release or self.release, self.installed, cancelled,
                                  opener=lambda _: Response(self.content if content is None else content), probe=probe)

    def assert_untouched(self):
        self.assertEqual(self.previous.read_bytes(), b'old executable')
        self.assertFalse(list((self.root / 'clinesting').glob('.engine-download-*')))

    def test_platform_mapping_and_unsupported_architectures(self):
        for system, machine, folder in [('Windows', 'AMD64', 'windows-x86_64'), ('Windows', 'x64', 'windows-x86_64'),
                ('Linux', 'x86_64', 'linux-x86_64'), ('Linux', 'aarch64', 'linux-aarch64'),
                ('Darwin', 'arm64', 'macos-universal2'), ('Darwin', 'x86_64', 'macos-universal2')]:
            with self.subTest(system=system, machine=machine):
                self.assertEqual(E.target_platform(system, machine).folder, folder)
        for system, machine in [('Windows', 'arm64'), ('Linux', 'i386'), ('Darwin', 'ppc'), ('Other', 'x64')]:
            with self.assertRaises(ValueError):
                E.target_platform(system, machine)

    def test_version_comparison_never_downgrades(self):
        for installed, available, expected in [('1', '1.0', False), ('1.2', '1.10', True),
                                               ('2', '1.9', False), (None, '1', True)]:
            self.assertEqual(E.needs_update(dict(version=available), dict(version=installed)), expected)
        for invalid in ('main', 'v1.0-beta', '1.x', '../1', ''):
            with self.assertRaises(ValueError): E.version_key(invalid)

    def test_download_urls_for_every_supported_release_asset(self):
        for system,machine in [('Windows','AMD64'),('Linux','x86_64'),('Linux','aarch64'),('Darwin','arm64')]:
            target=E.target_platform(system,machine)
            self.assertEqual(E.download_url(target), 'https://github.com/ingussp/CLI-nesting/releases/latest/download/'+target.asset)
            self.assertEqual(E.download_url(target,'v1.02'), 'https://github.com/ingussp/CLI-nesting/releases/download/v1.02/'+target.asset)

    def test_receipt_source_requires_matching_executable_and_release(self):
        prepared=self.prepare()
        E.install_prepared(self.root,prepared)
        url=self.release['asset']['browser_download_url']
        info=E.installed_info(self.root,self.target,probe=lambda _: '1.0')
        self.assertEqual(info['asset_url'],url)
        receipt_path=self.previous.parent/E.RECEIPT
        receipt=json.loads(receipt_path.read_text())
        receipt['asset_url']='https://untrusted.invalid/engine.exe'
        receipt_path.write_text(json.dumps(receipt))
        self.assertNotIn('asset_url',E.installed_info(self.root,self.target,probe=lambda _: '1.0'))
        receipt['asset_url']=url
        receipt_path.write_text(json.dumps(receipt))
        self.previous.write_bytes(b'a manually replaced executable')
        self.assertNotIn('asset_url',E.installed_info(self.root,self.target,probe=lambda _: '1.02'))
        prepared.cleanup()

    def test_invalid_release_metadata_and_missing_asset(self):
        for change in (dict(draft=True), dict(prerelease=True), dict(assets=[]), dict(tag_name='main')):
            data = dict(self.data, **change)
            with self.assertRaises(ValueError):
                E.latest_release(self.target, opener=lambda _: Response(json.dumps(data).encode()))
        for key, value in [('digest', None), ('size', E.MAX_ARCHIVE + 1), ('size', True),
                           ('browser_download_url', 'https://example.com/engine')]:
            data = copy.deepcopy(self.data)
            data['assets'][0][key] = value
            with self.assertRaises(ValueError):
                E.latest_release(self.target, opener=lambda _: Response(json.dumps(data).encode()))

    def test_cancel_before_network_and_during_download(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(E.Cancelled):
            E.latest_release(self.target, cancelled, opener=lambda _: self.fail('Network started'))
        with self.assertRaises(E.Cancelled): self.prepare(cancelled=cancelled)
        self.assert_untouched()
        cancelled.clear()
        class CancelResponse(Response):
            def read(self, count=-1):
                value = super().read(count)
                cancelled.set()
                return value
        with self.assertRaises(E.Cancelled):
            E.prepare_download(self.root, self.release, self.installed, cancelled,
                               opener=lambda _: CancelResponse(self.content), probe=lambda _: self.fail('Cancelled before validation'))
        self.assert_untouched()

    def test_size_and_digest_mismatch_preserve_old_engine(self):
        for content in (self.content[:-1], self.content + b'extra', b'x' * len(self.content)):
            with self.assertRaises(ValueError): self.prepare(content=content)
            self.assert_untouched()

    def test_archive_traversal_links_and_duplicate_binary_are_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE),
                           ('clinesting-windows-x86_64/../../escape', tarfile.REGTYPE),
                           ('clinesting-windows-x86_64/link', tarfile.SYMTYPE),
                           ('clinesting-windows-x86_64/clinesting.exe', tarfile.REGTYPE),
                           ('clinesting-windows-x86_64/C:\\escape', tarfile.REGTYPE)]:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = 1 if kind == tarfile.REGTYPE else 0
            member.linkname = '/outside'
            content = archive(self.target, additional=member)
            release = copy.deepcopy(self.release)
            release['asset'].update(size=len(content), digest='sha256:' + hashlib.sha256(content).hexdigest())
            with self.assertRaises(ValueError): self.prepare(content=content, release=release)
            self.assert_untouched()

    def test_wrong_executable_architecture_and_version_are_rejected(self):
        content = archive(self.target, executable=b'not an executable')
        release = copy.deepcopy(self.release)
        release['asset'].update(size=len(content), digest='sha256:' + hashlib.sha256(content).hexdigest())
        with self.assertRaises(ValueError): self.prepare(content=content, release=release)
        for version in ('2', None):
            with self.assertRaises(ValueError): self.prepare(probe=lambda _: version)
        self.assert_untouched()

    def test_install_records_receipt_and_preserves_other_files(self):
        extra = self.previous.parent / 'custom.txt'
        extra.write_text('keep')
        prepared = self.prepare()
        self.assertEqual(self.previous.read_bytes(), b'old executable')
        E.install_prepared(self.root, prepared)
        self.assertEqual(self.previous.read_bytes(), binary(self.target))
        self.assertEqual(extra.read_text(), 'keep')
        receipt = json.loads((self.previous.parent / E.RECEIPT).read_text())
        self.assertEqual(receipt['tag'], 'v1.0')
        self.assertEqual(receipt['sha256'], E.digest(self.previous))
        info = E.installed_info(self.root, self.target, probe=lambda _: self.fail('Receipt should avoid process launch'))
        self.assertEqual(info['version'], '1.0')
        self.assertFalse(E.needs_update(self.release, info))
        self.assertFalse(prepared.root.exists())

    def test_changed_engine_during_download_is_not_overwritten(self):
        prepared = self.prepare()
        self.previous.write_bytes(b'newer manual engine')
        with self.assertRaises(RuntimeError): E.install_prepared(self.root, prepared)
        self.assertEqual(self.previous.read_bytes(), b'newer manual engine')
        self.assertFalse(prepared.root.exists())

    def test_failed_replacement_rolls_back_receipt_and_licences(self):
        receipt = self.previous.parent / E.RECEIPT
        receipt.write_text('old receipt')
        prepared = self.prepare()
        replace = E.os.replace
        def fail_binary(source, destination):
            if Path(source).name == self.target.executable and Path(source).parent.name == 'payload':
                raise PermissionError('Executable is in use')
            return replace(source, destination)
        with patch.object(E.os, 'replace', side_effect=fail_binary):
            with self.assertRaises(PermissionError): E.install_prepared(self.root, prepared)
        self.assertEqual(receipt.read_text(), 'old receipt')
        self.assertFalse((self.previous.parent / 'licenses/Clipper2.txt').exists())
        self.assert_untouched()

    def test_binary_formats_for_supported_platforms(self):
        for target in [E.target_platform('Linux', 'x86_64'), E.target_platform('Linux', 'aarch64'),
                       E.target_platform('Darwin', 'arm64')]:
            path = self.root / target.folder
            path.write_bytes(binary(target))
            E.validate_binary(path, target)
        path.write_bytes(binary(E.target_platform('Linux', 'x86_64')))
        with self.assertRaises(ValueError): E.validate_binary(path, E.target_platform('Linux', 'arm64'))

    def test_linux_without_execute_permission_can_be_repaired(self):
        target = E.target_platform('Linux', 'aarch64')
        path = self.root / 'clinesting' / target.folder / target.executable
        path.parent.mkdir(parents=True)
        path.write_bytes(binary(target))
        with patch.object(E.os, 'access', return_value=False):
            info = E.installed_info(self.root, target, probe=lambda _: self.fail('Not executable'))
        self.assertIsNone(info['version'])
        self.assertEqual(info['digest'], E.digest(path))

    def test_macos_arm_fallback_is_found_for_version_checks(self):
        target = E.target_platform('Darwin', 'arm64')
        path = self.root / 'clinesting/macos-arm64/clinesting'
        path.parent.mkdir(parents=True)
        path.write_bytes(binary(target))
        path.chmod(0o755)
        info = E.installed_info(self.root, target, probe=lambda _: '1')
        self.assertEqual(Path(info['executable']), path)
        self.assertFalse(E.needs_update(self.release, info))


if __name__ == '__main__':
    unittest.main()
