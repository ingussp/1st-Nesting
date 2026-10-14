"""Real FreeCAD/STEP/DXF/SVG import-to-result-to-DXF integration checks."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freecad_bridges import (App, Part, QtGui, APPLICATION, languages, rectangle,
                             solid_example, ref, create_document)
import Import
from Nesting1stResult import NestingResultImporter
from Nesting1stRuntime import snapshot_part
from Nesting1stExport import _extract_part_candidate_wires, _normalize_polygon, _points_min_xy
from Nesting1stResultDXF import export_document, export_from_panel, result_document, top_view_shape

ROOT = Path(__file__).resolve().parents[1]


def curved_profile():
    v = App.Vector
    edges = [Part.makeLine(v(0, 0, 0), v(20, 0, 0)),
             Part.Arc(v(20, 0, 0), v(35, 15, 0), v(20, 30, 0)).toShape(),
             Part.makeLine(v(20, 30, 0), v(0, 30, 0)), Part.makeLine(v(0, 30, 0), v(0, 0, 0))]
    return Part.Face(Part.Wire(edges)).cut(Part.Face(Part.Wire([Part.makeCircle(3, v(8, 15, 0))])))


def entities(path):
    """Read only ASCII DXF entity records, without extra Python dependencies."""
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    pairs = [(int(lines[i].strip()), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    result = []
    active = False
    current = None
    for code, value in pairs:
        if code == 2 and value == 'ENTITIES': active = True; continue
        if not active: continue
        if code == 0:
            if current is not None: result.append(current)
            if value == 'ENDSEC': break
            current = {'type': value}
        elif current is not None:
            current[code] = value
    return result


class DXFTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(os.environ.get('BRIDGE_TEST_DIR', str(ROOT / 'tests'))).resolve()
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.assertEqual(Path(self.temp.name).resolve().parent, temporary_root)
        self.folder = Path(self.temp.name)
        self.preview = App.newDocument('Nesting_Preview')
        self.panel = SimpleNamespace(preview_doc_name=self.preview.Name, form=QtGui.QWidget(), display_units='inch')

    def tearDown(self):
        self.panel.form.close()
        for name in list(App.listDocuments()): App.closeDocument(name)
        self.temp.cleanup()

    def make_result(self, source, source_type='3d', sheet=0):
        contours = _extract_part_candidate_wires(source, .02)
        ox, oy = _points_min_xy(contours[0])
        part = dict(snapshot_part(source, .02, contours), source_part_index=0, part_id='part_0',
                    label=source.Label, preview_object_name=source.Name, source_type=source_type,
                    points=_normalize_polygon(contours[0]),
                    holes=[[[x - ox, y - oy] for x, y in hole] for hole in contours[1:]])
        data = dict(sourceParts=[part],
                    sheets=[dict(width=200, height=160, sheet_instance_index=i) for i in range(sheet + 1)],
                    placements=[dict(id='part_0', source_part_index=0, instance_index=0,
                                     sheet_instance_index=sheet, x=42.5, y=13.25, rotation=37)], unplaced=[])
        importer = NestingResultImporter(self.panel)
        self.assertTrue(importer.import_result(data, show_summary=False))
        self.panel._nesting_manager = SimpleNamespace(importer=importer)
        return importer.result_doc

    def check_export(self, source, source_type='3d', sheet=0):
        before = source.Shape.exportBrepToString()
        doc = self.make_result(source, source_type, sheet)
        placed = doc.getObject('Nesting_part_0')
        self.assertEqual(placed.TypeId, 'Part::Feature')
        before_result = placed.Shape.exportBrepToString()
        expected = top_view_shape(placed)
        expected_circles = [edge for edge in expected.Edges if type(edge.Curve).__name__ == 'Circle']
        expected_splines = [edge for edge in expected.Edges if type(edge.Curve).__name__ == 'BSplineCurve']
        self.assertTrue(expected_circles or expected_splines)
        documents = set(App.listDocuments())
        path = export_document(doc, self.folder / 'layout')
        self.assertEqual(path.suffix, '.dxf')
        self.assertEqual(set(App.listDocuments()), documents)
        self.assertIs(App.ActiveDocument, doc)
        records = entities(path)
        circles = [e for e in records if e['type'] == 'CIRCLE']
        arcs = [e for e in records if e['type'] == 'ARC']
        if expected_circles:
            self.assertEqual(len(circles), 1, records)
        else:
            # FreeCAD 1.0's SVG importer turns all edges into B-splines.
            # Verify they remain CAD splines rather than sampled polylines.
            self.assertEqual(len([e for e in records if e['type'] == 'SPLINE']), len(expected_splines))
        # FreeCAD's SVG importer represents SVG arcs as trimmed ellipses,
        # even when the two radii match. Retain that analytic curve too.
        self.assertGreaterEqual(len(arcs) + len([e for e in records if e['type'] in ('ELLIPSE', 'SPLINE')]), 1, records)
        self.assertTrue(all(e['type'] in ('LINE', 'ARC', 'CIRCLE', 'ELLIPSE', 'SPLINE') for e in records))
        self.assertTrue(all(e[8].startswith('Sheet_%d_' % (sheet + 1)) for e in records))
        self.assertTrue(all(abs(float(e.get(code, 0))) < 1e-8 for e in records for code in (30, 31)))
        if circles:
            true_circle = next(e for e in expected_circles if e.isClosed())
            self.assertAlmostEqual(float(circles[0][40]), true_circle.Curve.Radius, places=7)
            self.assertAlmostEqual(float(circles[0][10]), true_circle.Curve.Center.x, places=7)
            self.assertAlmostEqual(float(circles[0][20]), true_circle.Curve.Center.y, places=7)
        self.assertEqual(source.Shape.exportBrepToString(), before)
        self.assertEqual(placed.Shape.exportBrepToString(), before_result)
        # Read the actual exported file back with the native DXF importer.
        read_doc = App.newDocument('DXFRoundtrip')
        Import.readDXF(str(path), read_doc.Name)
        shapes = [o.Shape for o in read_doc.Objects if hasattr(o, 'Shape') and not o.Shape.isNull()]
        self.assertTrue(shapes)
        restored = Part.makeCompound(shapes)
        self.assertAlmostEqual(sum(e.Length for e in restored.Edges), sum(e.Length for e in expected.Edges), places=6)
        self.assertAlmostEqual(restored.BoundBox.XMin, expected.BoundBox.XMin, places=6)
        self.assertAlmostEqual(restored.BoundBox.YMax, expected.BoundBox.YMax, places=6)
        return doc, path

    def test_freecad_partfeature_keeps_circles_arcs_and_sheet_offset(self):
        obj = self.preview.addObject('Part::Feature', 'NativePanel')
        obj.Shape = curved_profile().extrude(App.Vector(0, 0, 6))
        self.check_export(obj, sheet=1)

    def test_actual_step_file_keeps_circles_and_arcs(self):
        original = self.preview.addObject('Part::Feature', 'InputSTEP')
        original.Shape = curved_profile().extrude(App.Vector(0, 0, 6))
        path = self.folder / 'source.step'
        Part.export([original], str(path))
        obj = self.preview.addObject('Part::Feature', 'ImportedSTEP')
        obj.Shape = Part.read(str(path))
        self.check_export(obj)

    def test_actual_dxf_import_keeps_circles_and_arcs(self):
        from Nesting1stImport2D import import_dxf_to_preview
        original = self.preview.addObject('Part::Feature', 'InputDXF')
        original.Shape = Part.makeCompound(curved_profile().Wires)
        path = self.folder / 'source.dxf'
        Import.writeDXFObject([original], str(path), 14, False)
        import FreeCADGui as Gui
        import importDXF
        # The bundled importer calls GUI cursor helpers even in headless mode.
        # Stub only those presentation helpers; the real DXF parser runs.
        with patch.object(importDXF, 'FreeCADGui', Gui, create=True), \
                patch.object(Gui, 'suspendWaitCursor', create=True), patch.object(Gui, 'resumeWaitCursor', create=True):
            names = import_dxf_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 1)
        self.check_export(self.preview.getObject(names[0]), 'dxf')

    def test_actual_svg_import_keeps_circles_and_arcs(self):
        from Nesting1stImport2D import import_svg_to_preview
        path = self.folder / 'source.svg'
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30">'
                        '<path d="M0 0 H20 A15 15 0 0 1 20 30 H0 Z" fill="none" stroke="black"/>'
                        '<circle cx="8" cy="15" r="3" fill="none" stroke="black"/></svg>', encoding='utf-8')
        names = import_svg_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 1)
        self.check_export(self.preview.getObject(names[0]), 'svg')

    def test_svg_bezier_remains_a_cad_spline(self):
        from Nesting1stImport2D import import_svg_to_preview
        path = self.folder / 'bezier.svg'
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30">'
                        '<path d="M0 0 H20 C40 0 40 30 20 30 H0 Z" fill="none" stroke="black"/>'
                        '<circle cx="8" cy="15" r="3" fill="none" stroke="black"/></svg>', encoding='utf-8')
        names = import_svg_to_preview(self.panel, str(path))
        self.assertEqual(len(names), 1)
        _, exported = self.check_export(self.preview.getObject(names[0]), 'svg')
        self.assertTrue(any(e['type'] == 'SPLINE' for e in entities(exported)))

    def test_rational_splines_retain_weights_and_geometry(self):
        # This also covers older SVG importers that represent circles as NURBS.
        obj = self.preview.addObject('Part::Feature', 'RationalNURBS')
        obj.Shape = Part.makeCompound(curved_profile().Wires).toNurbs()
        _, path = self.check_export(obj, 'svg')
        records = entities(path)
        self.assertTrue(any(e['type'] == 'SPLINE' and int(e[70]) & 4 for e in records))

    def test_visible_blind_pocket_and_through_hole_are_preserved(self):
        obj = self.preview.addObject('Part::Feature', 'MachinedPanel')
        obj.Shape = curved_profile().extrude(App.Vector(0, 0, 6)).cut(
            Part.makeCylinder(2, 2, App.Vector(8, 5, 4)))
        doc = self.make_result(obj)
        path = export_document(doc, self.folder / 'machining.dxf')
        circles = [e for e in entities(path) if e['type'] == 'CIRCLE']
        self.assertEqual(sorted(float(e[40]) for e in circles), [2, 3])

    def test_bridged_result_exports_joined_perimeter_without_attachment_edges(self):
        layout = solid_example()
        layout.add_bridge(ref(0, 25, 15), ref(1, 35, 15), 2)
        doc = create_document(layout, languages.tr)
        self.assertIs(result_document(self.panel), doc)
        path = export_document(doc, self.folder / 'bridged.dxf')
        records = entities(path)
        self.assertTrue(all(e[8] == 'Sheet_1_JoinedParts_1' for e in records))
        # Full perimeter has 12 outer edges and four edges around the hole;
        # no two rectangles, stock border or separate bridge is exported.
        self.assertEqual(len(records), 16)

    def test_saved_result_and_failure_preserve_documents_and_existing_file(self):
        source = self.preview.addObject('Part::Feature', 'Panel')
        source.Shape = curved_profile().extrude(App.Vector(0, 0, 6))
        doc = self.make_result(source)
        saved = self.folder / 'result.FCStd'
        doc.saveAs(str(saved)); App.closeDocument(doc.Name)
        doc = App.openDocument(str(saved))
        self.assertIs(result_document(SimpleNamespace()), doc)
        path = export_document(doc, self.folder / 'saved.dxf')
        before = path.read_bytes()
        documents = set(App.listDocuments())
        with patch.object(Import, 'writeDXFObject', side_effect=RuntimeError('simulated writer error')):
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                export_document(doc, path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(App.listDocuments()), documents)
        self.assertIs(App.ActiveDocument, doc)
        self.assertEqual(list(self.folder.glob('.nesting-dxf-*')), [])

    def test_panel_buttons_share_equal_width_row_and_export_callback(self):
        from Nesting1stGui import NestingTaskPanel
        with patch.object(App, 'ParamGet', return_value=SimpleNamespace(
            GetString=lambda key, default='': default, GetBool=lambda key, default=False: default,
            GetInt=lambda key, default=0: default, GetUnsigned=lambda key, default=0: default,
            GetFloat=lambda key, default=0: default)):
            panel = NestingTaskPanel()
        panel.form.show(); APPLICATION.processEvents()
        self.assertLessEqual(abs(panel.export_result_svg_btn.width() - panel.export_result_dxf_btn.width()), 1)
        with patch('Nesting1stResultDXF.export_from_panel') as exported:
            panel.export_result_dxf_btn.click(); exported.assert_called_once_with(panel)
        with patch.object(QtGui.QMessageBox, 'information') as message:
            self.assertFalse(export_from_panel(panel)); self.assertTrue(message.called)
        panel._nesting_manager.shutdown()
        try: panel._selection_observer._unregister()
        except AttributeError: pass
        panel.form.close()


if __name__ == '__main__': unittest.main(verbosity=2)
