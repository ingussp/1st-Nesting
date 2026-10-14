"""Native FreeCAD geometry and Qt integration for mixed material gauges."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from freecad_bridges import App, Part, QtGui, QtCore, APPLICATION, rectangle
from Nesting1stGui import NestingTaskPanel
from Nesting1stThickness import object_thicknesses, compare_parts, MISMATCH_COLOR, MARKED_ROLE


class Preferences:
    def GetString(self, key, default=''): return default
    def GetBool(self, key, default=False): return default
    def GetInt(self, key, default=0): return default
    def GetUnsigned(self, key, default=0): return default
    def GetFloat(self, key, default=0): return default
    def __getattr__(self, name):
        if name.startswith(('Set', 'Rem')): return lambda *args: None
        raise AttributeError(name)


class ThicknessTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Nesting_Preview')
        with patch.object(App, 'ParamGet', return_value=Preferences()):
            self.panel = NestingTaskPanel()
        self.panel._fit_all_views = lambda: None
        self.checker = self.panel._thickness_checker
        self.warning = patch.object(self.checker, '_show_warning').start()

    def tearDown(self):
        self.checker.timer.stop()
        self.panel._nesting_manager.shutdown()
        self.panel._selection_observer._unregister()
        self.panel.form.close()
        self.panel.form.deleteLater()
        patch.stopall()
        for name in list(App.listDocuments()):
            App.closeDocument(name)

    def add(self, thickness, name=None):
        name = name or 'Panel%d' % self.panel.added_count
        obj = self.doc.addObject('Part::Feature', name)
        obj.Shape = Part.makeBox(30, 40, thickness)
        self.assertTrue(self.panel._add_preview_object_to_table(self.doc, obj.Name))
        return obj

    def marked(self, row):
        item = self.panel.table.item(row, 0)
        return bool(item is not None and item.data(MARKED_ROLE))

    def test_equal_gauges_and_cad_noise_do_not_warn(self):
        self.add(6)
        self.add(6.0000001)
        result = self.checker.refresh()
        self.assertFalse(result['mismatched'])
        self.warning.assert_not_called()
        self.assertFalse(self.marked(0))
        self.assertFalse(self.marked(1))

    def test_majority_gauge_marks_full_row_and_cell_controls(self):
        self.add(8, 'Wrong')
        self.add(6)
        self.add(6)
        result = self.checker.refresh()
        self.assertEqual(result['reference'], 6)
        self.assertEqual(result['mismatched'], {'Wrong'})
        for col in (0, 1, 2):
            item = self.panel.table.item(0, col)
            self.assertEqual(item.background().color().name(), MISMATCH_COLOR)
            self.assertIn('8 mm', item.toolTip())
            self.assertIn('6 mm', item.toolTip())
        for col in (3, 4, 5):
            widget = self.panel.table.cellWidget(0, col)
            self.assertEqual(widget.palette().color(QtGui.QPalette.Window).name(), MISMATCH_COLOR)
            self.assertIn(MISMATCH_COLOR, widget.styleSheet())
        self.assertFalse(self.marked(1))
        self.assertFalse(self.marked(2))
        self.assertFalse(self.marked((self.panel.table.rowCount() - self.panel.control_rows)))
        self.warning.assert_called_once()
        self.checker.refresh()
        self.warning.assert_called_once()

    def test_tie_uses_first_part_and_quantity_does_not_change_reference(self):
        self.add(6)
        self.add(8)
        self.panel.table.item(1, 1).setText('100')
        result = self.checker.refresh()
        self.assertEqual(result['reference'], 6)
        self.assertTrue(self.marked(1))

    def test_orientation_change_updates_depth_and_clears_mark(self):
        self.add(6)
        obj = self.add(8)
        original = QtGui.QBrush(QtGui.QColor('#e4e4e4'))
        self.panel.table.item(1, 0).setBackground(original)
        self.panel.table.item(1, 0).setToolTip('Original group tooltip')
        self.checker.refresh()
        obj.Shape = Part.makeBox(30, 40, 6)
        self.doc.recompute()
        self.checker.refresh()
        item = self.panel.table.item(1, 0)
        self.assertFalse(self.marked(1))
        self.assertEqual(item.background().color().name(), '#e4e4e4')
        self.assertEqual(item.toolTip(), 'Original group tooltip')
        for col in (3, 4, 5):
            self.assertEqual(self.panel.table.cellWidget(1, col).styleSheet(), '')
        self.assertIsNone(self.checker.last_warning)
        obj.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90)
        self.checker.refresh()
        self.assertTrue(self.marked(1))
        self.assertAlmostEqual(object_thicknesses(obj)[0], 30)
        obj.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 180)
        self.checker.refresh()
        self.assertFalse(self.marked(1))

    def test_flat_dxf_svg_have_unknown_gauge_and_are_ignored(self):
        self.add(6)
        for source in ('DXF', 'SVG'):
            obj = self.doc.addObject('Part::Feature', source)
            obj.Label = source + ': contour'
            obj.Shape = Part.makePolygon([App.Vector(x, y, 0) for x, y in rectangle(0, 0, 10, 20) + [[0, 0]]])
            self.panel._add_preview_object_to_table(self.doc, obj.Name)
        self.assertFalse(self.checker.refresh()['mismatched'])
        self.warning.assert_not_called()

    def test_compound_solids_measured_separately_and_z_offsets_ignored(self):
        obj = self.add(6)
        first = Part.makeBox(30, 40, 6)
        second = Part.makeBox(30, 40, 6, App.Vector(50, 0, 20))
        obj.Shape = Part.makeCompound([first, second])
        self.assertEqual(object_thicknesses(obj), [6, 6])
        second = Part.makeBox(30, 40, 8, App.Vector(50, 0, 20))
        obj.Shape = Part.makeCompound([first, second])
        self.assertEqual(object_thicknesses(obj), [6, 8])
        self.add(6)
        self.assertEqual(self.checker.refresh()['mismatched'], {obj.Name})

    def test_partdesign_tip_blind_holes_keep_full_material_gauge(self):
        self.add(6)
        body = self.doc.addObject('PartDesign::Body', 'MachinedBody')
        tip = body.newObject('PartDesign::Feature', 'MachinedTip')
        tip.Shape = Part.makeBox(30, 40, 8).cut(Part.makeCylinder(3, 3, App.Vector(10, 10, 5)))
        body.Tip = tip
        self.doc.recompute()
        self.panel._add_preview_object_to_table(self.doc, body.Name)
        self.assertEqual(object_thicknesses(body), [8])
        self.assertEqual(self.checker.refresh()['mismatched'], {body.Name})

    def test_step_round_trip_keeps_different_gauges(self):
        root = os.environ.get('BRIDGE_TEST_DIR', os.path.dirname(__file__))
        with tempfile.TemporaryDirectory(dir=root) as directory:
            shapes = [Part.makeBox(30, 40, 6), Part.makeBox(20, 40, 8, App.Vector(50, 0, 0))]
            path = os.path.join(directory, 'gauges.step')
            Part.makeCompound(shapes).exportStep(path)
            imported = Part.read(path)
            obj = self.doc.addObject('Part::Feature', 'StepAssembly')
            obj.Shape = imported
            self.panel._add_preview_object_to_table(self.doc, obj.Name)
            self.add(6)
            result = self.checker.refresh()
            self.assertEqual(result['reference'], 6)
            self.assertEqual(result['mismatched'], {obj.Name})

    def test_texture_group_marks_summary_and_only_different_member(self):
        from Nesting1stGrainMatch import _fill_group_row, MEMBER_ROW_KIND, ROW_KIND_ROLE
        self.add(6, 'First')
        self.add(8, 'Wrong')
        self.add(6, 'Third')
        row = (self.panel.table.rowCount() - self.panel.control_rows)
        self.panel.table.insertRow(row)
        _fill_group_row(self.panel, row, ['First', 'Wrong'], 1, ['First', 'Wrong'])
        self.panel.table.item(0, 0).setData(ROW_KIND_ROLE, MEMBER_ROW_KIND)
        self.panel.table.item(1, 0).setData(ROW_KIND_ROLE, MEMBER_ROW_KIND)
        self.checker.refresh()
        self.assertFalse(self.marked(0))
        self.assertTrue(self.marked(1))
        self.assertTrue(self.marked(row))
        self.assertFalse(self.marked((self.panel.table.rowCount() - self.panel.control_rows)))

    def test_removed_row_recalculates_and_clears_stale_marks(self):
        self.add(6)
        self.add(8)
        self.checker.refresh()
        self.panel.table.removeRow(0)
        QApplication = QtGui.QApplication
        QApplication.processEvents()
        self.assertFalse(self.marked(0))
        self.assertIsNone(self.checker.last_warning)

    def test_run_nesting_checks_again_before_engine_starts(self):
        self.add(6)
        self.add(8)
        self.panel.offcuts = [{'points': rectangle(0, 0, 100, 100)}]
        with patch.object(self.panel._nesting_manager, 'is_running', return_value=False), \
             patch.object(self.panel._nesting_manager, 'prepare_and_start') as start:
            self.panel.execute_nesting()
            self.warning.assert_called_once()
            start.assert_called_once()

    def test_inch_display_keeps_mm_comparison(self):
        self.add(6.35)
        self.add(12.7)
        self.panel.display_units = 'inch'
        result = self.checker.refresh()
        self.assertEqual(result['reference'], 6.35)
        self.assertIn('0.5 inch', self.panel.table.item(1, 0).toolTip())
        self.assertIn('0.25 inch', self.panel.table.item(1, 0).toolTip())

    def test_deferred_batch_warns_once_and_refresh_can_be_silent(self):
        self.add(6)
        self.add(8)
        self.add(6)
        APPLICATION.processEvents()
        self.warning.assert_called_once()
        self.checker.refresh(warn=False)
        self.warning.assert_called_once()

    def test_popup_has_details_and_current_units(self):
        self.add(6)
        self.add(8, 'Wrong')
        patch.stopall()
        messages = []
        def close_message():
            for widget in APPLICATION.topLevelWidgets():
                if isinstance(widget, QtGui.QMessageBox) and widget.isVisible():
                    messages.append((widget.windowTitle(), widget.text(), widget.detailedText()))
                    widget.accept()
        QtCore.QTimer.singleShot(0, close_message)
        self.checker.refresh()
        self.assertEqual(len(messages), 1)
        self.assertIn('Reference thickness: 6 mm', messages[0][1])
        self.assertIn('Wrong: 8 mm', messages[0][2])


if __name__ == '__main__':
    unittest.main(verbosity=2)
