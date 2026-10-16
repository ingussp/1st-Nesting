"""Real Qt master-row edits with native FreeCAD parts and matched groups."""
import json
import unittest
from unittest.mock import patch
from freecad_bridges import App, Part, QtGui, QtCore, APPLICATION, rectangle
from Nesting1stGui import NestingTaskPanel


class Preferences:
    def GetString(self, key, default=''): return default
    def GetBool(self, key, default=False): return default
    def GetInt(self, key, default=0): return default
    def GetUnsigned(self, key, default=0): return default
    def GetFloat(self, key, default=0): return default
    def __getattr__(self, name):
        if name.startswith(('Set', 'Rem')): return lambda *args: None
        raise AttributeError(name)


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Nesting_Preview')
        with patch.object(App, 'ParamGet', return_value=Preferences()):
            self.panel = NestingTaskPanel()
        self.panel._fit_all_views = lambda: None
        for index in range(3):
            obj = self.doc.addObject('Part::Feature', 'Panel%d' % index)
            obj.Shape = Part.makeBox(20 + index, 30, 6)
            obj.Placement.Base = App.Vector(index * 40, 0, 0)
            self.assertTrue(self.panel._add_preview_object_to_table(self.doc, obj.Name))
        self.doc.recompute()

    def tearDown(self):
        self.panel._nesting_manager.shutdown()
        try: self.panel._selection_observer._unregister()
        except AttributeError: pass
        self.panel.form.close()
        for name in list(App.listDocuments()): App.closeDocument(name)

    def checkbox(self, row, column):
        return self.panel.table.cellWidget(row, column).findChild(QtGui.QCheckBox)

    def test_master_is_between_parts_and_buttons_and_not_exported_as_part(self):
        row = self.panel._bulk_editor.row
        self.assertEqual(row, 4)
        self.assertEqual(self.panel.table.item(row, 0).text(), 'Select all')
        self.assertEqual(self.panel.control_rows, 6)
        separator = row - 1
        self.assertEqual(self.panel.table.columnSpan(separator, 0), 6)
        self.assertEqual(self.panel.table.item(separator, 0).text(), '')
        self.assertEqual(self.panel.table.item(separator, 0).background().color().name(), '#eeeeee')
        self.assertEqual(self.panel.table.item(separator, 0).flags(), QtCore.Qt.NoItemFlags)
        self.assertEqual(self.panel.table.columnSpan(row, 0), 1)
        self.assertEqual(self.panel.table.columnSpan(row + 1, 0), 6)
        self.assertIsNone(self.panel.table.item(row, 0).data(QtCore.Qt.UserRole))

    def test_qty_and_rotation_normalization_applies_to_all_parts(self):
        row = self.panel._bulk_editor.row
        self.panel.table.item(row, 1).setText('100')
        self.assertEqual([self.panel.table.item(i, 1).text() for i in range(3)], ['100'] * 3)
        self.panel.table.item(row, 2).setText('360')
        self.assertEqual([self.panel.table.item(i, 2).text() for i in range(3)], ['360'] * 3)
        self.panel.table.item(row, 2).setText('[0, 180]')
        self.assertEqual([self.panel.table.item(i, 2).text() for i in range(3)], ['[0, 180]'] * 3)
        self.panel.table.item(row, 1).setText('oops')
        self.assertEqual(self.panel._bulk_editor.row, 4)
        self.assertEqual([self.panel.table.item(i, 1).text() for i in range(3)], ['100'] * 3)

    def test_selection_and_custom_angle_columns_apply_to_all_parts(self):
        row = self.panel._bulk_editor.row
        for column in (3, 5):
            self.checkbox(row, column).setChecked(True)
            self.assertTrue(all(self.checkbox(i, column).isChecked() for i in range(3)))
            self.checkbox(row, column).setChecked(False)
            self.assertFalse(any(self.checkbox(i, column).isChecked() for i in range(3)))

    def test_grain_direction_uses_existing_callbacks_and_one_final_layout(self):
        row = self.panel._bulk_editor.row
        axis = self.panel.table.cellWidget(row, 4).findChild(QtGui.QComboBox)
        axis.setCurrentIndex(1)
        with patch.object(self.panel, 'update_grain_layout_and_perimeters', wraps=self.panel.update_grain_layout_and_perimeters) as update:
            self.checkbox(row, 4).setChecked(True)
            update.assert_called_once()
        self.assertTrue(all(self.checkbox(i, 4).isChecked() for i in range(3)))
        self.assertEqual([self.panel.table.item(i, 2).text() for i in range(3)], ['[0, 180]'] * 3)
        self.panel.table.item(row, 2).setText('360')
        self.assertEqual([self.panel.table.item(i, 2).text() for i in range(3)], ['[0, 180]'] * 3)
        self.checkbox(row, 4).setChecked(False)
        self.assertFalse(any(self.checkbox(i, 4).isChecked() for i in range(3)))
        self.assertFalse(self.panel._bulk_edit_active)

    def test_matched_group_and_disabled_members_stay_synchronized(self):
        from Nesting1stGrainMatch import _fill_group_row, write_groups, read_groups, MEMBER_ROW_KIND, ROW_KIND_ROLE
        names = ['Panel0', 'Panel1']
        definition = dict(names=names, rotations='[0]', grain=None, poses={})
        write_groups(self.doc, [definition])
        for row in (0, 1):
            item = self.panel.table.item(row, 0)
            item.setFlags(QtCore.Qt.NoItemFlags)
            item.setData(ROW_KIND_ROLE, MEMBER_ROW_KIND)
        row = self.panel._bulk_editor.separator_row
        self.panel.table.insertRow(row)
        _fill_group_row(self.panel, row, names, 1, names, definition)
        master = self.panel._bulk_editor.row
        self.panel.table.item(master, 1).setText('100')
        self.assertEqual([self.panel.table.item(i, 1).text() for i in range(master - 1)], ['100'] * 4)
        self.panel.table.item(master, 2).setText('360')
        self.assertEqual(read_groups(self.doc)[0]['rotations'], '360')
        self.assertEqual(self.panel.table.item(row, 2).text(), '360')

    def test_qty_zero_uses_existing_deletion_without_touching_control_rows(self):
        self.panel.table.item(self.panel._bulk_editor.row, 1).setText('0')
        self.assertEqual(self.panel.table.rowCount(), 6)
        self.assertEqual(self.panel.table.item(1, 0).text(), 'Select all')
        self.assertTrue(self.panel.table.isRowHidden(0))
        self.assertTrue(self.panel.table.isRowHidden(1))
        self.assertFalse(any(self.doc.getObject('Panel%d' % i) for i in range(3)))
        self.assertFalse(self.panel.table.signalsBlocked())
        self.assertTrue(self.panel.table.updatesEnabled())

    def test_master_visibility_tracks_add_remove_with_table_signals_blocked(self):
        table = self.panel.table
        editor = self.panel._bulk_editor
        self.assertFalse(table.isRowHidden(editor.separator_row))
        self.assertFalse(table.isRowHidden(editor.row))
        blocked = table.blockSignals(True)
        for count in (2, 1, 0):
            table.removeRow(count)
            self.assertEqual(editor.separator_row, count)
            self.assertEqual(table.isRowHidden(editor.row), count < 2)
            self.assertEqual(table.isRowHidden(editor.separator_row), count < 2)
            self.assertEqual(table.columnSpan(editor.separator_row, 0), 6)
        for count in (1, 2, 3):
            obj = self.doc.getObject('Panel%d' % (count - 1))
            self.assertTrue(self.panel._add_preview_object_to_table(self.doc, obj.Name))
            self.assertFalse(table.isRowHidden(count - 1))
            self.assertEqual(table.isRowHidden(editor.row), count < 2)
            self.assertEqual(table.isRowHidden(editor.separator_row), count < 2)
            self.assertEqual(table.columnSpan(editor.separator_row, 0), 6)
            self.assertEqual(table.columnSpan(count - 1, 0), 1)
        table.blockSignals(blocked)


if __name__ == '__main__': unittest.main(verbosity=2)
