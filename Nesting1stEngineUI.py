"""First-use setup and explicit, cancellable engine updates on the Qt UI thread."""
import os
from html import escape
from pathlib import Path
from PySide import QtCore, QtGui
import FreeCAD as App
from Nesting1stAsync import BackgroundCall
from Nesting1stLanguages import DIRECTORY, PREFERENCES, tr, ui_call, register_window
from Nesting1stWaitDialog import NestingWaitDialog
import Nesting1stEngine as engine

_controller = None


class EngineUpdater(QtCore.QObject):
    def __init__(self, parent=None, workbench=DIRECTORY):
        super().__init__(parent)
        self.workbench = os.path.abspath(workbench)
        self.parent_window = parent
        self.dialog = None
        self.task = None
        self.done = None
        self.cancelled = False
        self.update_lock = None
        self.offer_queued = False
        self.install_requested = False
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._poll)
        if parent is not None:
            parent.destroyed.connect(self.cancel)

    @staticmethod
    def _source_link(asset_url):
        url = escape(asset_url, quote=True)
        return '<a href="' + url + '">' + url + '</a>'

    def _question(self, message, asset_url=None):
        box = QtGui.QMessageBox(self.parent_window)
        box.setWindowTitle(tr('engine.title'))
        box.setIcon(QtGui.QMessageBox.Question)
        box.setText(message)
        box.setInformativeText(self._source_link(asset_url) if asset_url else
                               '<a href="https://github.com/ingussp/CLI-nesting/releases">GitHub: ingussp/CLI-nesting</a>')
        box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        box.setStandardButtons(QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        box.setDefaultButton(QtGui.QMessageBox.No)
        self._translate_buttons(box)
        register_window(box)
        return box.exec_() == QtGui.QMessageBox.Yes

    def _info(self, message, asset_url=None):
        box = QtGui.QMessageBox(self.parent_window)
        box.setWindowTitle(tr('engine.title'))
        box.setText(message)
        if asset_url:
            box.setInformativeText(self._source_link(asset_url))
            box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        box.setStandardButtons(QtGui.QMessageBox.Ok)
        self._translate_buttons(box)
        register_window(box)
        box.exec_()

    @staticmethod
    def _translate_buttons(box):
        # QMessageBox and QDialogButtonBox use distinct enum types in Qt 6.
        for name, key in (('Yes', 'common.yes'), ('No', 'common.no'), ('Ok', 'common.ok')):
            button = box.button(getattr(QtGui.QMessageBox, name))
            if button is not None:
                ui_call(button, 'setText', tr(key))

    def _error(self, message):
        self._info(tr('engine.error') % str(message))

    def offer_first_run(self):
        if self.offer_queued or self.dialog is not None:
            return
        self.offer_queued = True
        QtCore.QTimer.singleShot(0, self._offer)

    def _offer(self):
        self.offer_queued = False
        try:
            target = engine.target_platform()
            preferences = App.ParamGet(PREFERENCES)
            key = 'EngineSetupOffered.' + target.folder
            if preferences.GetBool(key, False):
                return
            preferences.SetBool(key, True)
            if self._question(tr('engine.first_run') % target.caption, engine.download_url(target)):
                self.check_updates(install_requested=True)
        except Exception as exc:
            self._error(exc)

    def check_updates(self, install_requested=False):
        if self.dialog is not None:
            self.dialog.raise_()
            return
        try:
            target = engine.target_platform()
            lock = QtCore.QLockFile(os.path.join(self.workbench, '.ipnesting-engine-update.lock'))
            if not lock.tryLock(0):
                self._info(tr('engine.busy'))
                return
            self.update_lock = lock
            self.cancelled = False
            self.install_requested = install_requested

            def check(cancelled):
                installed = engine.installed_info(self.workbench, target)
                release = engine.latest_release(target, cancelled)
                return release, installed

            self._start(check, self._checked, tr('engine.checking'), asset_url=engine.download_url(target))
        except Exception as exc:
            self._finish()
            self._error(exc)

    def _start(self, action, done, message, discard=None, asset_url=None):
        self.done = done
        self.dialog = NestingWaitDialog(self.cancel, self.parent_window,
                                        message=message, title=tr('engine.title'))
        if asset_url:
            source = QtGui.QLabel(self._source_link(asset_url))
            source.setWordWrap(True)
            source.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            source.setOpenExternalLinks(True)
            self.dialog.layout().insertWidget(1, source)
        self.dialog.setWindowModality(QtCore.Qt.WindowModal)
        self.dialog.show()

        def begin():
            if self.cancelled:
                return
            self.task = BackgroundCall(action, discard=discard)
            self.task.start()
            self.timer.start()

        self.dialog.start_after_paint(begin)

    def _close_progress(self):
        self.timer.stop()
        self.task = None
        if self.dialog is not None:
            self.dialog.finish()
            self.dialog.deleteLater()
            self.dialog = None

    def _poll(self):
        result = self.task.poll() if self.task is not None else None
        if result is None:
            return
        value, error = result
        done = self.done
        self._close_progress()
        if self.cancelled:
            return
        if error:
            self._finish()
            self._error(error)
        else:
            try:
                done(value)
            except Exception as exc:
                self._finish()
                self._error(exc)

    def _checked(self, result):
        release, installed = result
        if not engine.needs_update(release, installed):
            self._finish()
            # Legacy/manual installs have no verified receipt: show the public
            # update endpoint rather than attributing an unrecorded release URL.
            self._info(tr('engine.current') % installed['version'],
                       installed.get('asset_url') or engine.download_url(release['target']))
            return
        asset_url = release['asset']['browser_download_url']
        if not self.install_requested and not self._question(tr('engine.download_offer') % (release['tag'], release['target'].caption), asset_url):
            self._finish()
            return
        self._start(lambda cancelled: engine.prepare_download(self.workbench, release, installed, cancelled),
                    self._downloaded, tr('engine.downloading') % release['tag'],
                    discard=lambda prepared: prepared.cleanup(), asset_url=asset_url)

    def _downloaded(self, prepared):
        job_lock = QtCore.QLockFile(os.path.join(self.workbench, '.ipnesting-job.lock'))
        try:
            if not job_lock.tryLock(0):
                self._info(tr('engine.busy'))
                return
            engine.install_prepared(self.workbench, prepared)
        finally:
            job_lock.unlock()
            prepared.cleanup()
            self._finish()
        self._info(tr('engine.installed') % prepared.receipt['version'], prepared.receipt.get('asset_url'))

    def _finish(self):
        self._close_progress()
        if self.update_lock is not None:
            self.update_lock.unlock()
            self.update_lock = None

    def cancel(self, *args):
        self.cancelled = True
        if self.task is not None:
            self.task.cancel()
        try:
            self._finish()
        except RuntimeError:
            pass  # The main window is already being destroyed.


def controller():
    global _controller
    if _controller is None:
        import FreeCADGui as Gui
        _controller = EngineUpdater(Gui.getMainWindow())
    return _controller


def offer_first_run():
    controller().offer_first_run()


def check_updates():
    controller().check_updates()
