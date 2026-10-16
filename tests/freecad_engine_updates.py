"""Real Qt engine setup/update lifecycle with isolated preferences and network fakes."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch
import FreeCAD as App
from PySide import QtCore, QtGui

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import Nesting1stEngineUI as UI
import Nesting1stEngine as E
import Nesting1stLanguages as L

APPLICATION = QtGui.QApplication.instance() or QtGui.QApplication([])


class Preferences:
    def __init__(self): self.values = {}
    def GetBool(self, key, default=False): return self.values.get(key, default)
    def SetBool(self, key, value): self.values[key] = value


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.parent = QtGui.QWidget()
        self.parent.show()
        self.updater = UI.EngineUpdater(self.parent, self.root)
        self.info = []
        self.info_sources = []
        self.prompts = []
        self.prompt_sources = []
        self.updater._info = lambda message, asset_url=None: (self.info.append(message), self.info_sources.append(asset_url))
        self.updater._question = lambda message, asset_url=None: (self.prompts.append(str(message)), self.prompt_sources.append(asset_url), False)[-1]
        self.language = patch.object(L, 'current_language', return_value='en')
        self.language_mock = self.language.start()
        self.target = E.target_platform('Windows', 'AMD64')
        self.release = dict(tag='v1.0', version='1.0', target=self.target,
                            asset=dict(browser_download_url=E.download_url(self.target, 'v1.0')))

    def tearDown(self):
        self.updater.cancel()
        self.parent.close()
        self.parent.deleteLater()
        APPLICATION.processEvents()
        self.language.stop()
        self.temp.cleanup()

    def wait(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            APPLICATION.processEvents()
            time.sleep(.01)
        self.assertTrue(condition())

    def test_first_use_offer_once_without_network_when_declined(self):
        preferences = Preferences()
        with patch.object(UI.App, 'ParamGet', return_value=preferences), \
             patch.object(UI.engine, 'latest_release', side_effect=AssertionError('No network before consent')):
            self.updater.offer_first_run()
            self.updater.offer_first_run()
            self.wait(lambda: len(self.prompts) == 1)
            self.updater.offer_first_run()
            APPLICATION.processEvents()
            self.assertEqual(len(self.prompts), 1)
            self.assertTrue(preferences.values['EngineSetupOffered.windows-x86_64'])
            self.assertEqual(self.prompt_sources, [E.download_url(self.target)])

    def test_real_confirmation_uses_translated_buttons_source_and_rtl_layout(self):
        self.language_mock.return_value = 'ar'
        observed = []
        def close_question():
            box = APPLICATION.activeModalWidget()
            if isinstance(box, QtGui.QMessageBox):
                observed.append((box.informativeText(), box.defaultButton().text(), box.layoutDirection()))
                box.button(QtGui.QMessageBox.No).click()
        QtCore.QTimer.singleShot(30, close_question)
        answer = UI.EngineUpdater._question(self.updater, L.tr('engine.first_run') % 'Windows x64', E.download_url(self.target))
        self.assertFalse(answer)
        self.assertEqual(len(observed), 1)
        self.assertIn(E.download_url(self.target), observed[0][0])
        self.assertEqual(observed[0][1], str(L.tr('common.no')))
        self.assertEqual(observed[0][2], QtCore.Qt.RightToLeft)

    def test_first_use_acceptance_needs_only_one_confirmation(self):
        preferences = Preferences()
        self.updater._question = lambda message, asset_url=None: self.prompts.append(str(message)) or True
        with patch.object(UI.App, 'ParamGet', return_value=preferences), \
             patch.object(self.updater, 'check_updates') as check:
            self.updater.offer_first_run()
            self.wait(lambda: check.called)
            check.assert_called_once_with(install_requested=True)
            self.assertEqual(len(self.prompts), 1)

    def test_latest_installed_version_requires_no_download(self):
        with patch.object(E, 'installed_info', return_value=dict(version='1.0', digest='hash', executable='engine')), \
             patch.object(E, 'latest_release', return_value=self.release), \
             patch.object(E, 'prepare_download', side_effect=AssertionError('Already current')):
            self.updater.check_updates()
            self.wait(lambda: bool(self.info))
            self.assertIn('up to date', str(self.info[0]))
            self.assertEqual(self.info_sources[0], E.download_url(self.target))
            self.assertFalse(self.prompts)
            self.assertIsNone(self.updater.update_lock)

    def test_first_use_download_install_and_followup_check(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_engine import archive, Response
        content = archive(self.target)
        release = dict(self.release, asset=dict(name=self.target.asset, size=len(content),
            digest='sha256:' + hashlib.sha256(content).hexdigest(),
            browser_download_url='https://github.com/ingussp/CLI-nesting/releases/download/v1.0/' + self.target.asset))
        preferences = Preferences()
        self.updater._question = lambda message, asset_url=None: self.prompts.append(str(message)) or True
        prepare = E.prepare_download
        def download(workbench, selected, installed, cancelled):
            return prepare(workbench, selected, installed, cancelled,
                           opener=lambda _: Response(content), probe=lambda _: '1')
        with patch.object(UI.App, 'ParamGet', return_value=preferences), \
             patch.object(E, 'latest_release', return_value=release), \
             patch.object(E, 'prepare_download', side_effect=download):
            self.updater.offer_first_run()
            self.wait(lambda: bool(self.info))
            self.assertIn('installed', str(self.info[0]))
            self.assertEqual(self.info_sources[0], release['asset']['browser_download_url'])
            self.assertEqual(len(self.prompts), 1)
            receipt = self.root / 'clinesting/windows-x86_64/installation.json'
            self.assertEqual(json.loads(receipt.read_text())['tag'], 'v1.0')
            self.assertIsNone(self.updater.update_lock)
            self.updater.check_updates()
            self.wait(lambda: len(self.info) == 2)
            self.assertIn('up to date', str(self.info[1]))
            self.assertEqual(self.info_sources[1], release['asset']['browser_download_url'])
            self.assertEqual(len(self.prompts), 1)

    def test_another_update_for_same_workbench_is_blocked(self):
        lock = QtCore.QLockFile(str(self.root / '.ipnesting-engine-update.lock'))
        self.assertTrue(lock.tryLock(0))
        try:
            with patch.object(E, 'latest_release', side_effect=AssertionError('Another updater owns the lock')):
                self.updater.check_updates()
            self.assertIn('running', str(self.info[0]))
            self.assertIsNone(self.updater.task)
            self.assertTrue(lock.isLocked())
        finally:
            lock.unlock()

    def test_failed_check_preserves_existing_engine_and_releases_lock(self):
        with patch.object(E, 'installed_info', return_value=dict(version=None, digest='hash', executable='engine')), \
             patch.object(E, 'latest_release', side_effect=OSError('Offline')):
            self.updater.check_updates()
            self.wait(lambda: bool(self.info))
            self.assertIn('Offline', str(self.info[0]))
            self.assertIsNone(self.updater.update_lock)
            self.assertIsNone(self.updater.dialog)

    def test_background_check_remains_responsive_and_can_be_cancelled(self):
        entered, release = threading.Event(), threading.Event()
        heartbeats = []
        timer = QtCore.QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: heartbeats.append(True))
        timer.start()
        def slow_check(target, cancelled):
            entered.set()
            release.wait(3)
            return self.release
        try:
            with patch.object(E, 'installed_info', return_value=dict(version=None, digest=None, executable=None)), \
                 patch.object(E, 'latest_release', side_effect=slow_check), \
                 patch.object(E, 'prepare_download', side_effect=AssertionError('Cancelled')):
                self.updater.check_updates()
                self.wait(entered.is_set)
                self.wait(lambda: len(heartbeats) >= 4)
                self.updater.cancel()
                release.set()
                self.assertIsNone(self.updater.dialog)
                self.assertIsNone(self.updater.update_lock)
                self.assertFalse(self.info)
                self.assertFalse(self.prompts)
        finally:
            release.set()
            timer.stop()

    def test_install_is_blocked_by_a_running_job(self):
        class Prepared:
            receipt = dict(version='1.0')
            cleaned = False
            def cleanup(self): self.cleaned = True
        prepared = Prepared()
        lock = QtCore.QLockFile(str(self.root / '.ipnesting-job.lock'))
        self.assertTrue(lock.tryLock(0))
        try:
            with patch.object(E, 'install_prepared', side_effect=AssertionError('Must not replace a running engine')):
                self.updater._downloaded(prepared)
            self.assertTrue(prepared.cleaned)
            self.assertTrue(lock.isLocked())
            self.assertIn('running', str(self.info[0]))
        finally:
            lock.unlock()

    def test_cancelled_download_discards_staged_files_without_installing(self):
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        class Prepared:
            def cleanup(self): cleaned.set()
        def download(cancelled):
            entered.set()
            release.wait(3)
            return Prepared()
        try:
            self.updater._start(download, lambda _: self.fail('Cancelled download was installed'),
                                L.tr('engine.downloading') % 'v1.0', discard=lambda prepared: prepared.cleanup())
            self.wait(entered.is_set)
            self.updater.cancel()
            release.set()
            self.wait(cleaned.is_set)
        finally:
            release.set()

    def test_settings_button_is_translated_and_triggers_explicit_check(self):
        import FreeCADGui
        with patch.object(FreeCADGui, 'getMainWindow', return_value=self.parent, create=True), \
             patch.object(UI, 'check_updates') as check:
            L.show_settings()
            self.assertEqual(L._menu._engine_update_button.text(), 'Check for updates')
            for code, _ in L.LANGUAGES:
                self.language_mock.return_value = code
                L._refresh_widget(L._menu._engine_update_button)
                self.assertEqual(L._menu._engine_update_button.text(), str(L.tr('engine.check_updates')))
            L._menu._engine_update_button.click()
            check.assert_called_once()
            self.assertFalse(L._menu.isVisible())
            L._menu.close()
            L._menu.deleteLater()
            L._menu = None

    def test_update_offer_shows_exact_asset_and_decline_does_not_download(self):
        with patch.object(E, 'installed_info', return_value=dict(version='0.9', digest='hash', executable='engine')), \
             patch.object(E, 'latest_release', return_value=self.release), \
             patch.object(E, 'prepare_download', side_effect=AssertionError('Declined')):
            self.updater.check_updates()
            self.wait(lambda: bool(self.prompts))
            self.assertEqual(self.prompt_sources, [E.download_url(self.target, 'v1.0')])
            self.assertIsNone(self.updater.update_lock)

    def test_download_progress_contains_complete_copyable_asset_url(self):
        url=E.download_url(self.target, 'v1.0')
        self.updater._start(lambda cancelled: None, lambda result: None,
                            L.tr('engine.downloading') % 'v1.0', asset_url=url)
        labels=self.updater.dialog.findChildren(QtGui.QLabel)
        sources=[label for label in labels if url in label.text()]
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0].textInteractionFlags() & QtCore.Qt.TextSelectableByMouse)
        self.assertTrue(sources[0].openExternalLinks())

    def test_actual_success_dialog_displays_receipt_source(self):
        url=E.download_url(self.target, 'v1.0')
        observed=[]
        def close_info():
            box=APPLICATION.activeModalWidget()
            if isinstance(box, QtGui.QMessageBox):
                observed.append(box.informativeText())
                box.button(QtGui.QMessageBox.Ok).click()
        QtCore.QTimer.singleShot(30, close_info)
        UI.EngineUpdater._info(self.updater, L.tr('engine.installed') % '1.0', url)
        self.assertEqual(len(observed), 1)
        self.assertIn(url, observed[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
