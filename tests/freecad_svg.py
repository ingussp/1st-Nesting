"""Multi-file SVG imports, independent contours and preserved hole topology."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freecad_bridges import App, Part, QtGui, QtCore, APPLICATION, rectangle
from Nesting1stImport2D import _split_svg_shapes, import_svg_to_preview
from Nesting1stExport import _extract_part_candidate_wires
from Nesting1stGui import NestingTaskPanel

ROOT = Path(__file__).resolve().parents[1]


def rect_wire(x, y, width, height):
    points = rectangle(x, y, width, height)
    vectors = [App.Vector(a, b, 0) for a, b in points]
    return Part.makePolygon(vectors + vectors[:1])


class SVGTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(os.environ.get('BRIDGE_TEST_DIR', str(ROOT / 'tests'))).resolve()
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(temporary_root)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.assertEqual(Path(self.temp.name).resolve().parent, temporary_root)
        self.folder = Path(self.temp.name)
        self.doc = App.newDocument('Nesting_Preview')
        self.panel = SimpleNamespace(preview_doc_name=self.doc.Name)

    def tearDown(self):
        for name in list(App.listDocuments()): App.closeDocument(name)
        self.temp.cleanup()
        tempfile.tempdir = self.previous_tempdir

    def svg(self, name, geometry):
        path = self.folder / name
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
                        'viewBox="0 0 100 100">' + geometry + '</svg>', encoding='utf-8')
        return path

    def test_one_path_contains_separate_parts_and_holes(self):
        path = self.svg('two_parts.svg', '<path fill-rule="evenodd" d="M0 0H30V30H0Z '
                        'M5 5H10V10H5Z M40 0H70V30H40Z M45 5H50V10H45Z"/>')
        names = import_svg_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 2)
        for index, name in enumerate(names, 1):
            obj = self.doc.getObject(name)
            self.assertEqual(len(obj.Shape.Wires), 2)
            self.assertEqual(len(_extract_part_candidate_wires(obj, .01)), 2)
            self.assertEqual(obj.SVGSourceFile, 'two_parts.svg')
            self.assertEqual(obj.SVGPartNumber, index)
            self.assertIn('[%d]' % index, obj.Label)

    def test_nested_material_island_is_a_separate_part(self):
        wires = [rect_wire(0, 0, 50, 50), rect_wire(5, 5, 40, 40),
                 rect_wire(10, 10, 30, 30), rect_wire(15, 15, 20, 20)]
        components = _split_svg_shapes([Part.makeCompound(wires)])
        self.assertEqual(len(components), 2)
        self.assertEqual([len(wires.Wires) for wires, _ in components], [2, 2])
        self.assertEqual([round(material.Area) for _, material in components], [900, 500])

    def test_overlapping_and_touching_outer_contours_are_not_grouped(self):
        components = _split_svg_shapes([Part.makeCompound([rect_wire(0, 0, 20, 20),
                                  rect_wire(10, 5, 20, 20), rect_wire(30, 5, 10, 10)])])
        self.assertEqual(len(components), 3)

    def test_coincident_fill_stroke_duplicates_do_not_become_parts_or_holes(self):
        outer = rect_wire(0, 0, 20, 20)
        hole = Part.Wire([Part.makeCircle(3, App.Vector(10, 10, 0))])
        components = _split_svg_shapes([Part.makeCompound([outer, hole]),
                                       Part.makeCompound([outer.copy(), hole.copy()])])
        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0][0].Wires), 2)
        self.assertTrue(any(type(e.Curve).__name__ == 'Circle' for e in components[0][0].Edges))

    def test_transformed_groups_keep_native_circle_and_hole_geometry(self):
        path = self.svg('groups.svg', '<g transform="translate(10 20) rotate(30)">'
                        '<path fill="none" stroke="black" d="M0 0H20V20H0Z"/>'
                        '<circle cx="10" cy="10" r="3" fill="none" stroke="black"/></g>'
                        '<rect x="60" y="60" width="10" height="15"/>')
        names = import_svg_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 2)
        self.assertEqual(sorted(len(self.doc.getObject(name).Shape.Wires) for name in names), [1, 2])
        self.assertTrue(all(self.doc.getObject(name).Shape.isValid() for name in names))

    def test_actual_duplicate_svg_circle_is_imported_once(self):
        path = self.svg('duplicate.svg', '<circle cx="20" cy="20" r="10"/>'
                        '<circle cx="20" cy="20" r="10" fill="none" stroke="black"/>')
        names = import_svg_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 1)
        self.assertEqual(len(self.doc.getObject(names[0]).Shape.Wires), 1)

    def test_failed_file_removes_new_geometry_and_keeps_existing_parts(self):
        existing = self.doc.addObject('Part::Feature', 'KeepPart')
        existing.Shape = rect_wire(0, 0, 10, 10)
        self.doc.recompute()
        before = existing.Shape.exportBrepToString()
        path = self.svg('open.svg', '<path fill="none" stroke="black" d="M0 0L20 20"/>')
        self.assertEqual(import_svg_to_preview(self.panel, str(path)), [])
        self.assertEqual([obj.Name for obj in self.doc.Objects], ['KeepPart'])
        self.assertEqual(existing.Shape.exportBrepToString(), before)

    def test_native_import_failure_does_not_leave_partial_objects(self):
        existing = self.doc.addObject('Part::Feature', 'KeepPart')
        existing.Shape = rect_wire(0, 0, 10, 10)
        self.doc.recompute()
        path = self.svg('failed.svg', '<rect width="20" height="20"/>')
        def incomplete_import(*args):
            partial = self.doc.addObject('Part::Feature', 'PartialSVG')
            partial.Shape = rect_wire(20, 0, 10, 10)
            return False
        with patch('Nesting1stImport2D._import_svg', side_effect=incomplete_import):
            self.assertEqual(import_svg_to_preview(self.panel, str(path)), [])
        self.assertEqual([obj.Name for obj in self.doc.Objects], ['KeepPart'])

    def test_batch_adds_actual_parts_to_table_and_restores_update_state(self):
        paths = [self.svg('first.svg', '<path fill-rule="evenodd" d="M0 0H20V20H0Z M5 5H10V10H5Z '
                            'M40 0H60V20H40Z"/>'),
                 self.folder / 'missing.svg', self.svg('second.svg', '<circle cx="20" cy="20" r="10"/>')]
        class Preferences:
            def GetString(self, key, default=''): return default
            def GetBool(self, key, default=False): return default
            def GetInt(self, key, default=0): return default
            def GetUnsigned(self, key, default=0): return default
            def GetFloat(self, key, default=0): return default
            def __getattr__(self, name):
                if name.startswith(('Set', 'Rem')): return lambda *args: None
                raise AttributeError(name)
        with patch.object(App, 'ParamGet', return_value=Preferences()):
            panel = NestingTaskPanel()
        before = panel.table.rowCount()
        try:
            with patch.object(QtGui.QFileDialog, 'getOpenFileNames', return_value=([str(p) for p in paths], '')) as choose, \
                    patch.object(QtGui.QFileDialog, 'getOpenFileName', side_effect=AssertionError('single file chooser used')), \
                    patch.object(QtGui.QMessageBox, 'exec_', return_value=QtGui.QMessageBox.Ok) as warning, \
                    patch.object(panel, 'ensure_preview_doc', return_value=self.doc), \
                    patch.object(panel, 'update_grain_layout_and_perimeters') as update, \
                    patch.object(panel, '_fit_all_views') as fit:
                panel.import_svg_2d()
            choose.assert_called_once(); warning.assert_called_once()
            update.assert_called_once(); fit.assert_called_once()
            self.assertEqual(panel.table.rowCount() - before, 3)
            rows = [panel.table.item(row, 0) for row in range(panel.table.rowCount())]
            imported = [item for item in rows if item and self.doc.getObject(str(item.data(QtCore.Qt.UserRole)))
                        and hasattr(self.doc.getObject(str(item.data(QtCore.Qt.UserRole))), 'SVGSourceFile')]
            self.assertEqual(len(imported), 3)
            self.assertEqual(len({item.data(QtCore.Qt.UserRole) for item in imported}), 3)
            self.assertFalse(panel.table.signalsBlocked())
            self.assertTrue(panel.table.updatesEnabled())
            self.assertFalse(panel._suppress_qty_update)
        finally:
            panel._nesting_manager.shutdown()
            try: panel._selection_observer._unregister()
            except AttributeError: pass
            panel.form.close()

    def test_deepnest_letter_fixtures_have_independent_profiles(self):
        fixtures = Path(os.environ.get('SVG_TEST_ASSETS', str(ROOT.parent / 'fixtures')))
        for name, expected_parts, expected_wires in [('henny-penny.svg', 27, 36),
                                                       ('mrs-saint-delafield.svg', 27, 44)]:
            path = fixtures / name
            self.assertTrue(path.exists(), 'Download the Deepnest fixtures or set SVG_TEST_ASSETS.')
            names = import_svg_to_preview(self.panel, str(path))
            self.assertEqual(len(names), expected_parts, name)
            parts = [self.doc.getObject(key) for key in names]
            self.assertEqual(sum(len(part.Shape.Wires) for part in parts), expected_wires, name)
            for part in parts:
                self.assertTrue(part.Shape.isValid(), part.Label)
                # The same contour preparation used by nesting must accept
                # every letter and its attached holes as one independent part.
                candidates = _extract_part_candidate_wires(part, .01)
                self.assertEqual(len(candidates), len(part.Shape.Wires), part.Label)


if __name__ == '__main__': unittest.main(verbosity=2)
