"""A column-aligned master row for editing all active parts together."""
from PySide import QtCore, QtGui
from Nesting1stLanguages import tr, ui_widget


class BulkPartEditor:
    def __init__(self, panel):
        self.panel = panel
        self.busy = False
        # Model signals still fire when table signals are blocked during imports.
        panel.table.model().rowsInserted.connect(self.update_visibility)
        panel.table.model().rowsRemoved.connect(self.update_visibility)

    @property
    def separator_row(self):
        return self.panel.table.rowCount() - self.panel.control_rows

    @property
    def row(self):
        return self.separator_row + 1

    def update_visibility(self, *args):
        visible = self.separator_row >= 2
        self.panel.table.setRowHidden(self.separator_row, not visible)
        self.panel.table.setRowHidden(self.row, not visible)

    def build_row(self):
        table = self.panel.table
        blocked = table.blockSignals(True)
        try:
            separator = QtGui.QTableWidgetItem('')
            separator.setFlags(QtCore.Qt.NoItemFlags)
            separator.setBackground(QtGui.QBrush(QtGui.QColor('#eeeeee')))
            table.setItem(self.separator_row, 0, separator)
            table.setSpan(self.separator_row, 0, 1, table.columnCount())
            table.setVerticalHeaderItem(self.separator_row, QtGui.QTableWidgetItem(''))
            label = ui_widget(QtGui.QTableWidgetItem, tr('select_all'))
            label.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            label.setBackground(QtGui.QBrush(QtGui.QColor('#e8edf5')))
            table.setItem(self.row, 0, label)
            for column in (1, 2):
                item = QtGui.QTableWidgetItem('')
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setBackground(QtGui.QBrush(QtGui.QColor('#e8edf5')))
                table.setItem(self.row, column, item)
            for column in (3, 4, 5):
                widget = QtGui.QWidget()
                layout = QtGui.QHBoxLayout(widget)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addStretch()
                checkbox = QtGui.QCheckBox()
                layout.addWidget(checkbox)
                checkbox.stateChanged.connect(lambda state, c=column: self.apply_checkbox(c))
                if column == 4:
                    combo = QtGui.QComboBox()
                    combo.addItems(['X', 'Y'])
                    combo.setFixedWidth(70)
                    layout.addWidget(combo)
                    combo.currentIndexChanged.connect(lambda index: self.apply_axis())
                layout.addStretch()
                table.setCellWidget(self.row, column, widget)
            table.setVerticalHeaderItem(self.row, QtGui.QTableWidgetItem(''))
            self.update_visibility()
        finally:
            table.blockSignals(blocked)

    def _targets(self):
        table = self.panel.table
        return [table.item(row, 0).data(QtCore.Qt.UserRole) for row in range(self.separator_row)
                if table.item(row, 0) is not None and table.item(row, 0).flags() & QtCore.Qt.ItemIsEnabled]

    def _find_row(self, name):
        for row in range(self.separator_row):
            item = self.panel.table.item(row, 0)
            if item is not None and item.flags() & QtCore.Qt.ItemIsEnabled and item.data(QtCore.Qt.UserRole) == name:
                return row
        return None

    def _apply(self, callback, layout=False):
        if self.busy:
            return
        table = self.panel.table
        self.busy = True
        previous_bulk = getattr(self.panel, '_bulk_edit_active', False)
        self.panel._bulk_edit_active = True
        blocked = table.blockSignals(True)
        updates = table.updatesEnabled()
        table.setUpdatesEnabled(False)
        try:
            for name in self._targets():
                row = self._find_row(name)
                if row is not None:
                    callback(row)
        finally:
            table.blockSignals(blocked)
            table.setUpdatesEnabled(updates)
            self.panel._bulk_edit_active = previous_bulk
            self.busy = False
        if layout and not previous_bulk:
            self.panel.update_grain_layout_and_perimeters(preserve_standard_layout=True)
            self.panel._fit_all_views()
        self.panel._update_apply_blink_state()

    def handle_item_changed(self, item):
        if item.row() != self.row:
            return False
        if self.busy or item.column() not in (1, 2):
            return True
        value = item.text().strip()
        if not value:
            return True
        column = item.column()
        if column == 1:
            try:
                value = str(max(0, min(5000, int(value))))
            except ValueError:
                blocked = self.panel.table.blockSignals(True)
                item.setText('')
                self.panel.table.blockSignals(blocked)
                return True
        else:
            value = self.panel._clamp_rotation_degrees_text(value)
        blocked = self.panel.table.blockSignals(True)
        item.setText(value)
        self.panel.table.blockSignals(blocked)
        def set_value(row):
            target = self.panel.table.item(row, column)
            if target is None:
                return
            rotation = value
            grain_widget = self.panel.table.cellWidget(row, 4)
            if column == 2 and grain_widget and grain_widget.findChild(QtGui.QCheckBox).isChecked():
                rotation = '[0, 180]'
            target.setText(rotation if column == 2 else value)
            self.panel.on_item_changed(target)
        self._apply(set_value)
        return True

    def apply_checkbox(self, column):
        master = self.panel.table.cellWidget(self.row, column)
        checked = master.findChild(QtGui.QCheckBox).isChecked()
        axis = master.findChild(QtGui.QComboBox) if column == 4 else None
        def change(row):
            widget = self.panel.table.cellWidget(row, column)
            if not widget:
                return
            if axis is not None:
                widget.findChild(QtGui.QComboBox).setCurrentIndex(axis.currentIndex())
            checkbox = widget.findChild(QtGui.QCheckBox)
            if checkbox is not None and checkbox.isEnabled():
                checkbox.setChecked(checked)
        self._apply(change, layout=column == 4)

    def apply_axis(self):
        master = self.panel.table.cellWidget(self.row, 4).findChild(QtGui.QComboBox)
        def change(row):
            widget = self.panel.table.cellWidget(row, 4)
            combo = widget.findChild(QtGui.QComboBox) if widget else None
            if combo is not None:
                combo.setCurrentIndex(master.currentIndex())
        self._apply(change, layout=True)
