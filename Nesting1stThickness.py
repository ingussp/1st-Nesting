"""Compare part depths along the preview's cutting axis, in canonical mm."""
import json
import math
import FreeCAD as App
from PySide import QtCore, QtGui
from Nesting1stLanguages import tr

TOLERANCE_MM = 0.001
MISMATCH_COLOR = '#f7c9c9'
BACKGROUND_ROLE = int(QtCore.Qt.UserRole) + 830
TOOLTIP_ROLE = BACKGROUND_ROLE + 1
MARKED_ROLE = BACKGROUND_ROLE + 2
WARNING_TOOLTIP_ROLE = BACKGROUND_ROLE + 3


def same_thickness(first, second):
    return math.isclose(first, second, abs_tol=TOLERANCE_MM, rel_tol=1e-6)


def object_thicknesses(obj):
    """Use current nesting orientation; flat 2D input has no known gauge."""
    from Nesting1stExport import _get_source_type
    if obj is None or _get_source_type(obj) in ('dxf', 'svg'):
        return []
    shape = getattr(obj, 'Shape', None)
    if shape is None or shape.isNull():
        shape = getattr(getattr(obj, 'Tip', None), 'Shape', None)
    if shape is None or shape.isNull():
        return []
    # STEP compounds may contain different solid gauges or offsets in Z.
    shapes = list(shape.Solids) or [shape]
    return [d for d in (float(s.BoundBox.ZLength) for s in shapes)
            if math.isfinite(d) and d > TOLERANCE_MM]


def compare_parts(parts):
    """Each source part votes once per gauge; quantities and summary rows don't.

    Ties choose the first gauge. Fixed cluster representatives avoid accepting
    a chain of gradually different thicknesses.
    """
    clusters = []
    for name, depths in parts.items():
        for depth in depths:
            cluster = next((c for c in clusters if same_thickness(c['depth'], depth)), None)
            if cluster is None:
                cluster = {'depth': depth, 'names': set()}
                clusters.append(cluster)
            cluster['names'].add(name)
    if not clusters:
        return {'reference': None, 'mismatched': set()}
    reference = max(clusters, key=lambda c: len(c['names']))['depth']
    return {'reference': reference,
            'mismatched': {n for n, depths in parts.items()
                           if any(not same_thickness(d, reference) for d in depths)}}


class ThicknessChecker:
    """Refresh after edits; warn once per changed mismatch, or on explicit run."""
    def __init__(self, panel):
        self.panel = panel
        self.last_warning = None
        self.timer = QtCore.QTimer(panel.table)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        panel.table.model().rowsInserted.connect(self.schedule)
        panel.table.model().rowsRemoved.connect(self.schedule)

    def schedule(self, *args):
        # Let a batch import finish filling its rows before opening a popup.
        self.timer.start(0)

    def _row_names(self, row):
        item = self.panel.table.item(row, 0)
        if item is None:
            return []
        raw = item.data(QtCore.Qt.UserRole + 1)
        if raw:
            try:
                names = json.loads(raw) if isinstance(raw, str) else list(raw)
                if isinstance(names, list):
                    return list(dict.fromkeys(str(n) for n in names if n))
            except (ValueError, TypeError):
                pass
        primary = item.data(QtCore.Qt.UserRole)
        return [str(primary)] if primary else []

    def measure(self):
        doc = App.getDocument(self.panel.preview_doc_name) if self.panel.preview_doc_name in App.listDocuments() else None
        rows = {r: self._row_names(r) for r in range(max(0, self.panel.table.rowCount() - self.panel.control_rows))}
        parts, labels = {}, {}
        if doc is not None:
            for names in rows.values():
                for name in names:
                    if name not in parts:
                        obj = doc.getObject(name)
                        parts[name] = object_thicknesses(obj)
                        labels[name] = str(getattr(obj, 'Label', name))
        result = compare_parts(parts)
        result.update(rows=rows, parts=parts, labels=labels)
        return result

    def _dimension(self, value):
        return self.panel._format_dimension(value) + (' inch' if self.panel.display_units == 'inch' else ' mm')

    def _values(self, values):
        unique = []
        for value in values:
            if not any(same_thickness(value, old) for old in unique):
                unique.append(value)
        return ', '.join(self._dimension(value) for value in unique)

    def _highlight(self, result):
        table = self.panel.table
        blocked = table.blockSignals(True)
        try:
            for row, names in result['rows'].items():
                mismatch = bool(set(names) & result['mismatched'])
                depths = [d for name in names for d in result['parts'].get(name, [])]
                tooltip = str(tr('thickness.row_tooltip') % (self._values(depths), self._dimension(result['reference']))) if mismatch else ''
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is not None:
                        marked = bool(item.data(MARKED_ROLE))
                        if mismatch:
                            # Group rendering can replace red with its grey/green
                            # base colour; keep that updated style for restoration.
                            if not marked or item.background().color().name() != MISMATCH_COLOR:
                                item.setData(BACKGROUND_ROLE, item.background())
                            if not marked or item.toolTip() != item.data(WARNING_TOOLTIP_ROLE):
                                item.setData(TOOLTIP_ROLE, item.toolTip())
                            item.setData(MARKED_ROLE, True)
                            item.setData(WARNING_TOOLTIP_ROLE, tooltip)
                            item.setBackground(QtGui.QBrush(QtGui.QColor(MISMATCH_COLOR)))
                            item.setToolTip(tooltip)
                        elif marked:
                            if item.background().color().name() == MISMATCH_COLOR:
                                item.setBackground(item.data(BACKGROUND_ROLE) or QtGui.QBrush())
                            if item.toolTip() == item.data(WARNING_TOOLTIP_ROLE):
                                item.setToolTip(item.data(TOOLTIP_ROLE) or '')
                            for role in (BACKGROUND_ROLE, TOOLTIP_ROLE, MARKED_ROLE, WARNING_TOOLTIP_ROLE):
                                item.setData(role, None)
                    widget = table.cellWidget(row, col)
                    if widget is None:
                        continue
                    saved = widget.property('Nesting1stThicknessPalette')
                    if mismatch:
                        if saved is None:
                            widget.setProperty('Nesting1stThicknessPalette', widget.palette())
                            widget.setProperty('Nesting1stThicknessAutoFill', widget.autoFillBackground())
                            widget.setProperty('Nesting1stThicknessTooltip', widget.toolTip())
                            widget.setProperty('Nesting1stThicknessStyleSheet', widget.styleSheet())
                        widget.setProperty('Nesting1stThicknessMismatch', True)
                        widget.setStyleSheet((widget.property('Nesting1stThicknessStyleSheet') or '') +
                                            '\nQWidget[Nesting1stThicknessMismatch="true"] { background-color: ' + MISMATCH_COLOR + '; }')
                        palette = widget.palette()
                        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(MISMATCH_COLOR))
                        widget.setPalette(palette)
                        widget.setAutoFillBackground(True)
                        widget.setToolTip(tooltip)
                    elif saved is not None:
                        widget.setProperty('Nesting1stThicknessMismatch', None)
                        widget.setStyleSheet(widget.property('Nesting1stThicknessStyleSheet') or '')
                        widget.setPalette(saved)
                        widget.setAutoFillBackground(bool(widget.property('Nesting1stThicknessAutoFill')))
                        widget.setToolTip(widget.property('Nesting1stThicknessTooltip') or '')
                        for key in ('Palette', 'AutoFill', 'Tooltip', 'StyleSheet'):
                            widget.setProperty('Nesting1stThickness' + key, None)
        finally:
            table.blockSignals(blocked)

    def _show_warning(self, result):
        message = QtGui.QMessageBox(self.panel.form)
        message.setIcon(QtGui.QMessageBox.Warning)
        message.setWindowTitle(tr('thickness.warning_title'))
        message.setText(tr('thickness.warning') % self._dimension(result['reference']))
        message.setDetailedText('\n'.join(result['labels'][n] + ': ' + self._values(result['parts'][n])
                                        for n in result['parts'] if n in result['mismatched']))
        message.setStandardButtons(QtGui.QMessageBox.Ok)
        if hasattr(message, 'exec'):
            message.exec()
        else:
            message.exec_()

    def refresh(self, warn=True, force=False):
        self.timer.stop()
        result = self.measure()
        self._highlight(result)
        if not result['mismatched']:
            self.last_warning = None
            return result
        signature = (round(result['reference'], 6), tuple((n, tuple(round(d, 6) for d in result['parts'][n]))
                     for n in result['parts'] if n in result['mismatched']))
        if warn and (force or signature != self.last_warning):
            self.last_warning = signature  # Before the modal loop dispatches edits.
            self._show_warning(result)
        return result
