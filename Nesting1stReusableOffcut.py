"""Display the CLI's largest connected reusable offcut; all geometry is in mm."""
import math
from Nesting1stResultSVG import _ring, _shape_area


def reusable_offcut(data):
    """Read a measured contour, retaining conservative texture-group reports.

    Never substitute total sheet waste or a bounding box for this measurement.
    Older engines and explicitly disabled calculations return None, not zero.
    """
    report = data.get('reusableOffcut') or data.get('grainMatchingEnvelopeReport')
    if not isinstance(report, dict) or report.get('enabled') is False or report.get('evaluated') is not True:
        return None
    try:
        area = float(report['area'])
        width = float(report['minWidthMm'])
        if not math.isfinite(area) or area < 0 or not math.isfinite(width) or width <= 0:
            return None
        if area == 0:
            return dict(area=0.0, percentage=0.0, sheet_index=None, outer=[], holes=[], min_width_mm=width)
        outer = _ring(report['points'])
        holes = [_ring(hole) for hole in report.get('holes', [])]
        # Integer clipping and JSON decimal coordinates can differ very slightly.
        if abs(_shape_area(outer, holes) - area) > max(0.01, area * 1e-6):
            return None
        for index, sheet in enumerate(data.get('sheets', [])):
            if str(sheet.get('id')) != str(report.get('sheetId')):
                continue
            stock = sheet.get('points') or sheet.get('outer')
            if not stock:
                w, h = float(sheet['width']), float(sheet['height'])
                stock = [[0, 0], [w, 0], [w, h], [0, h]]
            stock_area = _shape_area(_ring(stock), [_ring(h) for h in sheet.get('holes', [])])
            if stock_area <= 0 or area > stock_area + max(0.01, stock_area * 1e-6):
                return None
            return dict(area=area, percentage=min(100.0, 100 * area / stock_area),
                        sheet_index=int(sheet.get('sheet_instance_index', index)), outer=outer,
                        holes=holes, min_width_mm=width)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None


def offcut_text(data, translate, units='mm'):
    """Convert square units only at the display boundary, without rounding mm."""
    report = reusable_offcut(data)
    if report is None:
        return translate('result_info_single_piece_offcut_unavailable')
    inch = units == 'inch'
    return translate('result_info_single_piece_offcut') % (
        report['area'] / (25.4 ** 2 if inch else 1.0),
        'in²' if inch else 'mm²', report['percentage'])


def create_offcut_outline(importer, translate):
    """Add an annotation contour to its sheet group, outside the CAD part list."""
    import FreeCAD as App
    import Part
    report = reusable_offcut(importer.result_data)
    if report is None or report['area'] <= 0:
        return None
    group = importer.sheet_groups.get(report['sheet_index'])
    if group is None:
        return None
    wires = []
    for ring in [report['outer']] + report['holes']:
        points = [App.Vector(float(x), float(y), 0.05) for x, y in ring]
        if (points[0] - points[-1]).Length > 1e-9:
            points.append(points[0])
        wires.append(Part.makePolygon(points))
    obj = importer.result_doc.addObject('Part::Feature', 'Reusable_offcut')
    obj.Shape = Part.makeCompound(wires)
    obj.Label = str(offcut_text(importer.result_data, translate, getattr(importer.panel, 'display_units', 'mm')))
    obj.addProperty('App::PropertyArea', 'ReusableArea', 'Offcut').ReusableArea = report['area']
    obj.addProperty('App::PropertyLength', 'MinimumWidth', 'Offcut').MinimumWidth = report['min_width_mm']
    obj.addProperty('App::PropertyFloat', 'SheetPercentage', 'Offcut', 'Percentage of this sheet').SheetPercentage = report['percentage']
    for name in ('ReusableArea', 'MinimumWidth', 'SheetPercentage'):
        obj.setEditorMode(name, 1)
    group.addObject(obj)
    if getattr(App, 'GuiUp', False):
        obj.ViewObject.DisplayMode = 'Wireframe'
        obj.ViewObject.LineColor = (0.0, 0.65, 0.4)
        obj.ViewObject.LineWidth = 3.0
    return obj
