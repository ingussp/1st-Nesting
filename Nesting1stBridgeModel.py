"""Millimetre bridge geometry on a frozen, normalized nesting result."""
import copy
import json
import math
import FreeCAD as App
import Part
from Nesting1stResultSVG import _ring, _transform

MM_PER_INCH = 25.4
TOLERANCE = 1e-6


class BridgeError(ValueError):
    def __init__(self, key):
        self.key = key
        super().__init__(key)


def to_mm(value, units):
    return float(value) * (MM_PER_INCH if units == 'inch' else 1.0)


def from_mm(value, units):
    return float(value) / (MM_PER_INCH if units == 'inch' else 1.0)


def wire(points):
    cleaned = []
    for point in points:
        if not cleaned or list(point) != cleaned[-1]:
            cleaned.append(list(point))
    if len(cleaned) > 1 and cleaned[-1] == cleaned[0]:
        cleaned.pop()
    if len(cleaned) < 3:
        raise BridgeError('geometry')
    points = cleaned
    # OCC planar fusions need matching face normals, irrespective of the
    # clockwise/counter-clockwise winding supplied by SVG, DXF or the engine.
    if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points, points[1:]+points[:1])) < 0:
        points = list(reversed(points))
    vectors = [App.Vector(x, y, 0) for x, y in points]
    return Part.makePolygon(vectors + [vectors[0]])


def face(outer, holes=()):
    shape = Part.Face(wire(outer))
    for hole in holes:
        shape = shape.cut(Part.Face(wire(hole)))
    if shape.isNull() or not shape.isValid() or shape.Area <= TOLERANCE:
        raise BridgeError('geometry')
    return shape.Faces[0] if len(shape.Faces) == 1 else shape


def joined_faces(shapes):
    result = shapes[0].multiFuse(shapes[1:]) if len(shapes) > 1 else shapes[0]
    # Planar Boolean fusions can return a compound of subdivided faces.
    # Sewing their shared edges into a shell lets OCC remove all internal cuts.
    return Part.makeShell(result.Faces).removeSplitter()


def nearest_on_ring(point, ring):
    best = None
    px, py = point
    for a, b in zip(ring, ring[1:] + ring[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        if length2 <= TOLERANCE * TOLERANCE:
            continue
        t = max(0.0, min(1.0, ((px-a[0])*dx + (py-a[1])*dy)/length2))
        snap = [a[0] + t*dx, a[1] + t*dy]
        distance = math.hypot(px-snap[0], py-snap[1])
        if best is None or distance < best[0]:
            best = (distance, snap)
    return best


class BridgeLayout:
    def __init__(self, data, source_shapes=None):
        self.data = copy.deepcopy(data)
        self.parts = []
        self.sheets = []
        self.bridges = []
        self.next_id = 1
        sources = {str(p['source_part_index']): p for p in self.data.get('sourceParts', [])}
        for index, sheet in enumerate(self.data.get('sheets', [])):
            outer = sheet.get('outer') or sheet.get('points')
            if not outer:
                w, h = float(sheet.get('width', 0)), float(sheet.get('height', 0))
                outer = [[0, 0], [w, 0], [w, h], [0, h]]
            outer = _ring(outer)
            holes = [_ring(h) for h in sheet.get('holes', []) or []]
            self.sheets.append(dict(index=int(sheet.get('sheet_instance_index', index)),
                                    outer=outer, holes=holes, face=face(outer, holes)))
        for placement in self.data.get('placements', []):
            if not placement.get('placed', True):
                continue
            source = sources.get(str(placement.get('source_part_index')), {})
            outer = _ring(placement['absolute_points']) if placement.get('absolute_points') else \
                _transform(source.get('points', placement.get('points', [])), placement)
            holes = [_ring(h) for h in placement['absolute_holes']] if 'absolute_holes' in placement else \
                [_transform(h, placement) for h in source.get('holes', [])]
            index = len(self.parts)
            self.parts.append(dict(index=index, sheet=int(placement.get('sheet_instance_index', 0)),
                                   label=source.get('label') or str(placement.get('id', index+1)),
                                   outer=outer, holes=holes, face=face(outer, holes),
                                   source_type=source.get('source_type', '2d'),
                                   shape=(source_shapes or {}).get(index), placement=placement))
        if not self.sheets or not self.parts:
            raise BridgeError('no_result')
        sheet_ids = {s['index'] for s in self.sheets}
        if any(p['sheet'] not in sheet_ids for p in self.parts):
            raise BridgeError('geometry')

    def nearest_edge(self, sheet, point, tolerance):
        best = None
        for part in self.parts:
            if part['sheet'] != sheet:
                continue
            candidate = nearest_on_ring(point, part['outer'])
            if candidate and candidate[0] <= tolerance and (best is None or candidate[0] < best[0]):
                best = (candidate[0], dict(part=part['index'], point=candidate[1]))
        return best[1] if best else None

    def make_bridge(self, first, second, width_mm):
        width = float(width_mm)
        if not math.isfinite(width) or width <= 0:
            raise BridgeError('width_invalid')
        a, b = self.parts[first['part']], self.parts[second['part']]
        if a['index'] == b['index']:
            raise BridgeError('different_parts')
        if a['sheet'] != b['sheet']:
            raise BridgeError('same_sheet')
        p, q = [list(map(float, ref['point'])) for ref in (first, second)]
        if any(not math.isfinite(v) for point in (p, q) for v in point):
            raise BridgeError('geometry')
        for part, point in ((a, p), (b, q)):
            if nearest_on_ring(point, part['outer'])[0] > TOLERANCE:
                raise BridgeError('edge_required')
        length = math.hypot(q[0]-p[0], q[1]-p[1])
        if length <= TOLERANCE:
            raise BridgeError('too_short')
        ux, uy = (q[0]-p[0])/length, (q[1]-p[1])/length
        nx, ny = -uy*width/2, ux*width/2
        # A small overlap creates actual joined material, rather than two
        # faces that merely touch. Canonical click coordinates remain intact.
        extension = max(.001, min(width/4, length/4))
        start, end = [p[0]-ux*extension, p[1]-uy*extension], [q[0]+ux*extension, q[1]+uy*extension]
        outer = [[start[0]+nx, start[1]+ny], [end[0]+nx, end[1]+ny],
                 [end[0]-nx, end[1]-ny], [start[0]-nx, start[1]-ny]]
        strip = face(outer)
        sheet = next(s for s in self.sheets if s['index'] == a['sheet'])
        if strip.cut(sheet['face']).Area > TOLERANCE:
            raise BridgeError('outside_sheet')
        # Endpoint parts are obstacles too, except at their local attachment.
        for part in self.parts:
            if part['sheet'] != a['sheet']:
                continue
            first_box, second_box = strip.BoundBox, part['face'].BoundBox
            if (first_box.XMax < second_box.XMin-TOLERANCE or second_box.XMax < first_box.XMin-TOLERANCE or
                    first_box.YMax < second_box.YMin-TOLERANCE or second_box.YMax < first_box.YMin-TOLERANCE):
                continue
            common = strip.common(part['face'])
            if part['index'] in (a['index'], b['index']):
                point = p if part['index'] == a['index'] else q
                cap = Part.Face(Part.Wire([Part.makeCircle(width+extension+.001,
                                                        App.Vector(*point, 0))]))
                if common.Area <= TOLERANCE or common.cut(cap).Area > TOLERANCE:
                    raise BridgeError('attachment')
                for hole in part['holes']:
                    if strip.common(face(hole)).Area > TOLERANCE:
                        raise BridgeError('hole_collision')
            elif common.Area > TOLERANCE or strip.distToShape(part['face'])[0] <= TOLERANCE:
                raise BridgeError('collision')
        joined = joined_faces([a['face'], strip, b['face']])
        if not joined.isValid() or len(joined.Faces) != 1:
            raise BridgeError('attachment')
        for old in self.bridges:
            pair = {old['first']['part'], old['second']['part']}
            if pair == {a['index'], b['index']}:
                old_points = [old['first']['point'], old['second']['point']]
                if all(min(math.dist(point, other) for other in old_points) < TOLERANCE for point in (p, q)):
                    raise BridgeError('duplicate')
        return dict(id=self.next_id, sheet=a['sheet'], first=dict(part=a['index'], point=p),
                    second=dict(part=b['index'], point=q), width_mm=width, length_mm=length,
                    outer=outer, face=strip)

    def add_bridge(self, first, second, width_mm):
        bridge = self.make_bridge(first, second, width_mm)
        self.next_id += 1
        self.bridges.append(bridge)
        return bridge

    def remove_bridges(self, identifiers):
        self.bridges[:] = [bridge for bridge in self.bridges if bridge['id'] not in identifiers]

    def merged_profile(self, sheet):
        parts = [part['face'] for part in self.parts if part['sheet'] == sheet]
        shapes = parts + [bridge['face'] for bridge in self.bridges if bridge['sheet'] == sheet]
        if not shapes:
            return None
        merged = joined_faces(shapes)
        if not merged.isValid():
            raise BridgeError('geometry')
        return merged

    def serialized_bridges(self):
        return [{key: value for key, value in bridge.items() if key != 'face'} for bridge in self.bridges]

    def connected_groups(self):
        """Each physically connected bridge network becomes one CAM object."""
        parents = list(range(len(self.parts)))
        def find(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index
        def union(first, second):
            parents[find(second)] = find(first)
        for bridge in self.bridges:
            union(bridge['first']['part'], bridge['second']['part'])
        # Crossing/edge-sharing bridge strips also join material, even if
        # the user did not attach both bridges to a common part.
        for index, first in enumerate(self.bridges):
            for second in self.bridges[index+1:]:
                if first['sheet'] != second['sheet']:
                    continue
                if not first['face'].BoundBox.intersect(second['face'].BoundBox):
                    continue
                common = first['face'].common(second['face'])
                if common.Area > TOLERANCE or common.Length > TOLERANCE:
                    union(first['first']['part'], second['first']['part'])
        groups = {}
        for part in self.parts:
            group = groups.setdefault(find(part['index']), dict(sheet=part['sheet'], parts=[], bridges=[]))
            group['parts'].append(part)
        for bridge in self.bridges:
            groups[find(bridge['first']['part'])]['bridges'].append(bridge)
        return sorted(groups.values(), key=lambda group: group['parts'][0]['index'])

    def fused_group(self, group):
        """Return one real solid or one planar face, without reference edges."""
        parts, bridges = group['parts'], group['bridges']
        if not bridges:
            original = parts[0]['shape']
            return original.copy() if original is not None else parts[0]['face'].copy()
        solids = all(part['shape'] is not None and part['shape'].Solids for part in parts)
        if not solids:
            profile = joined_faces([part['face'] for part in parts] + [bridge['face'] for bridge in bridges])
            if not profile.isValid() or len(profile.Faces) != 1:
                raise BridgeError('geometry')
            # A single face carries the outer wire and all inner hole wires.
            # Mixed 2D/3D networks use the same planar cutting profile.
            return profile.Faces[0]
        shapes = [part['shape'].copy() for part in parts]
        for bridge in bridges:
            adjacent = [self.parts[bridge[key]['part']]['shape'] for key in ('first', 'second')]
            bottom = max(shape.BoundBox.ZMin for shape in adjacent)
            top = min(shape.BoundBox.ZMax for shape in adjacent)
            if top-bottom <= TOLERANCE:
                raise BridgeError('join_failed')
            connector = bridge['face'].extrude(App.Vector(0, 0, top-bottom))
            connector.translate(App.Vector(0, 0, bottom))
            shapes.append(connector)
        try:
            result = shapes[0].multiFuse(shapes[1:]).removeSplitter()
        except Exception as exc:
            raise BridgeError('join_failed') from exc
        if not result.isValid() or len(result.Solids) != 1:
            raise BridgeError('join_failed')
        return result.Solids[0]


def store_result_data(document, data, object_name):
    """Persist millimetre contours so a saved result can reopen the editor."""
    snapshot = copy.deepcopy(data)
    for source in snapshot.get('sourceParts', []):
        source.pop('shape_brep', None)
    for placement in snapshot.get('placements', []):
        placement['_bridge_object_name'] = object_name(placement)
    meta = document.addObject('App::FeaturePython', 'NestingResultData')
    meta.addProperty('App::PropertyString', 'ResultJson', '1st Nesting')
    meta.ResultJson = json.dumps(snapshot)
    if App.GuiUp:
        meta.ViewObject.Visibility = False


def load_result(panel):
    manager = getattr(panel, '_nesting_manager', None)
    importer = getattr(manager, 'importer', None)
    active = App.ActiveDocument
    document = active if active is not None and (active.getObject('NestingBridgeData') or active.getObject('NestingResultData')) else getattr(importer, 'result_doc', None)
    try:
        if document is not None and document.Name not in App.listDocuments():
            document = None
    except RuntimeError:
        document = None
    if document is None:
        document = App.ActiveDocument
        if document is None or document.getObject('NestingResultData') is None:
            document = next((doc for doc in App.listDocuments().values()
                             if doc.Name.startswith('Nesting_Result') and doc.getObject('NestingResultData')), None)
    if document is None:
        raise BridgeError('no_result')
    bridge_metadata = document.getObject('NestingBridgeData')
    metadata = bridge_metadata or document.getObject('NestingResultData')
    data = json.loads(metadata.ResultJson) if metadata else copy.deepcopy(importer.result_data)
    shapes = {}
    source_breps = json.loads(bridge_metadata.SourceShapesJson) if bridge_metadata and \
        'SourceShapesJson' in bridge_metadata.PropertiesList else None
    index = 0
    for placement in data.get('placements', []):
        if not placement.get('placed', True):
            continue
        if source_breps is not None:
            shape = Part.Shape()
            shape.importBrepFromString(source_breps[str(index)])
            if shape.isNull() or not shape.isValid():
                raise BridgeError('geometry')
            shapes[index] = shape
        else:
            # Compatibility with the original overlapping-bridge documents.
            name = placement.get('_bridge_object_name') or importer._result_object_name(placement)
            obj = document.getObject(name)
            if obj is None or not hasattr(obj, 'Shape') or obj.Shape.isNull():
                raise BridgeError('no_result')
            shapes[index] = obj.Shape.copy()
        index += 1
    layout = BridgeLayout(data, shapes)
    if bridge_metadata:
        saved = json.loads(bridge_metadata.BridgesJson)
        if saved.get('units') != 'mm':
            raise BridgeError('geometry')
        for old in saved.get('bridges', []):
            bridge = layout.add_bridge(old['first'], old['second'], old['width_mm'])
            bridge['id'] = int(old['id'])
        layout.next_id = max((b['id'] for b in layout.bridges), default=0)+1
    return layout


def style_component(view, index):
    """FreeCAD colour tuples require float components, including zero."""
    from Nesting1stResultSVG import _colour
    colour = _colour(index)
    rgb = tuple(float(int(colour[i:i+2], 16))/255.0 for i in (1, 3, 5))
    view.ShapeColor = rgb
    view.LineColor = (0.15, 0.15, 0.15)
    view.LineWidth = 2.0


def create_document(layout, translate):
    """Create only fused CAM geometry; keep editable sources in metadata."""
    import FreeCADGui as Gui
    # Complete every Boolean operation before touching the user's documents.
    components = [(group, layout.fused_group(group)) for group in layout.connected_groups()]
    document = App.newDocument('Nesting_Bridges')
    try:
        metadata = document.addObject('App::FeaturePython', 'NestingBridgeData')
        metadata.addProperty('App::PropertyString', 'BridgesJson', '1st Nesting')
        metadata.addProperty('App::PropertyString', 'ResultJson', '1st Nesting')
        metadata.addProperty('App::PropertyString', 'SourceShapesJson', '1st Nesting')
        metadata.BridgesJson = json.dumps(dict(version=2, units='mm', bridges=layout.serialized_bridges()))
        metadata.ResultJson = json.dumps(layout.data)
        metadata.SourceShapesJson = json.dumps({str(part['index']):
            (part['shape'] if part['shape'] is not None else part['face']).exportBrepToString()
            for part in layout.parts})
        offset = 0.0
        for sheet in layout.sheets:
            sheet_id = sheet['index']
            group = document.addObject('App::Part', 'SheetGroup_%d' % sheet_id)
            group.Label = str(translate('sheet_d')) % (sheet_id+1)
            group.Placement.Base = App.Vector(offset, 0, 0)
            offset += sheet['face'].BoundBox.XLength + 50
            border = document.addObject('Part::Feature', 'Sheet_%d' % sheet_id)
            border.Shape = Part.makeCompound(sheet['face'].Wires)
            group.addObject(border)
            for component, shape in components:
                if component['sheet'] != sheet_id:
                    continue
                first = component['parts'][0]
                joined = bool(component['bridges'])
                name = ('JoinedParts_%d' if joined else 'Part_%d') % (first['index']+1)
                obj = document.addObject('Part::Feature', name)
                obj.Label = ('%s %d · %s' % (translate('bridge.joined_parts'), first['index']+1,
                    ' + '.join(part['label'] for part in component['parts']))) if joined else first['label']
                obj.Shape = shape
                obj.addProperty('App::PropertyIntegerList', 'SourcePartIndices', '1st Nesting')
                obj.SourcePartIndices = [part['index'] for part in component['parts']]
                obj.addProperty('App::PropertyStringList', 'SourceLabels', '1st Nesting')
                obj.SourceLabels = [part['label'] for part in component['parts']]
                obj.addProperty('App::PropertyIntegerList', 'BridgeIds', '1st Nesting')
                obj.BridgeIds = [bridge['id'] for bridge in component['bridges']]
                group.addObject(obj)
                if App.GuiUp:
                    style_component(obj.ViewObject, first['index'])
        document.recompute()
        if App.GuiUp:
            metadata.ViewObject.Visibility = False
            App.setActiveDocument(document.Name)
            Gui.activeDocument().activeView().viewTop()
            Gui.activeDocument().activeView().fitAll()
        return document
    except Exception:
        App.closeDocument(document.Name)
        raise
