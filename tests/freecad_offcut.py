"""Measured offcut areas, units, CAD annotation and part-only DXF selection."""
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from freecad_bridges import App, Part, rectangle, languages
from Nesting1stResult import NestingResultImporter, _normalize_result
from Nesting1stResultDXF import result_parts
from Nesting1stResultSVG import render_result_svg
from Nesting1stReusableOffcut import reusable_offcut, offcut_text, create_offcut_outline
from Nesting1stExport import build_nesting_config


def example():
    outer = rectangle(20, 0, 80, 100)
    holes = [rectangle(50, 40, 10, 10)]
    return dict(units='mm', summary=dict(placed_count=1, utilisation=20),
        sheets=[dict(id=11, type='rect', width=100, height=100, sheet_instance_index=0),
                dict(id=22, type='rect', width=100, height=100, sheet_instance_index=1)],
        placements=[dict(id='test_part', placed=True, source_part_index=0, sheet_instance_index=1,
            absolute_points=rectangle(0, 0, 20, 100), absolute_holes=[])],
        sourceParts=[dict(source_part_index=0, source_type='2d')], unplaced=[],
        reusableOffcut=dict(enabled=True, evaluated=True, minWidthMm=3.25, sheetId=22,
            area=7900.0, points=outer, holes=holes))


class OffcutTests(unittest.TestCase):
    def tearDown(self):
        languages._active_language = 'en'
        for name in list(App.listDocuments()): App.closeDocument(name)

    def test_all_units_export_spacing_plus_one_mm(self):
        for mode in ('first', 'continuous'):
            for spacing in (0, .01, 2.25, 25.4):
                with self.subTest(mode=mode, spacing=spacing):
                    config = build_nesting_config(mode=mode, spacing=spacing)
                    self.assertEqual(config['reusableOffcut'], dict(enabled=True, minWidthMm=spacing+1))

    def test_area_excludes_holes_and_uses_own_sheet_not_all_stock(self):
        report = reusable_offcut(example())
        self.assertEqual(report['area'], 7900)
        self.assertEqual(report['percentage'], 79)
        self.assertEqual(report['sheet_index'], 1)
        data = example()
        data['sheets'][1] = dict(data['sheets'][1], type='polygon', outer=rectangle(0,0,100,100),
                                  holes=[rectangle(50,40,10,10)])
        self.assertAlmostEqual(reusable_offcut(data)['percentage'], 7900/9900*100)

    def test_inches_convert_area_once_and_do_not_mutate_result(self):
        data = example(); before = copy.deepcopy(data)
        languages._active_language = 'en'
        for _ in range(4):
            self.assertEqual(offcut_text(data, languages.tr), 'Single-piece offcut: 7900.00 mm² (79.00 %)')
            self.assertEqual(offcut_text(data, languages.tr, 'inch'), 'Single-piece offcut: 12.25 in² (79.00 %)')
        self.assertEqual(data, before)

    def test_missing_invalid_or_disabled_is_not_reported_as_zero(self):
        for change in ({'evaluated':False}, {'enabled':False}, {'area':float('nan')}, {'area':-1},
                       {'sheetId':999}, {'points':[]}, {'area':8000}, {'minWidthMm':float('inf')}):
            data = example(); data['reusableOffcut'].update(change)
            self.assertIsNone(reusable_offcut(data), change)
            self.assertIn('unavailable', offcut_text(data, languages.tr))
        self.assertIsNone(reusable_offcut({}))
        data = example(); data['reusableOffcut'].update(area=0, points=[], holes=[], sheetId=None)
        self.assertEqual(reusable_offcut(data)['area'], 0)
        self.assertIn('0.00 mm²', offcut_text(data, languages.tr))

    def test_conservative_texture_group_report_is_retained(self):
        data = example()
        data['grainMatchingEnvelopeReport'] = data.pop('reusableOffcut')
        self.assertEqual(reusable_offcut(data)['area'], 7900)

    def test_wire_annotation_follows_correct_parent_sheet_and_holes(self):
        data = example(); doc = App.newDocument('Nesting_Result')
        groups = {i:doc.addObject('App::Part','SheetGroup_%d'%i) for i in (0,1)}
        groups[1].Placement.Base = App.Vector(150,0,0)
        importer = NestingResultImporter(SimpleNamespace(display_units='mm'))
        importer.result_doc=doc; importer.result_data=data; importer.sheet_groups=groups
        obj=create_offcut_outline(importer,languages.tr); doc.recompute()
        self.assertIn(obj, groups[1].Group)
        self.assertEqual(len(obj.Shape.Wires), 2)
        self.assertAlmostEqual(obj.ReusableArea.Value, 7900)
        self.assertAlmostEqual(obj.MinimumWidth.Value, 3.25)
        self.assertAlmostEqual(obj.SheetPercentage, 79)
        self.assertAlmostEqual(obj.getGlobalPlacement().Base.x, 150)
        self.assertAlmostEqual(obj.Shape.BoundBox.XMin, 20)
        # Offcut outlines are not laser-cutting paths in the part-only exporter.
        part=doc.addObject('Part::Feature','Nesting_test_part')
        part.Shape=Part.makeBox(20,100,3)
        self.assertEqual(result_parts(doc,data),[(1,part)])
        lines=[]
        importer._make_annotation=lambda text, *args: lines.append(str(text))
        importer._sheet_layout_x=300; importer._sheet_max_y=100
        importer._create_result_info()
        self.assertIn('Sheet waste',lines[2])
        self.assertEqual(lines[3], 'Single-piece offcut: 7900.00 mm² (79.00 %)')

    def test_svg_report_contains_measured_contour_and_area(self):
        root=ET.fromstring(render_result_svg(example(),languages.tr))
        outlines=root.findall('.//{http://www.w3.org/2000/svg}path[@class="reusable-offcut"]')
        self.assertEqual(len(outlines),1)
        self.assertIn('M 20.000000,0.000000',outlines[0].attrib['d'])
        self.assertIn('7900.00 mm²', ''.join(root.itertext()))

    def test_result_import_refreshes_the_outline_for_2d_and_3d(self):
        for source_type in ('3d', 'dxf', 'svg'):
            with self.subTest(source_type=source_type):
                data=example()
                wire=Part.makePolygon([App.Vector(x,y,0) for x,y in rectangle(0,0,20,100)+[[0,0]]])
                shape=Part.Face(wire).extrude(App.Vector(0,0,6)) if source_type=='3d' else wire
                data['sourceParts'][0].update(points=rectangle(0,0,20,100), holes=[],
                    shape_brep=shape.exportBrepToString(), normalization_offset=[0,0,0],
                    label='Test',source_type=source_type)
                importer=NestingResultImporter(SimpleNamespace(display_units='mm'))
                self.assertTrue(importer.import_result(data,show_summary=False))
                doc=importer.result_doc
                self.assertIsNotNone(doc.getObject('Reusable_offcut'))
                self.assertEqual(len(result_parts(doc)),1)
                data['reusableOffcut'].update(points=rectangle(20,0,80,95),holes=[],area=7600)
                self.assertTrue(importer.import_result(data,show_summary=False))
                self.assertIs(importer.result_doc,doc)
                self.assertEqual(len([o for o in doc.Objects if o.Name.startswith('Reusable_offcut')]),1)
                self.assertAlmostEqual(doc.Reusable_offcut.ReusableArea.Value,7600)
                self.assertAlmostEqual(doc.Reusable_offcut.Shape.BoundBox.YMax,95)
                App.closeDocument(doc.Name)

    def test_all_50_translation_formats_are_compatible(self):
        folder=Path(__file__).resolve().parents[1]/'lng'
        for entry in json.loads((folder/'index.json').read_text(encoding='utf-8')):
            code=entry['code']; languages._active_language=code
            with self.subTest(language=code):
                text=offcut_text(example(),languages.tr)
                self.assertIn('7900.00 mm²',text)
                self.assertNotEqual(text,languages.tr('result_info_single_piece_offcut_unavailable'))
        languages._active_language='lv'
        self.assertTrue(offcut_text(example(),languages.tr).startswith('Viena gabala atgriezums:'))


if __name__ == '__main__': unittest.main()
