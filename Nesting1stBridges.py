"""Manual edge-to-edge laser bridge editor for 2D and 3D nesting results."""
from PySide import QtCore, QtGui
from Nesting1stLanguages import tr, ui_call, ui_widget, register_window
from Nesting1stGrainMatch import ZoomView
from Nesting1stBridgeModel import BridgeError, load_result, create_document, from_mm, to_mm
from Nesting1stResultSVG import _colour


def text(key):
    return tr('bridge.' + key)


def painter_path(outer, holes=()):
    path = QtGui.QPainterPath()
    path.setFillRule(QtCore.Qt.OddEvenFill)
    for ring in [outer] + list(holes):
        path.moveTo(ring[0][0], -ring[0][1])
        for x, y in ring[1:]:
            path.lineTo(x, -y)
        path.closeSubpath()
    return path


def cosmetic_pen(colour, width=1.4):
    pen = QtGui.QPen(QtGui.QColor(colour))
    pen.setWidthF(width)
    pen.setCosmetic(True)
    return pen


class BridgeView(ZoomView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self._left_start = None
        self._left_last = None
        self._left_panning = False
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            position = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            self._left_start = self._left_last = position
            self._left_panning = False
            event.accept()
        elif event.button() == QtCore.Qt.RightButton:
            self.editor.clear_endpoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        position = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        if self._left_start is not None:
            if not self._left_panning and (position-self._left_start).manhattanLength() >= QtGui.QApplication.startDragDistance():
                self._left_panning = True
                self.setCursor(QtCore.Qt.ClosedHandCursor)
                self.editor.clear_candidate()
            if self._left_panning:
                delta = position-self._left_last
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            self._left_last = position
            event.accept()
            return
        if self._pan_position is None and self.editor.pending is not None:
            point = self.mapToScene(position)
            self.editor.draw_candidate([point.x(), -point.y()])
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._left_start is not None:
            was_panning = self._left_panning
            self._left_start = self._left_last = None
            self._left_panning = False
            self.setCursor(QtCore.Qt.CrossCursor)
            if not was_panning:
                position = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                point = self.mapToScene(position)
                self.editor.choose_edge([point.x(), -point.y()])
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MiddleButton:
            self.setCursor(QtCore.Qt.CrossCursor)


class BridgeDialog(QtGui.QDialog):
    def __init__(self, layout, units='mm', width_mm=1.0, parent=None):
        super().__init__(parent)
        self.layout_model = layout
        self._had_bridges = bool(layout.bridges)
        self.units = units
        self.width_mm = float(width_mm)
        self.pending = None
        self.result_document = None
        self._unit_guard = False
        self._row_guard = False
        self._marker = None
        self._candidate = None
        ui_call(self, 'setWindowTitle', text('title'))
        self.resize(1120, 800)
        self.setMinimumSize(720, 540)
        root = QtGui.QVBoxLayout(self)
        hint = ui_widget(QtGui.QLabel, text('hint'))
        hint.setWordWrap(True)
        root.addWidget(hint)
        controls = QtGui.QHBoxLayout()
        root.addLayout(controls)
        controls.addWidget(ui_widget(QtGui.QLabel, text('sheet')))
        self.sheet_combo = QtGui.QComboBox()
        for sheet in layout.sheets:
            self.sheet_combo.addItem(str(tr('sheet_d') % (sheet['index']+1)), sheet['index'])
        controls.addWidget(self.sheet_combo)
        controls.addSpacing(18)
        controls.addWidget(ui_widget(QtGui.QLabel, text('width')))
        self.width_spin = QtGui.QDoubleSpinBox()
        self.width_spin.setMinimumWidth(145)
        self.width_spin.valueChanged.connect(self.width_changed)
        controls.addWidget(self.width_spin)
        self.cancel_point = ui_widget(QtGui.QPushButton, text('cancel_point'))
        self.cancel_point.clicked.connect(self.clear_endpoint)
        controls.addWidget(self.cancel_point)
        controls.addStretch()
        self.fit_button = ui_widget(QtGui.QPushButton, text('fit'))
        self.fit_button.clicked.connect(self.fit_view)
        controls.addWidget(self.fit_button)
        self.view = BridgeView(self)
        self.view.setScene(QtGui.QGraphicsScene(self.view))
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor('#fafbfc')))
        self.view.setMinimumHeight(240)
        root.addWidget(self.view, 1)
        self.status = QtGui.QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addWidget(ui_widget(QtGui.QLabel, text('list')))
        self.table = QtGui.QTableWidget(0, 4)
        ui_call(self.table, 'setHorizontalHeaderLabels', [text('number'), text('parts'), text('width'), text('length')])
        self.table.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(190)
        self.table.setMinimumHeight(90)
        self.table.itemSelectionChanged.connect(self.highlight_selection)
        root.addWidget(self.table)
        buttons = QtGui.QHBoxLayout()
        root.addLayout(buttons)
        self.delete_button = ui_widget(QtGui.QPushButton, text('delete'))
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        self.ok_button = ui_widget(QtGui.QPushButton, tr('common.ok'))
        self.ok_button.clicked.connect(self.save_result)
        buttons.addWidget(self.ok_button)
        cancel = ui_widget(QtGui.QPushButton, tr('common.cancel'))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        shortcut = QtGui.QShortcut(QtGui.QKeySequence('Delete'), self.table)
        shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.delete_selected)
        self.sheet_combo.currentIndexChanged.connect(self.change_sheet)
        self.set_display_units(units)
        self.refresh_table()
        self.draw_scene()
        register_window(self)
        QtCore.QTimer.singleShot(0, self.fit_view)

    def current_sheet(self):
        return int(self.sheet_combo.itemData(self.sheet_combo.currentIndex()))

    def dimension(self, mm):
        return ('%.6f' % from_mm(mm, self.units)).rstrip('0').rstrip('.') + ' ' + self.units

    def set_display_units(self, units):
        self.units = 'inch' if units == 'inch' else 'mm'
        self._unit_guard = True
        try:
            self.width_spin.setDecimals(7 if self.units == 'inch' else 4)
            self.width_spin.setRange(from_mm(.001, self.units), from_mm(1000000, self.units))
            self.width_spin.setSingleStep(.01 if self.units == 'inch' else .1)
            self.width_spin.setSuffix(' ' + self.units)
            self.width_spin.setValue(from_mm(self.width_mm, self.units))
        finally:
            self._unit_guard = False
        if hasattr(self, 'table'):
            self.refresh_table()

    def width_changed(self, value):
        if not self._unit_guard:
            self.width_mm = to_mm(value, self.units)
            self.clear_candidate()

    def set_status(self, key, error=False):
        ui_call(self.status, 'setText', text(key))
        self.status.setStyleSheet('color:#a34545;' if error else '')

    def fit_view(self):
        sheet = next(s for s in self.layout_model.sheets if s['index'] == self.current_sheet())
        bounds = painter_path(sheet['outer']).boundingRect()
        padding = max(bounds.width(), bounds.height()) * .04
        bounds.adjust(-padding, -padding, padding, padding)
        canvas = QtCore.QRectF(bounds)
        travel = max(bounds.width(), bounds.height()) * 3
        canvas.adjust(-travel, -travel, travel, travel)
        self.view.setSceneRect(canvas)
        self.view.fitInView(bounds, QtCore.Qt.KeepAspectRatio)

    def change_sheet(self, _index):
        self.clear_endpoint()
        self.draw_scene()
        self.fit_view()

    def clear_candidate(self):
        if self._candidate is not None:
            self.view.scene().removeItem(self._candidate)
            self._candidate = None

    def clear_endpoint(self):
        self.pending = None
        self.clear_candidate()
        if self._marker is not None:
            self.view.scene().removeItem(self._marker)
            self._marker = None
        self.cancel_point.setEnabled(False)
        self.set_status('choose_first')

    def snap(self, point):
        tolerance = 9/max(abs(self.view.transform().m11()), 1e-9)
        return self.layout_model.nearest_edge(self.current_sheet(), point, tolerance)

    def choose_edge(self, point):
        endpoint = self.snap(point)
        if endpoint is None:
            self.set_status('edge_required', True)
            return
        if self.pending is None:
            self.pending = endpoint
            x, y = endpoint['point']
            self._marker = self.view.scene().addEllipse(-4, -4, 8, 8, cosmetic_pen('#d45524', 2),
                                                       QtGui.QBrush(QtGui.QColor('#ffb366')))
            self._marker.setFlag(QtGui.QGraphicsItem.ItemIgnoresTransformations)
            self._marker.setPos(x, -y)
            self._marker.setZValue(10)
            self.cancel_point.setEnabled(True)
            self.set_status('choose_second')
            return
        try:
            self.layout_model.add_bridge(self.pending, endpoint, self.width_mm)
        except BridgeError as exc:
            self.set_status(exc.key, True)
            return
        self.pending = None
        self.refresh_table()
        self.draw_scene()
        self.set_status('added')

    def draw_candidate(self, point):
        self.clear_candidate()
        endpoint = self.snap(point)
        if endpoint is None:
            return
        try:
            candidate = self.layout_model.make_bridge(self.pending, endpoint, self.width_mm)
        except BridgeError:
            x, y = self.pending['point']; ex, ey = endpoint['point']
            self._candidate = self.view.scene().addLine(x, -y, ex, -ey, cosmetic_pen('#c43d3d', 2))
        else:
            colour = QtGui.QColor('#ffa32c'); colour.setAlpha(100)
            self._candidate = self.view.scene().addPath(painter_path(candidate['outer']),
                                                       cosmetic_pen('#da7c15'), QtGui.QBrush(colour))
        self._candidate.setZValue(5)

    def selected_ids(self):
        return {int(self.table.item(index.row(), 0).data(QtCore.Qt.UserRole))
                for index in self.table.selectionModel().selectedRows()}

    def refresh_table(self):
        self._row_guard = True
        try:
            selected = self.selected_ids()
            self.table.setRowCount(len(self.layout_model.bridges))
            for row, bridge in enumerate(self.layout_model.bridges):
                a, b = [self.layout_model.parts[bridge[key]['part']] for key in ('first', 'second')]
                values = [str(bridge['id']), '%s → %s' % (a['label'], b['label']),
                          self.dimension(bridge['width_mm']), self.dimension(bridge['length_mm'])]
                for column, value in enumerate(values):
                    item = QtGui.QTableWidgetItem(value)
                    item.setData(QtCore.Qt.UserRole, bridge['id'])
                    self.table.setItem(row, column, item)
                if bridge['id'] in selected:
                    self.table.selectRow(row)
            self.table.resizeColumnsToContents()
            self.delete_button.setEnabled(bool(self.selected_ids()))
            self.ok_button.setEnabled(bool(self.layout_model.bridges) or self._had_bridges)
        finally:
            self._row_guard = False

    def highlight_selection(self):
        if self._row_guard:
            return
        identifiers = self.selected_ids()
        self.delete_button.setEnabled(bool(identifiers))
        if identifiers:
            bridge = next(b for b in self.layout_model.bridges if b['id'] in identifiers)
            index = self.sheet_combo.findData(bridge['sheet'])
            if index != self.sheet_combo.currentIndex():
                self.sheet_combo.setCurrentIndex(index)
        self.draw_scene()

    def draw_scene(self):
        self._marker = self._candidate = None
        scene = self.view.scene(); scene.clear()
        self.pending = None
        self.cancel_point.setEnabled(False)
        sheet = next(s for s in self.layout_model.sheets if s['index'] == self.current_sheet())
        scene.addPath(painter_path(sheet['outer'], sheet['holes']), cosmetic_pen('#8794a0'),
                      QtGui.QBrush(QtGui.QColor('#f0f3f6')))
        for part in self.layout_model.parts:
            if part['sheet'] != sheet['index']:
                continue
            colour = QtGui.QColor(_colour(part['index'])); colour.setAlpha(115)
            item = scene.addPath(painter_path(part['outer'], part['holes']), cosmetic_pen(_colour(part['index']), 1.8),
                                 QtGui.QBrush(colour))
            item.setToolTip(part['label'])
            if part['shape'] is not None:
                from Nesting1stExport import _discretize_edge_2d
                details = QtGui.QPainterPath()
                seen = set()
                for edge in part['shape'].Edges:
                    points = _discretize_edge_2d(edge, .01)
                    key = tuple(tuple(p) for p in points)
                    if len(points) < 2 or key in seen or tuple(reversed(key)) in seen:
                        continue
                    seen.add(key)
                    details.moveTo(points[0][0], -points[0][1])
                    for x, y in points[1:]:
                        details.lineTo(x, -y)
                detail_item = scene.addPath(details, cosmetic_pen('#566372', .8))
                detail_item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            label = scene.addSimpleText('%d · %s' % (part['index']+1, part['label']))
            label.setFlag(QtGui.QGraphicsItem.ItemIgnoresTransformations)
            label.setBrush(QtGui.QBrush(QtGui.QColor('#273545')))
            bounds = item.boundingRect()
            label.setPos(bounds.left(), bounds.top())
            label.setZValue(3)
        selected = self.selected_ids()
        for bridge in self.layout_model.bridges:
            if bridge['sheet'] != sheet['index']:
                continue
            colour = '#ffca44' if bridge['id'] in selected else '#f79632'
            item = scene.addPath(painter_path(bridge['outer']), cosmetic_pen('#9c4b08'), QtGui.QBrush(QtGui.QColor(colour)))
            item.setZValue(4)
            item.setToolTip(str(text('item') % bridge['id']))
        self.set_status('choose_first')

    def delete_selected(self):
        self.layout_model.remove_bridges(self.selected_ids())
        self.table.clearSelection()
        self.refresh_table()
        self.draw_scene()

    def save_result(self):
        if not self.layout_model.bridges and not self._had_bridges:
            return
        try:
            self.result_document = create_document(self.layout_model, tr)
        except BridgeError as exc:
            self.set_status(exc.key, True)
        except Exception as exc:
            QtGui.QMessageBox.critical(self, text('title'), text('failed') % str(exc))
        else:
            self.accept()


def open_editor(panel):
    try:
        layout = load_result(panel)
    except BridgeError as exc:
        QtGui.QMessageBox.information(panel.form, text('title'), text(exc.key))
        return None
    dialog = BridgeDialog(layout, getattr(panel, 'display_units', 'mm'),
                          getattr(panel, '_bridge_width_mm', 1.0), panel.form)
    panel._active_bridge_dialog = dialog
    try:
        dialog.exec_()
        if dialog.result_document is not None:
            panel._bridge_width_mm = dialog.width_mm
        return dialog.result_document
    finally:
        panel._active_bridge_dialog = None
