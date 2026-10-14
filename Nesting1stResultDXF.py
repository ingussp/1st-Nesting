"""Export placed CAD geometry as top-view DXF, retaining analytic curves."""
import json
import os
from pathlib import Path
import re
import tempfile

import FreeCAD as App
import Part


def _live_document(document):
    try:
        return document is not None and App.listDocuments().get(document.Name) is document
    except RuntimeError:
        return False


def result_document(panel):
    """Prefer the active saved/bridged result, then this panel's live result."""
    active = App.ActiveDocument
    if active is not None and (active.getObject('NestingBridgeData') or active.getObject('NestingResultData')):
        return active
    importer = getattr(getattr(panel, '_nesting_manager', None), 'importer', None)
    document = getattr(importer, 'result_doc', None)
    if _live_document(document):
        return document
    return None


def _part_name(placement):
    name = placement.get('_bridge_object_name')
    if name:
        return name
    if placement.get('id'):
        return 'Nesting_' + str(placement['id']).replace(' ', '_')
    return 'Nesting_part_%d_instance_%d' % (int(placement.get('source_part_index', 0)),
                                           int(placement.get('instance_index', 0)))


def result_parts(document, data=None):
    """Return placed parts only; exclude stock, labels and unplaced geometry."""
    bridge_data = document.getObject('NestingBridgeData')
    result_data = document.getObject('NestingResultData')
    if bridge_data or result_data:
        data = json.loads((bridge_data or result_data).ResultJson)
    if not isinstance(data, dict):
        raise ValueError('The document has no saved nesting result.')
    placements = [p for p in data.get('placements', []) if p.get('placed', True)]
    if bridge_data:
        parts = []
        for obj in document.Objects:
            if 'SourcePartIndices' not in obj.PropertiesList:
                continue
            indices = list(obj.SourcePartIndices)
            if not indices or any(i < 0 or i >= len(placements) for i in indices):
                raise ValueError('Invalid bridged result part references.')
            sheet = int(placements[indices[0]].get('sheet_instance_index', 0))
            parts.append((sheet, obj))
        # Version 1 prototype documents still contain the original Part_i.
        if not parts:
            parts = [(int(p.get('sheet_instance_index', 0)), document.getObject(_part_name(p)))
                     for p in placements]
            if json.loads(bridge_data.BridgesJson).get('bridges'):
                raise ValueError('Reopen Create bridges and click OK to convert this older bridge result before DXF export.')
    else:
        parts = [(int(p.get('sheet_instance_index', 0)), document.getObject(_part_name(p)))
                 for p in placements]
    if not parts:
        raise ValueError('The result contains no placed parts.')
    if any(obj is None or not hasattr(obj, 'Shape') or obj.Shape.isNull() for _, obj in parts):
        raise ValueError('A placed part is missing its CAD geometry.')
    return parts


def top_view_shape(obj):
    """Project real BREP, not sampled engine polygons or bounding boxes."""
    shape = obj.Shape.copy()
    # Shape includes its own placement; replace it with the global placement
    # to include parent sheet offsets exactly once, including saved results.
    shape.Placement = obj.getGlobalPlacement()
    if not shape.isValid():
        raise ValueError('Invalid CAD geometry: ' + obj.Label)
    if shape.BoundBox.ZLength < 1e-7:
        shape.translate(App.Vector(0, 0, -shape.BoundBox.ZMin))
        edges = shape.Edges
    else:
        import TechDraw
        # Same analytic projection used by FreeCAD's Shape2DView and DXF
        # exporter. Groups 0..4 are visible edges, outlines and smooth edges;
        # hidden back-side edges are not duplicate cutting paths.
        groups = TechDraw.projectEx(shape, App.Vector(0, 0, 1))
        edges = [edge for group in groups[:5] if not group.isNull() for edge in group.Edges]
    unique = []
    buckets = {}
    for edge in edges:
        if edge.Length < 1e-7:
            continue
        curve = edge.Curve
        if isinstance(curve, Part.BezierCurve):
            spline = curve.toBSpline()
            spline.segment(edge.FirstParameter, edge.LastParameter)
            edge = spline.toShape()
            curve = edge.Curve
        # SVG circular arcs are often imported as equal-radius ellipses.
        # Emit them as actual DXF ARC/CIRCLE entities for CAM compatibility.
        if isinstance(curve, Part.Ellipse) and abs(curve.MajorRadius - curve.MinorRadius) <= 1e-9:
            if edge.isClosed():
                edge = Part.makeCircle(curve.MajorRadius, curve.Center, curve.Axis)
            else:
                start, end = edge.FirstParameter, edge.LastParameter
                edge = Part.Arc(edge.valueAt(start), edge.valueAt((start + end) / 2), edge.valueAt(end)).toShape()
        if edge.BoundBox.ZLength > 1e-7 or abs(edge.BoundBox.ZMin) > 1e-7:
            raise ValueError('CAD projection is not planar: ' + obj.Label)
        box = edge.BoundBox
        key = tuple(round(value, 6) for value in (box.XMin, box.YMin, box.XMax, box.YMax, edge.Length))
        peers = buckets.setdefault(key, [])
        if any(abs(edge.common(old).Length - edge.Length) < 1e-7 for old in peers):
            continue
        peers.append(edge)
        unique.append(edge)
    if not unique:
        raise ValueError('The part has no projected contours: ' + obj.Label)
    return Part.makeCompound(unique)


def _exact_splines(content, objects):
    """Retain rational NURBS weights that the native writer approximates.

    Keep FreeCAD's DXF header, layers, handles and analytic entities; replace
    only its SPLINE geometry with the actual placed BREP's control data.
    """
    splines = {}
    for obj in objects:
        curves = []
        for edge in obj.Shape.Edges:
            if isinstance(edge.Curve, Part.BSplineCurve):
                curve = edge.Curve.copy()
                curve.segment(edge.FirstParameter, edge.LastParameter)
                curves.append((curve, edge.isClosed()))
        if curves:
            splines[obj.Name] = curves
    lines = content.splitlines()
    if len(lines) % 2:
        raise ValueError('Invalid DXF group data.')
    pairs = [(int(lines[i].strip()), lines[i + 1]) for i in range(0, len(lines), 2)]
    output = []
    index = 0
    while index < len(pairs):
        code, value = pairs[index]
        if code != 0 or value.strip() != b'SPLINE':
            output.append((code, value)); index += 1; continue
        end = index + 1
        while end < len(pairs) and pairs[end][0] != 0:
            end += 1
        record = pairs[index:end]
        layer = next(value.strip().decode('ascii') for code, value in record if code == 8)
        if not splines.get(layer):
            raise ValueError('Cannot match an exported spline to its CAD geometry.')
        curve, closed = splines[layer].pop(0)
        subclass = next(i for i, (code, value) in enumerate(record)
                        if code == 100 and value.strip() == b'AcDbSpline')
        output.extend(record[:subclass + 1])
        def add(code, value):
            output.append((code, (format(value, '.17g') if isinstance(value, float) else str(value)).encode('ascii')))
        poles = curve.getPoles()
        knots = [knot for knot, count in zip(curve.getKnots(), curve.getMultiplicities()) for _ in range(count)]
        rational = curve.isRational()
        flags = 8 | int(closed) | (2 if curve.isPeriodic() else 0) | (4 if rational else 0)
        for code, value in [(210, 0), (220, 0), (230, 1), (70, flags), (71, curve.Degree),
                            (72, len(knots)), (73, len(poles)), (74, 0)]:
            add(code, value)
        for knot in knots:
            add(40, knot)
        if rational:
            for weight in curve.getWeights():
                add(41, weight)
        for pole in poles:
            for code, value in [(10, pole.x), (20, pole.y), (30, pole.z)]:
                add(code, value)
        index = end
    if any(curves for curves in splines.values()):
        raise ValueError('A CAD spline is missing from the exported DXF.')
    return b''.join(str(code).encode('ascii') + b'\n' + value + b'\n' for code, value in output)


def export_document(document, filename, data=None):
    """Write one millimetre DXF atomically, without changing result geometry."""
    import Import
    # Finish all projections before creating temporary objects or files.
    projected = [(sheet, obj.Name, obj.Label, top_view_shape(obj))
                 for sheet, obj in result_parts(document, data)]
    path = Path(filename)
    if path.suffix.lower() != '.dxf':
        path = Path(str(path) + '.dxf')
    active_name = App.ActiveDocument.Name if App.ActiveDocument else None
    temp_document = None
    temp_path = None
    try:
        temp_document = App.newDocument('Nesting_DXF_Export', hidden=True, temp=True)
        objects = []
        for sheet, name, label, shape in projected:
            # The native exporter uses object names as layers, so each part
            # and sheet stays identifiable without exporting a stock border.
            obj = temp_document.addObject('Part::Feature', 'Sheet_%d_%s' % (sheet + 1, name))
            obj.Label = label
            obj.Shape = shape
            objects.append(obj)
        temp_document.recompute()
        descriptor, temporary = tempfile.mkstemp(prefix='.nesting-dxf-', suffix='.dxf', dir=str(path.parent))
        os.close(descriptor)
        temp_path = Path(temporary)
        # Use the bundled native writer directly, independent of the user's
        # legacy DXF exporter, tessellation and camera-view settings.
        Import.writeDXFObject(objects, str(temp_path), 14, False)
        content = temp_path.read_bytes()
        if b'ENTITIES' not in content or not content.rstrip().endswith(b'EOF'):
            raise ValueError('FreeCAD did not produce a complete DXF file.')
        content = _exact_splines(content, objects)
        # All CAD coordinates are millimetres, even with inch UI units.
        content, count = re.subn(rb'(\$INSUNITS\s+70\s+)\d+', rb'\g<1>4', content, count=1)
        if count != 1:
            raise ValueError('DXF output has no unit declaration.')
        temp_path.write_bytes(content)
        os.replace(str(temp_path), str(path))
        return path
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        if temp_document is not None:
            App.closeDocument(temp_document.Name)
        if active_name and active_name in App.listDocuments():
            App.setActiveDocument(active_name)


def export_from_panel(panel):
    from PySide import QtGui
    from Nesting1stLanguages import tr
    document = result_document(panel)
    if document is None:
        QtGui.QMessageBox.information(panel.form, tr('dxf.export'), tr('no_nesting_result_to_export'))
        return False
    filename, _ = QtGui.QFileDialog.getSaveFileName(panel.form, tr('dxf.export'),
                                                   document.Name + '.dxf', tr('dxf_files_dxf_dxf_all_files'))
    if not filename:
        return False
    try:
        importer = getattr(getattr(panel, '_nesting_manager', None), 'importer', None)
        data = getattr(importer, 'result_data', None) if getattr(importer, 'result_doc', None) is document else None
        export_document(document, filename, data)
        return True
    except Exception as exc:
        QtGui.QMessageBox.critical(panel.form, tr('dxf.export'), tr('dxf.failed') + '\n' + str(exc))
        return False
