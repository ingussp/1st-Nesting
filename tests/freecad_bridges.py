"""Run with FreeCAD's Python: exact corridor checks, real clicks, units and saved CAD."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part
from PySide import QtCore, QtGui
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Nesting1stBridgeModel import BridgeLayout, BridgeError, face, create_document, load_result, store_result_data, style_component
from Nesting1stBridges import BridgeDialog
import Nesting1stLanguages as languages
languages._active_language = 'en'
APPLICATION = QtGui.QApplication.instance() or QtGui.QApplication([])
QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
APPLICATION.setFont(QtGui.QFont('Segoe UI', 10))
try:
    from PySide6 import QtTest
except ImportError:
    from PySide2 import QtTest


def rectangle(x, y, w, h):
    return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]


def example(blocker=False, second_sheet=False):
    contours = [rectangle(5,10,20,30), rectangle(35,10,20,30)]
    if blocker: contours.append(rectangle(29,22,2,2))
    sources = [dict(source_part_index=i, label='Panel '+chr(65+i), source_type='3d' if i==0 else '2d')
               for i in range(len(contours))]
    placements = [dict(source_part_index=i, id='piece_%d'%i, instance_index=i,
                       sheet_instance_index=1 if second_sheet and i==1 else 0,
                       absolute_points=points, absolute_holes=[rectangle(10,20,5,5)] if i==0 else [])
                  for i,points in enumerate(contours)]
    sheets=[dict(width=90,height=60,sheet_instance_index=0)]
    if second_sheet:sheets.append(dict(width=90,height=60,sheet_instance_index=1))
    data=dict(units='mm',job_id='bridge-test',sheets=sheets,sourceParts=sources,placements=placements)
    shapes={0:face(contours[0],placements[0]['absolute_holes']).extrude(App.Vector(0,0,6)),
            1:Part.makeCompound(face(contours[1]).Wires)}
    return BridgeLayout(data,shapes)


def ref(part,x,y):
    return dict(part=part,point=[x,y])


def solid_example():
    layout=example()
    for part in layout.parts:
        part['shape']=part['face'].extrude(App.Vector(0,0,6))
    return layout


class BridgeTests(unittest.TestCase):
    def tearDown(self):
        for name in list(App.listDocuments()):App.closeDocument(name)

    def test_exact_join_removes_internal_cut_edges_and_keeps_holes(self):
        layout=example()
        before=copy.deepcopy(layout.data)
        layout.add_bridge(ref(0,25,15),ref(1,35,15),3.25)
        profile=layout.merged_profile(0)
        self.assertTrue(profile.isValid())
        self.assertEqual(len(profile.Faces),1)
        self.assertEqual(len(profile.Wires),2) # joined exterior + original hole
        self.assertAlmostEqual(profile.Area,1175+32.5,places=5)
        self.assertEqual(layout.data,before)
        doc=create_document(layout,languages.tr)
        self.assertEqual(doc.JoinedParts_1.Shape.ShapeType,'Face')
        self.assertAlmostEqual(doc.JoinedParts_1.Shape.Area,1207.5)
        self.assertEqual(len(doc.JoinedParts_1.Shape.Wires),2)
        self.assertEqual(doc.JoinedParts_1.SourcePartIndices,[0,1])
        self.assertFalse(any(o.Name.startswith(('Bridge_','CutContours_','Part_')) for o in doc.Objects))
        # No original attachment edge remains in the exported perimeter.
        self.assertGreater(doc.JoinedParts_1.Shape.OuterWire.distToShape(Part.Vertex(App.Vector(25,15,0)))[0],1)
        self.assertEqual(json.loads(doc.NestingBridgeData.BridgesJson)['units'],'mm')

    def test_entire_width_blocks_even_when_centreline_is_clear(self):
        layout=example(blocker=True)
        with self.assertRaises(BridgeError) as caught:
            layout.add_bridge(ref(0,25,20),ref(1,35,20),6)
        self.assertEqual(caught.exception.key,'collision')
        self.assertEqual(layout.bridges,[])
        layout.add_bridge(ref(0,25,15),ref(1,35,15),2)

    def test_endpoint_material_holes_sheet_and_duplicate_guards(self):
        cases=[(ref(0,5,15),ref(1,35,15),2,'attachment'),
               (ref(0,25,10),ref(1,35,10),30,'outside_sheet'),
               (ref(0,25,15),ref(0,5,15),2,'different_parts'),
               (ref(0,24,15),ref(1,35,15),2,'edge_required'),
               (ref(0,25,15),ref(1,35,15),float('nan'),'width_invalid')]
        for first,second,width,key in cases:
            with self.subTest(key=key),self.assertRaises(BridgeError) as caught:
                example().add_bridge(first,second,width)
            self.assertEqual(caught.exception.key,key)
        layout=example();layout.parts[0]['holes']=[rectangle(22,20,2,5)]
        layout.parts[0]['face']=face(layout.parts[0]['outer'],layout.parts[0]['holes'])
        with self.assertRaises(BridgeError) as caught:layout.add_bridge(ref(0,25,22),ref(1,35,22),12)
        self.assertEqual(caught.exception.key,'hole_collision')
        layout=example();layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        with self.assertRaises(BridgeError) as caught:layout.add_bridge(ref(1,35,15),ref(0,25,15),2)
        self.assertEqual(caught.exception.key,'duplicate')

    def test_same_sheet_and_diagonal_attachment(self):
        with self.assertRaises(BridgeError) as caught:
            example(second_sheet=True).add_bridge(ref(0,25,15),ref(1,35,15),2)
        self.assertEqual(caught.exception.key,'same_sheet')
        layout=example();layout.add_bridge(ref(0,25,15),ref(1,35,35),2)
        self.assertEqual(len(layout.merged_profile(0).Faces),1)

    def test_unconnected_parts_and_pure_2d_and_3d_documents(self):
        self.assertEqual(len(example().merged_profile(0).Faces),2)
        for three_dimensional in [False,True]:
            layout=example()
            for part in layout.parts:
                part['shape']=part['face'].extrude(App.Vector(0,0,6)) if three_dimensional else Part.makeCompound(part['face'].Wires)
            layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
            doc=create_document(layout,languages.tr)
            self.assertEqual(bool(doc.JoinedParts_1.Shape.Solids),three_dimensional)
            self.assertTrue(doc.JoinedParts_1.Shape.isValid())
            if three_dimensional:
                self.assertEqual(len(doc.JoinedParts_1.Shape.Solids),1)
                self.assertAlmostEqual(doc.JoinedParts_1.Shape.Volume,7170)
                top=[f for f in doc.JoinedParts_1.Shape.Faces if abs(f.CenterOfMass.z-6)<1e-6][0]
                self.assertEqual(len(top.Wires),2)
                self.assertGreater(top.OuterWire.distToShape(Part.Vertex(App.Vector(25,15,6)))[0],.9)
            else:self.assertEqual(len(doc.JoinedParts_1.Shape.Wires),2)
            App.closeDocument(doc.Name)

    def test_sheet_holes_are_obstacles(self):
        layout=example();layout.sheets[0]['holes']=[rectangle(29,14,2,2)]
        layout.sheets[0]['face']=face(layout.sheets[0]['outer'],layout.sheets[0]['holes'])
        with self.assertRaises(BridgeError) as caught:
            layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        self.assertEqual(caught.exception.key,'outside_sheet')

    def test_curved_contours_and_multiple_sheet_output(self):
        def circle(cx,cy,radius):
            return [[cx+radius*math.cos(i*math.pi/32),cy+radius*math.sin(i*math.pi/32)] for i in range(64)]
        data=dict(sheets=[dict(width=70,height=50)],sourceParts=[dict(source_part_index=i,label='Round %d'%i,source_type='3d') for i in range(2)],
                  placements=[dict(source_part_index=i,sheet_instance_index=0,absolute_points=circle(15+30*i,25,10),
                                   absolute_holes=[circle(15,25,3)] if i==0 else []) for i in range(2)])
        layout=BridgeLayout(data)
        layout.add_bridge(ref(0,25,25),ref(1,35,25),4)
        merged=layout.merged_profile(0)
        self.assertEqual(len(merged.Faces),1)
        self.assertEqual(len(merged.Wires),2)
        layout=example(second_sheet=True)
        doc=create_document(layout,languages.tr)
        self.assertEqual(doc.SheetGroup_1.Placement.Base.x,140)
        self.assertEqual(doc.Part_2.Shape.BoundBox.XMin,35)

    def test_closed_input_rings_and_reversed_winding(self):
        original=example();data=copy.deepcopy(original.data)
        for placement in data['placements']:
            ring=list(reversed(placement['absolute_points']))
            placement['absolute_points']=ring+[ring[0],ring[0]]
        layout=BridgeLayout(data)
        layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        self.assertEqual(len(layout.merged_profile(0).Faces),1)

    def test_bridge_colours_use_native_freecad_float_properties(self):
        doc=App.newDocument('NativeBridgeColours')
        obj=doc.addObject('App::FeaturePython','Style')
        for name in ['ShapeColor','LineColor']:obj.addProperty('App::PropertyColor',name)
        obj.addProperty('App::PropertyFloat','LineWidth')
        # Same native PropertyColor setter as GUI ViewObject: mixed numeric
        # types reproduce the user's error even in a headless CAD test.
        with self.assertRaises(TypeError):obj.LineColor=(.85,.35,0)
        style_component(obj,0)
        self.assertAlmostEqual(obj.LineColor[2],.15)

    def test_left_drag_pans_without_placing_endpoints(self):
        dialog=BridgeDialog(example())
        dialog.show();APPLICATION.processEvents();dialog.fit_view();APPLICATION.processEvents()
        labels=[button.text() for button in dialog.findChildren(QtGui.QPushButton)]
        self.assertNotIn('Zoom in',labels);self.assertNotIn('Zoom out',labels)
        self.assertIn('Fit all',labels)
        view=dialog.view
        start=view.mapFromScene(QtCore.QPointF(25,-15))
        target=start+QtCore.QPoint(65,30)
        before=(view.horizontalScrollBar().value(),view.verticalScrollBar().value())
        QtTest.QTest.mousePress(view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,start)
        move=QtGui.QMouseEvent(QtCore.QEvent.MouseMove,QtCore.QPointF(target),QtCore.Qt.NoButton,
                              QtCore.Qt.LeftButton,QtCore.Qt.NoModifier)
        QtGui.QApplication.sendEvent(view.viewport(),move)
        QtTest.QTest.mouseRelease(view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,target)
        APPLICATION.processEvents()
        self.assertNotEqual(before,(view.horizontalScrollBar().value(),view.verticalScrollBar().value()))
        self.assertIsNone(dialog.pending)
        self.assertEqual(dialog.layout_model.bridges,[])
        # Ordinary clicks still select exactly one edge after panning.
        point=view.mapFromScene(QtCore.QPointF(25,-15))
        QtTest.QTest.mouseClick(view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,point)
        self.assertEqual(dialog.pending['part'],0)
        dialog.close()

    def test_saved_result_and_saved_bridge_document_reopen(self):
        layout=example()
        source=App.newDocument('Nesting_Result')
        for i,part in enumerate(layout.parts):
            obj=source.addObject('Part::Feature','Original_%d'%i);obj.Shape=part['shape']
        store_result_data(source,layout.data,lambda p:'Original_%d'%p['instance_index'])
        source.recompute()
        recovered=load_result(SimpleNamespace())
        recovered.add_bridge(ref(0,25,15),ref(1,35,15),2.54)
        doc=create_document(recovered,languages.tr)
        temporary_root=Path(os.environ.get('BRIDGE_TEST_DIR',str(ROOT/'tests'))).resolve()
        temporary_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            self.assertEqual(Path(folder).resolve().parent,temporary_root)
            path=str(Path(folder)/'bridges.FCStd');doc.saveAs(path);App.closeDocument(doc.Name)
            reopened=App.openDocument(path)
            restored=load_result(SimpleNamespace())
            self.assertEqual(len(restored.bridges),1)
            self.assertAlmostEqual(restored.bridges[0]['width_mm'],2.54)
            self.assertAlmostEqual(restored.parts[0]['shape'].Volume,recovered.parts[0]['shape'].Volume)
            self.assertEqual(len(restored.merged_profile(0).Faces),1)

    def test_mouse_clicks_inch_conversion_deletion_and_zoom(self):
        dialog=BridgeDialog(example(),'inch')
        dialog.show();APPLICATION.processEvents();dialog.fit_view();APPLICATION.processEvents()
        dialog.width_spin.setValue(.1)
        self.assertAlmostEqual(dialog.width_mm,2.54)
        for x,y in [(25,15),(35,15)]:
            position=dialog.view.mapFromScene(QtCore.QPointF(x,-y))
            QtTest.QTest.mouseClick(dialog.view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,position)
            APPLICATION.processEvents()
        self.assertEqual(len(dialog.layout_model.bridges),1,dialog.status.text())
        self.assertEqual(dialog.table.rowCount(),1)
        self.assertAlmostEqual(dialog.layout_model.bridges[0]['width_mm'],2.54)
        canonical=dialog.width_mm
        for _ in range(20):dialog.set_display_units('mm');dialog.set_display_units('inch')
        self.assertEqual(dialog.width_mm,canonical)
        self.assertIn('0.1 inch',dialog.table.item(0,2).text())
        scale=dialog.view.transform().m11();dialog.view.scale(1.2,1.2)
        self.assertGreater(dialog.view.transform().m11(),scale)
        screenshot=os.environ.get('BRIDGE_SCREENSHOT')
        if screenshot:self.assertTrue(dialog.grab().save(screenshot))
        dialog.table.selectRow(0);dialog.delete_selected()
        self.assertEqual(dialog.layout_model.bridges,[])
        self.assertEqual(dialog.table.rowCount(),0)
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.close()

    def test_popup_wheel_zoom_follows_live_freecad_preferences(self):
        from Nesting1stGrainMatch import ZoomView
        from Nesting1stOffcutShowDialog import _OffcutPreview
        dialog = BridgeDialog(example())
        views = [ZoomView(), dialog.view, _OffcutPreview(outer=rectangle(0, 0, 100, 80))]
        settings = {'InvertZoom': False, 'ZoomStep': 0.2, 'ZoomAtCursor': True}
        params = SimpleNamespace(GetBool=lambda key, default: settings.get(key, default),
                                 GetFloat=lambda key, default: settings.get(key, default))
        def wheel(view, delta):
            position = QtCore.QPointF(100, 100)
            event = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, delta),
                                     QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
            APPLICATION.sendEvent(view.viewport(), event)
            return event
        try:
            for view in views:
                view.resize(700, 500)
                view.show()
            APPLICATION.processEvents()
            with patch.object(App, 'ParamGet', return_value=params) as read:
                # Reuse each view while changing settings: the popup must not cache them.
                for inverted in (False, True, False):
                    settings['InvertZoom'] = inverted
                    for step in (0.2, 0.35):
                        settings['ZoomStep'] = step
                        for at_cursor in (True, False):
                            settings['ZoomAtCursor'] = at_cursor
                            for delta in (120, -120, 60, 240):
                                expected = math.exp((1 if inverted else -1) * step * delta / 120)
                                for view in views:
                                    with self.subTest(view=type(view).__name__, inverted=inverted,
                                                      step=step, at_cursor=at_cursor, delta=delta):
                                        view.resetTransform()
                                        if hasattr(view, '_zoom'): view._zoom = 1.0
                                        self.assertTrue(wheel(view, delta).isAccepted())
                                        self.assertAlmostEqual(view.transform().m11(), expected, places=6)
                                        anchor = QtGui.QGraphicsView.AnchorUnderMouse if at_cursor else QtGui.QGraphicsView.AnchorViewCenter
                                        self.assertEqual(view.transformationAnchor(), anchor)
                for view in views:
                    before = view.transform().m11()
                    self.assertFalse(wheel(view, 0).isAccepted())
                    self.assertEqual(view.transform().m11(), before)
                self.assertTrue(read.called)
                self.assertTrue(all(call.args == ('User parameter:BaseApp/Preferences/View',)
                                    for call in read.call_args_list))
        finally:
            for view in views: view.close()
            dialog.close()

    def test_main_panel_button_and_result_import_metadata(self):
        from Nesting1stGui import NestingTaskPanel
        from Nesting1stResult import NestingResultImporter
        import Nesting1stBridges
        class Preferences:
            def GetString(self,key,default=''):return default
            def GetBool(self,key,default=False):return default
            def GetInt(self,key,default=0):return default
            def GetUnsigned(self,key,default=0):return default
            def GetFloat(self,key,default=0):return default
            def __getattr__(self,name):
                if name.startswith(('Set','Rem')):return lambda *args:None
                raise AttributeError(name)
        with patch.object(App,'ParamGet',return_value=Preferences()):
            panel=NestingTaskPanel()
            self.assertEqual(panel.bridges_btn.parent(),panel.match_grain_btn.parent())
            with patch.object(Nesting1stBridges,'open_editor') as opened:
                panel.bridges_btn.click();opened.assert_called_once_with(panel)
            with patch.object(QtGui.QMessageBox,'information') as warning:
                self.assertIsNone(Nesting1stBridges.open_editor(panel))
                warning.assert_called_once()
            layout=example();data=copy.deepcopy(layout.data)
            data['sourceParts'][0].update(shape_brep=layout.parts[0]['shape'].exportBrepToString(),
                                          normalization_offset=[0,0,0],part_id='part0',points=layout.parts[0]['outer'])
            App.newDocument('Nesting_Preview')
            importer=NestingResultImporter(panel)
            self.assertTrue(importer.import_result(data,show_summary=False))
            panel._nesting_manager.importer=importer
            self.assertIsNotNone(importer.result_doc.getObject('NestingResultData'))
            loaded=load_result(panel);self.assertEqual(len(loaded.parts),2)
            dialog=BridgeDialog(loaded,parent=panel.form)
            panel._active_bridge_dialog=dialog
            panel.units_combo.setCurrentIndex(1)
            self.assertEqual(dialog.units,'inch')
            self.assertEqual(dialog.width_mm,1)
            dialog.layout_model.add_bridge(ref(0,25,15),ref(1,35,15),2)
            dialog.refresh_table();dialog.ok_button.click()
            self.assertIsNotNone(dialog.result_document)
            self.assertEqual(dialog.result(),QtGui.QDialog.Accepted)
            panel._active_bridge_dialog=None
            panel._nesting_manager.shutdown()
            try:panel._selection_observer._unregister()
            except AttributeError:pass
            panel.form.close()

    def test_three_solid_chain_and_unconnected_part_are_separate_cam_objects(self):
        original=solid_example();data=copy.deepcopy(original.data)
        shapes={part['index']:part['shape'] for part in original.parts}
        for index,points in [(2,rectangle(65,10,20,30)),(3,rectangle(5,47,10,10))]:
            data['sourceParts'].append(dict(source_part_index=index,label='Panel %d'%index,source_type='3d'))
            data['placements'].append(dict(source_part_index=index,sheet_instance_index=0,
                                           absolute_points=points,absolute_holes=[]))
            shapes[index]=face(points).extrude(App.Vector(0,0,6))
        data['sheets'][0].update(width=110,height=75)
        layout=BridgeLayout(data,shapes)
        layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        layout.add_bridge(ref(1,55,15),ref(2,65,15),2)
        before=[part['shape'].Volume for part in layout.parts]
        doc=create_document(layout,languages.tr)
        objects=[obj for obj in doc.Objects if hasattr(obj,'SourcePartIndices')]
        self.assertEqual(len(objects),2)
        self.assertEqual(doc.JoinedParts_1.SourcePartIndices,[0,1,2])
        self.assertEqual(doc.JoinedParts_1.BridgeIds,[1,2])
        self.assertEqual(len(doc.JoinedParts_1.Shape.Solids),1)
        self.assertAlmostEqual(doc.JoinedParts_1.Shape.Volume,10890)
        self.assertAlmostEqual(doc.Part_4.Shape.Volume,600)
        self.assertEqual([part['shape'].Volume for part in layout.parts],before)
        self.assertFalse(any(obj.Name.startswith(('Bridge_','CutContours_')) for obj in doc.Objects))

    def test_boolean_preserves_through_hole_and_blind_pocket(self):
        layout=solid_example()
        pocket=Part.makeBox(4,4,3,App.Vector(43,23,3))
        layout.parts[1]['shape']=layout.parts[1]['shape'].cut(pocket)
        original=[part['shape'].Volume for part in layout.parts]
        layout.add_bridge(ref(0,25,15),ref(1,35,15),3)
        doc=create_document(layout,languages.tr)
        fused=doc.JoinedParts_1.Shape
        self.assertTrue(fused.isValid());self.assertEqual(len(fused.Solids),1)
        self.assertAlmostEqual(fused.Volume,sum(original)+180)
        self.assertAlmostEqual(fused.common(pocket).Volume,0)
        hole=face(rectangle(10,20,5,5)).extrude(App.Vector(0,0,6))
        self.assertAlmostEqual(fused.common(hole).Volume,0)
        restored=load_result(SimpleNamespace())
        self.assertEqual([round(p['shape'].Volume,6) for p in restored.parts],[round(v,6) for v in original])

    def test_incompatible_heights_reject_before_creating_document(self):
        layout=solid_example();layout.parts[1]['shape'].translate(App.Vector(0,0,8))
        layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        keep=App.newDocument('KeepNestingResult')
        before=set(App.listDocuments())
        with self.assertRaises(BridgeError) as caught:create_document(layout,languages.tr)
        self.assertEqual(caught.exception.key,'join_failed')
        self.assertEqual(set(App.listDocuments()),before)
        self.assertEqual(len(layout.bridges),1)

    def test_different_thicknesses_use_common_height_for_bridge_solid(self):
        layout=solid_example()
        shape=layout.parts[1]['face'].extrude(App.Vector(0,0,8));shape.translate(App.Vector(0,0,2))
        layout.parts[1]['shape']=shape
        layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        doc=create_document(layout,languages.tr)
        self.assertEqual(len(doc.JoinedParts_1.Shape.Solids),1)
        self.assertAlmostEqual(doc.JoinedParts_1.Shape.Volume,8330)

    def test_crossing_bridge_networks_make_one_cam_solid(self):
        contours=[rectangle(5,25,10,10),rectangle(75,25,10,10),rectangle(40,5,10,10),rectangle(40,50,10,10)]
        data=dict(sheets=[dict(width=100,height=80)],
                  sourceParts=[dict(source_part_index=i,label='Panel %d'%i,source_type='3d') for i in range(4)],
                  placements=[dict(source_part_index=i,sheet_instance_index=0,absolute_points=p,absolute_holes=[]) for i,p in enumerate(contours)])
        layout=BridgeLayout(data,{i:face(p).extrude(App.Vector(0,0,6)) for i,p in enumerate(contours)})
        layout.add_bridge(ref(0,15,30),ref(1,75,30),4)
        layout.add_bridge(ref(2,45,15),ref(3,45,50),4)
        doc=create_document(layout,languages.tr)
        self.assertEqual(len([o for o in doc.Objects if hasattr(o,'SourcePartIndices')]),1)
        self.assertEqual(len(doc.JoinedParts_1.Shape.Solids),1)
        self.assertAlmostEqual(doc.JoinedParts_1.Shape.Volume,4584)

    def test_cam_step_and_planar_brep_roundtrip_have_single_geometry(self):
        temporary_root=Path(os.environ.get('BRIDGE_TEST_DIR',str(ROOT/'tests'))).resolve()
        temporary_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            self.assertEqual(Path(folder).resolve().parent,temporary_root)
            layout=solid_example();layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
            doc=create_document(layout,languages.tr)
            path=str(Path(folder)/'joined.step');Part.export([doc.JoinedParts_1],path)
            exported=Part.read(path)
            self.assertTrue(exported.isValid());self.assertEqual(len(exported.Solids),1)
            self.assertAlmostEqual(exported.Volume,7170)
            layout=example()
            for part in layout.parts:part['shape']=Part.makeCompound(part['face'].Wires)
            layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
            doc=create_document(layout,languages.tr)
            path=str(Path(folder)/'joined.brep');doc.JoinedParts_1.Shape.exportBrep(path)
            exported=Part.read(path)
            self.assertEqual(len(exported.Faces),1);self.assertEqual(len(exported.Wires),2)
            self.assertAlmostEqual(exported.Area,1195)

    def test_legacy_overlay_document_converts_and_deleting_all_bridges_restores_sources(self):
        layout=solid_example();layout.add_bridge(ref(0,25,15),ref(1,35,15),2)
        data=copy.deepcopy(layout.data)
        for i,p in enumerate(data['placements']):p['_bridge_object_name']='Part_%d'%(i+1)
        old=App.newDocument('Nesting_Bridges_Legacy')
        meta=old.addObject('App::FeaturePython','NestingBridgeData')
        meta.addProperty('App::PropertyString','ResultJson');meta.ResultJson=json.dumps(data)
        meta.addProperty('App::PropertyString','BridgesJson');meta.BridgesJson=json.dumps(dict(version=1,units='mm',bridges=layout.serialized_bridges()))
        for i,part in enumerate(layout.parts):
            obj=old.addObject('Part::Feature','Part_%d'%(i+1));obj.Shape=part['shape']
        overlay=old.addObject('Part::Feature','Bridge_1');overlay.Shape=layout.bridges[0]['face']
        restored=load_result(SimpleNamespace());doc=create_document(restored,languages.tr)
        self.assertEqual(json.loads(doc.NestingBridgeData.BridgesJson)['version'],2)
        self.assertIsNone(doc.getObject('Bridge_1'))
        dialog=BridgeDialog(load_result(SimpleNamespace()))
        dialog.table.selectRow(0);dialog.delete_selected()
        self.assertTrue(dialog.ok_button.isEnabled())
        dialog.ok_button.click()
        separated=dialog.result_document
        self.assertIsNotNone(separated);self.assertEqual(dialog.result(),QtGui.QDialog.Accepted)
        self.assertIsNone(separated.getObject('JoinedParts_1'))
        self.assertAlmostEqual(separated.Part_1.Shape.Volume,3450)
        self.assertAlmostEqual(separated.Part_2.Shape.Volume,3600)
        dialog.close()


if __name__=='__main__':unittest.main(verbosity=2)
