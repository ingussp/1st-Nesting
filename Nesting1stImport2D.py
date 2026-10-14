"""
Nesting1stImport2D - DXF/SVG import to Nesting_Preview and conversion to stable Part::Feature.

Goal:
- Import 2D geometry (DXF/SVG) into the preview document.
- Collect imported objects' Shapes and convert them into one or more Part::Feature objects
  with a stable OCC Shape (Compound of edges/wires, optionally Faces when possible).
- Return created preview object names so the panel can add them into the table and rotate them like others.

Notes:
- FreeCAD import module names may vary between installs. We try multiple fallbacks.
- We don't require Faces for nesting; BoundBox + Placement must work.
"""
from Nesting1stLanguages import tr

import os
import tempfile
import traceback
import xml.etree.ElementTree as ET

import FreeCAD as App

try:
    import Part
except Exception:
    Part = None


# Get or create preview doc using existing panel machinery if available.
def _ensure_preview_doc(panel):
    """Get or create preview doc using existing panel machinery if available."""
    try:
        if hasattr(panel, "ensure_preview_doc"):
            return panel.ensure_preview_doc()
    except Exception:
        pass

    # fallback
    if panel.preview_doc_name not in App.listDocuments():
        App.newDocument(panel.preview_doc_name)
    return App.getDocument(panel.preview_doc_name)


# Import DXF into doc_name.
def _import_dxf(path, doc_name):
    """Import DXF into doc_name."""
    # Common importer module for DXF in FreeCAD
    try:
        import importDXF
        importDXF.insert(path, doc_name)
        return True
    except Exception:
        pass

    # Fallback: sometimes ImportGui handles formats, depending on install
    try:
        import ImportGui
        ImportGui.insert(path, doc_name)
        return True
    except Exception:
        pass

    return False


# Import SVG into doc_name.
def _import_svg(path, doc_name):
    """Import SVG into doc_name."""
    # Filled paths trigger different automatic cuts in FreeCAD 1.0 and 1.1.
    # Import unchanged vector boundaries as wires, then determine part/hole
    # topology ourselves. Preserve transforms, units, namespaces and styles.
    for _, (prefix, uri) in ET.iterparse(path, events=('start-ns',)):
        if prefix != 'xml' and not (prefix.startswith('ns') and prefix[2:].isdigit()):
            ET.register_namespace(prefix, uri)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    tree = ET.parse(path)
    for element in tree.iter():
        if element.tag.rsplit('}', 1)[-1] in ('path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline'):
            element.set('fill', 'none')
            element.set('style', element.get('style', '').rstrip(';') + ';fill:none')
    with tempfile.TemporaryDirectory(prefix='1stnesting-svg-') as directory:
        vector_path = os.path.join(directory, os.path.basename(path))
        tree.write(vector_path, encoding='utf-8', xml_declaration=True)
        try:
            import importSVG
            importSVG.insert(vector_path, doc_name)
            return True
        except Exception:
            pass
        try:
            import ImportGui
            ImportGui.insert(vector_path, doc_name)
            return True
        except Exception:
            pass
    return False


# Return an object Shape when its BoundBox is accessible, otherwise None.
def _safe_shape(obj):
    try:
        shp = getattr(obj, "Shape", None)
        if shp is None:
            return None
        # Some objects may have empty shapes
        try:
            _ = shp.BoundBox
        except Exception:
            return None
        return shp
    except Exception:
        return None


# Build a Part.Compound from a list of shapes.
def _shape_to_compound(shapes):
    """Build a Part.Compound from a list of shapes."""
    if Part is None:
        return None
    try:
        valid = [s for s in shapes if s is not None]
        if not valid:
            return None
        # Flatten compounds (optional, but helps)
        exploded = []
        for s in valid:
            try:
                if hasattr(s, "Solids") and s.Solids:
                    exploded.append(s)
                elif hasattr(s, "Faces") and s.Faces:
                    exploded.append(s)
                elif hasattr(s, "Wires") and s.Wires:
                    exploded.append(s)
                elif hasattr(s, "Edges") and s.Edges:
                    exploded.append(s)
                else:
                    exploded.append(s)
            except Exception:
                exploded.append(s)

        return Part.makeCompound(exploded)
    except Exception:
        return None


# Try to create a face for each closed wire.
def _try_make_faces_from_wires(shp):
    """
    Try to create a face for each closed wire.

    Return one Face, a Compound of multiple faces, or None if none can be made.
    Nested wires are treated as separate faces, not subtracted as holes.
    """
    if Part is None or shp is None:
        return None
    try:
        faces = []
        wires = []
        try:
            wires = list(getattr(shp, "Wires", [])) or []
        except Exception:
            wires = []

        if not wires:
            # DXF/SVG imports often deliver a bare compound of edges, which
            # exposes no Wires. Sort the edges into connected wires so closed
            # contours (for example a profile built from several arcs) still
            # become faces.
            try:
                edges = list(getattr(shp, "Edges", [])) or []
            except Exception:
                edges = []
            if edges:
                try:
                    groups = Part.sortEdges(edges)
                except Exception:
                    groups = []
                for group in groups:
                    try:
                        wires.append(Part.Wire(group))
                    except Exception:
                        continue

        for w in wires:
            try:
                if hasattr(w, "isClosed") and not w.isClosed():
                    continue
                f = Part.Face(w)
                faces.append(f)
            except Exception:
                continue

        if not faces:
            return None
        return Part.makeCompound(faces) if len(faces) > 1 else faces[0]
    except Exception:
        return None


# Import DXF/SVG into Nesting_Preview and convert to stable Part::Feature.
def _split_svg_shapes(shapes):
    """One part per exterior contour, with directly enclosed holes attached.

    Work from exact imported wires, including subpaths of a single SVG path.
    Containment depth handles holes and material islands independently of
    SVG object/group boundaries. Overlapping exterior contours stay separate.
    """
    profiles = []
    tolerance = 1e-7
    for shape in shapes:
        wires = list(shape.Wires)
        if not wires and shape.Edges:
            wires = [Part.Wire(group) for group in Part.sortEdges(shape.Edges)]
        for wire in wires:
            if not wire.isClosed():
                raise ValueError('SVG parts must have closed contours.')
            face = Part.Face(wire)
            if not face.isValid() or face.Area <= tolerance or face.BoundBox.ZLength > tolerance:
                raise ValueError('SVG contains an invalid or non-planar contour.')
            u0, u1, v0, v1 = face.ParameterRange
            if face.normalAt((u0 + u1) / 2, (v0 + v1) / 2).z < 0:
                face.reverse()
            box = face.BoundBox
            def same_bounds(other):
                return all(abs(a - b) <= tolerance for a, b in zip(
                    (box.XMin, box.YMin, box.XMax, box.YMax),
                    (other.XMin, other.YMin, other.XMax, other.YMax)))
            # Fill/stroke imports can produce coincident copies. Never make
            # an identical contour into another part or a zero-area hole.
            duplicate = False
            for old in profiles:
                if same_bounds(old['face'].BoundBox) and abs(face.Area - old['face'].Area) <= max(tolerance, face.Area * 1e-9):
                    area_tolerance = max(tolerance, face.Area * 1e-9)
                    if face.cut(old['face']).Area <= area_tolerance and old['face'].cut(face).Area <= area_tolerance:
                        duplicate = True
                        break
            if not duplicate:
                profiles.append(dict(wire=wire.copy(), face=face, parent=None))
    if not profiles:
        raise ValueError('SVG contains no closed part contours.')
    for index, inner in enumerate(profiles):
        inside = inner['face']
        box = inside.BoundBox
        candidates = []
        for other_index, outer in enumerate(profiles):
            outside = outer['face']
            bigger = outside.BoundBox
            if index == other_index or outside.Area <= inside.Area + tolerance:
                continue
            if (box.XMin < bigger.XMin - tolerance or box.YMin < bigger.YMin - tolerance or
                    box.XMax > bigger.XMax + tolerance or box.YMax > bigger.YMax + tolerance):
                continue
            area_tolerance = max(tolerance, inside.Area * 1e-8)
            if inside.cut(outside).Area <= area_tolerance and \
                    outside.OuterWire.distToShape(inside.OuterWire)[0] > tolerance:
                candidates.append((outside.Area, other_index))
        if candidates:
            inner['parent'] = min(candidates)[1]
    components = []
    for index, profile in enumerate(profiles):
        depth = 0
        parent = profile['parent']
        while parent is not None:
            depth += 1
            parent = profiles[parent]['parent']
        if depth % 2:
            continue
        holes = [child for child in profiles if child['parent'] == index]
        material = profile['face']
        for hole in holes:
            material = material.cut(hole['face'])
        if not material.isValid() or len(material.Faces) != 1 or material.Area <= tolerance:
            raise ValueError('SVG contains overlapping or invalid hole contours.')
        components.append((Part.makeCompound([profile['wire']] + [hole['wire'] for hole in holes]), material))
    return components


# Import DXF/SVG into Nesting_Preview and convert to stable Part::Feature.
def import_2d_file_to_preview(panel, path, fmt=None, make_faces_if_possible=True,
                             group_into_single_object=True, label_prefix=None, split_disconnected=False):
    """
    Import DXF/SVG into Nesting_Preview and convert to stable Part::Feature.

    Args:
        panel: NestingTaskPanel
        path: file path
        fmt: "dxf" or "svg" (optional; auto from extension)
        make_faces_if_possible: try to create Faces from closed wires (optional)
        group_into_single_object: if True -> make ONE Part::Feature from all imported shapes
                                 if False -> make one Part::Feature per imported object (quick & simple)
        split_disconnected: create one feature per outer contour, preserving holes
        label_prefix: label prefix for created features

    Returns:
        created_names: list[str] of created Part::Feature object Names in preview doc
    """
    created_names = []
    p_doc = None
    before = None
    try:
        if not path or not os.path.exists(path):
            App.Console.PrintError(tr('ipnestingimport2d_file_not_found_s') % str(path))
            return created_names

        ext = os.path.splitext(path)[1].lower().lstrip(".")
        fmt = (fmt or ext).lower()

        p_doc = _ensure_preview_doc(panel)
        if not p_doc:
            App.Console.PrintError(tr('ipnestingimport2d_could_not_ensure_preview_document'))
            return created_names

        before = set([o.Name for o in p_doc.Objects])

        ok = False
        if fmt == "dxf":
            ok = _import_dxf(path, p_doc.Name)
        elif fmt == "svg":
            ok = _import_svg(path, p_doc.Name)
        else:
            App.Console.PrintError(tr('ipnestingimport2d_unsupported_format_s') % fmt)
            return created_names

        if not ok:
            App.Console.PrintError(tr('ipnestingimport2d_import_failed_for_s') % path)
            if split_disconnected:
                for obj in reversed(list(p_doc.Objects)):
                    if obj.Name not in before:
                        p_doc.removeObject(obj.Name)
            return created_names

        try:
            p_doc.recompute()
        except Exception:
            pass

        after_objs = [o for o in p_doc.Objects if o.Name not in before]
        if not after_objs:
            App.Console.PrintMessage(tr('ipnestingimport2d_import_created_no_new_objects'))
            return created_names

        # Collect shapes
        imported_shapes = []
        per_obj_shapes = []
        for o in after_objs:
            shp = _safe_shape(o)
            if shp is None:
                continue
            imported_shapes.append(shp)
            per_obj_shapes.append((o, shp))

        if not imported_shapes:
            App.Console.PrintError(tr('ipnestingimport2d_imported_objects_had_no_usable_shape'))
            if split_disconnected:
                for obj in reversed(list(p_doc.Objects)):
                    if obj.Name not in before:
                        p_doc.removeObject(obj.Name)
            return created_names

        # Create stable Part::Feature(s)
        label_prefix = label_prefix or ("DXF" if fmt == "dxf" else "SVG")

        if split_disconnected:
            components = _split_svg_shapes(imported_shapes)
            label = tr('s_s_d9cd37') % (label_prefix, os.path.basename(path))
            for index, (wires, material) in enumerate(components, 1):
                feat = p_doc.addObject('Part::Feature', 'Preview2D')
                created_names.append(feat.Name)
                feat.Label = label + (' [%d]' % index if len(components) > 1 else '')
                feat.Shape = material if make_faces_if_possible else wires
                feat.addProperty('App::PropertyString', 'SVGSourceFile', '1st Nesting')
                feat.SVGSourceFile = os.path.basename(path)
                feat.addProperty('App::PropertyInteger', 'SVGPartNumber', '1st Nesting')
                feat.SVGPartNumber = index
        elif group_into_single_object:
            compound = _shape_to_compound(imported_shapes)
            final_shape = compound

            if make_faces_if_possible:
                face_shape = _try_make_faces_from_wires(compound)
                if face_shape is not None:
                    final_shape = face_shape

            if final_shape is None:
                App.Console.PrintError(tr('ipnestingimport2d_failed_to_build_compound_shape'))
                return created_names

            feat = p_doc.addObject("Part::Feature", "Preview2D")
            feat.Label = tr('s_s_d9cd37') % (label_prefix, os.path.basename(path))
            feat.Shape = final_shape
            created_names.append(feat.Name)
        else:
            for (src_obj, shp) in per_obj_shapes:
                final_shape = shp
                if make_faces_if_possible:
                    face_shape = _try_make_faces_from_wires(shp)
                    if face_shape is not None:
                        final_shape = face_shape

                feat = p_doc.addObject("Part::Feature", "Preview2D")
                feat.Label = tr('s_s_d9cd37') % (label_prefix, getattr(src_obj, "Label", src_obj.Name))
                feat.Shape = final_shape
                created_names.append(feat.Name)

        # Optional: hide raw imported objects to avoid clutter (keep them if you prefer)
        try:
            for o in after_objs:
                try:
                    if hasattr(o, "ViewObject"):
                        o.ViewObject.Visibility = False
                except Exception:
                    pass
        except Exception:
            pass

        try:
            p_doc.recompute()
        except Exception:
            pass

        App.Console.PrintMessage(tr('ipnestingimport2d_created_d_part_feature_s_from_s') %
                                 (len(created_names), os.path.basename(path)))
        return created_names

    except Exception:
        App.Console.PrintError(tr('ipnestingimport2d_import_2d_file_to_preview_failed') + traceback.format_exc())
        if split_disconnected and p_doc is not None and before is not None:
            # A failed file must not leave half a set of parts or raw objects.
            for obj in reversed(list(p_doc.Objects)):
                if obj.Name not in before:
                    p_doc.removeObject(obj.Name)
            created_names = []
        return created_names


# Convenience wrappers
# Import a DXF into stable preview features using the shared 2D importer.
def import_dxf_to_preview(panel, path, **kwargs):
    return import_2d_file_to_preview(panel, path, fmt="dxf", **kwargs)


# Import independent SVG profiles as stable preview features with attached holes.
def import_svg_to_preview(panel, path, **kwargs):
    # Preserve native curves and transparent hole outlines in the preview.
    if "make_faces_if_possible" not in kwargs:
        kwargs["make_faces_if_possible"] = False
    kwargs.setdefault('split_disconnected', True)
    return import_2d_file_to_preview(panel, path, fmt="svg", **kwargs)
