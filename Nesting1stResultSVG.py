"""Standalone, coloured SVG reports from the successfully imported nesting result."""
import colorsys
from html import escape
import json
import math
from pathlib import Path


def _ring(points):
    ring = [[float(p['x']), float(p['y'])] if isinstance(p, dict) else
            [float(p[0]), float(p[1])] for p in points]
    if len(ring) < 3 or any(not math.isfinite(v) for p in ring for v in p):
        raise ValueError('Invalid result contour')
    return ring


def _area(points):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))/2)


def _shape_area(outer, holes):
    return max(0, _area(outer)-sum(_area(hole) for hole in holes))


def _transform(points, placement):
    angle = math.radians(float(placement.get('rotation',0)))
    c, s = math.cos(angle), math.sin(angle)
    x, y = float(placement.get('x',0)), float(placement.get('y',0))
    return [[x+c*px-s*py,y+s*px+c*py] for px,py in _ring(points)]


def _path(outer, holes):
    return ' '.join('M '+' L '.join('%.6f,%.6f' % tuple(p) for p in ring)+' Z'
                    for ring in [outer]+holes)


def _colour(index):
    rgb = colorsys.hsv_to_rgb((.08+index*.618033988749895)%1, .48, .92)
    return '#'+''.join('%02x' % round(v*255) for v in rgb)


def render_result_svg(data, translate):
    """Render normalized placements; group proxies must already be expanded.

    Contours keep their millimetre coordinates inside uniform SVG transforms.
    Areas exclude selected holes and use actual member contours, not envelopes.
    """
    from Nesting1stReusableOffcut import offcut_text, reusable_offcut
    offcut = reusable_offcut(data)
    sources = {str(p['source_part_index']): p for p in data.get('sourceParts',[])}
    sheet_parts = {}
    count = 0
    for placement in data.get('placements',[]):
        if not placement.get('placed',True):
            continue
        source = sources.get(str(placement.get('source_part_index')), {})
        outer = _ring(placement['absolute_points']) if placement.get('absolute_points') else \
                _transform(source.get('points',placement.get('points',[])),placement)
        holes = [_ring(h) for h in placement['absolute_holes']] if 'absolute_holes' in placement else \
                [_transform(h,placement) for h in source.get('holes',[])]
        count += 1
        part = dict(number=count, outer=outer, holes=holes, placement=placement,
                    label=source.get('label') or source.get('preview_object_name') or str(placement.get('id',count)),
                    colour=_colour(count-1), area=_shape_area(outer,holes))
        sheet_parts.setdefault(int(placement.get('sheet_instance_index',0)),[]).append(part)
    sheets = []
    for index, sheet in enumerate(data.get('sheets',[])):
        outer = sheet.get('outer') or sheet.get('points')
        if not outer:
            w,h = float(sheet.get('width',0)),float(sheet.get('height',0))
            outer = [[0,0],[w,0],[w,h],[0,h]]
        outer = _ring(outer)
        holes = [_ring(h) for h in sheet.get('holes',[]) or []]
        area = _shape_area(outer,holes)
        if area <= 0:
            raise ValueError('Invalid sheet area')
        parts = sheet_parts.get(int(sheet.get('sheet_instance_index',index)),[])
        sheets.append(dict(index=index, sheet=sheet, outer=outer, holes=holes,
                           area=area, parts=parts, used=sum(p['area'] for p in parts)))
    if not sheets or sum(len(sheet['parts']) for sheet in sheets) != count:
        raise ValueError('Result placements do not match sheets')
    unplaced = data.get('unplaced',[]) or []
    used_sheets = [sheet for sheet in sheets if sheet['parts']]
    total_area = sum(sheet['area'] for sheet in used_sheets)
    total_used = sum(sheet['used'] for sheet in used_sheets)
    utilisation = 100*total_used/total_area if total_area else 0
    unit = str(data.get('units','mm'))
    area_unit = unit+'²'
    def tr(key,*values):
        text = str(translate(key))
        return text % values if values else text
    def text(x,y,value,size=16,attributes=''):
        return '<text x="%.3f" y="%.3f" font-size="%s" %s>%s</text>' % (x,y,size,attributes,escape(str(value)))
    content = [text(40,44,tr('result_info'),28),
               text(40,77,tr('nesting_completed_partially' if unplaced else 'nesting_completed')),
               text(40,110,tr('result_info_placed_total',count,count+len(unplaced))),
               text(640,110,tr('result_info_sheets',len(used_sheets))),
               text(40,138,tr('result_info_utilisation',utilisation)),
               text(640,138,tr('result_info_waste',100-utilisation)),
               text(40,166,tr('result_info_sheet_area',total_area,area_unit)),
               text(640,166,tr('unplaced_parts_label',len(unplaced))),
               text(40,194,offcut_text(data,translate))]
    y = 224
    identifiers = [str(data.get(key,'')) for key in ('job_id','created_at') if data.get(key)]
    if identifiers:
        content.append(text(40,y,' · '.join(identifiers),12))
        y += 26
    for sheet in sheets:
        parts = sheet['parts']
        xs,ys = zip(*sheet['outer'])
        x0,x1,y0,y1 = min(xs),max(xs),min(ys),max(ys)
        width,height = x1-x0,y1-y0
        scale = min(1100/width,650/height)
        title = tr('sheet_d',sheet['index']+1)
        material_label = sheet['sheet'].get('_ip_nesting',{}).get('label') or sheet['sheet'].get('label')
        if material_label:
            title += ' · '+str(material_label)
        content.append('<g class="sheet" data-sheet-index="%d">' % sheet['index'])
        content.append(text(40,y+20,title,23))
        content.append(text(40,y+48,'%.2f × %.2f %s · %s' % (width,height,unit,tr('result_info_sheet_area',sheet['area'],area_unit))))
        utilisation = 100*sheet['used']/sheet['area']
        content.append(text(40,y+76,tr('result_info_utilisation',utilisation)+' · '+tr('result_info_waste',100-utilisation)))
        content.append(text(40,y+104,tr('result_info_placed_total',len(parts),len(parts))))
        drawing_y = y+126
        content.append('<g transform="translate(%.6f %.6f) scale(%.9f %.9f)">' %
                       (40-x0*scale,drawing_y+y1*scale,scale,-scale))
        content.append('<path class="sheet-outline" d="%s" fill="#f4f6f8" fill-rule="evenodd" stroke="#677587" stroke-width="%.9f"/>' %
                       (_path(sheet['outer'],sheet['holes']),1.5/scale))
        for part in parts:
            placement = part['placement']
            title = '#%d · %s · X %.2f · Y %.2f · %.2f° · %.2f %s' % (
                part['number'],part['label'],float(placement.get('x',0)),float(placement.get('y',0)),
                float(placement.get('rotation',0)),part['area'],area_unit)
            content.append('<path class="nesting-part" data-part-number="%d" d="%s" fill="%s" fill-rule="evenodd" stroke="#344457" stroke-width="%.9f"><title>%s</title></path>' %
                           (part['number'],_path(part['outer'],part['holes']),part['colour'],.8/scale,escape(title)))
            px = (min(p[0] for p in part['outer'])+max(p[0] for p in part['outer']))/2
            py = (min(p[1] for p in part['outer'])+max(p[1] for p in part['outer']))/2
            content.append('<text transform="translate(%.6f %.6f) scale(1 -1)" font-size="%.9f" text-anchor="middle" dominant-baseline="middle">%d</text>' % (px,py,14/scale,part['number']))
        if offcut is not None and offcut['sheet_index'] == int(sheet['sheet'].get('sheet_instance_index',sheet['index'])) and offcut['area'] > 0:
            content.append('<path class="reusable-offcut" d="%s" fill="none" stroke="#00a666" stroke-width="%.9f"><title>%s</title></path>' %
                           (_path(offcut['outer'],offcut['holes']),2/scale,escape(str(offcut_text(data,translate)))))
        content.append('</g>')
        y = drawing_y+height*scale+32
        for part in parts:
            placement = part['placement']
            content.append('<rect x="40" y="%.3f" width="16" height="16" fill="%s"/>' % (y-13,part['colour']))
            content.append(text(68,y,'#%d · %s · X %.2f · Y %.2f · %.2f° · %.2f %s' % (
                part['number'],part['label'],float(placement.get('x',0)),float(placement.get('y',0)),
                float(placement.get('rotation',0)),part['area'],area_unit),14))
            y += 26
        content.append('</g>')
        y += 38
    if unplaced:
        content.append(text(40,y,tr('unplaced_parts_label',len(unplaced)),23))
        y += 32
        for item in unplaced:
            source = sources.get(str(item.get('_ip_nesting',{}).get('source_part_index',item.get('source_part_index'))),{})
            label = item.get('_ip_nesting',{}).get('label') or source.get('label') or item.get('source') or item.get('id','')
            content.append(text(40,y,label))
            y += 26
    metadata = dict(job_id=data.get('job_id'),units=unit,placed=count,unplaced=len(unplaced),
                    used_sheets=len(used_sheets),sheet_area=total_area,part_area=total_used)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="%.3f" viewBox="0 0 1200 %.3f">\n'
            '<title>%s</title><metadata>%s</metadata>\n'
            '<rect width="100%%" height="100%%" fill="white"/>\n'
            '<g font-family="Segoe UI, DejaVu Sans, sans-serif" fill="#263449">\n%s\n</g></svg>\n') % (
                y+30,y+30,escape(tr('result_info')),escape(json.dumps(metadata,ensure_ascii=False)), '\n'.join(content))


def export_from_panel(panel):
    """Save the current successful import; never export stale on-disk job data."""
    from PySide import QtGui
    from Nesting1stLanguages import tr
    manager = getattr(panel,'_nesting_manager',None)
    importer = getattr(manager,'importer',None)
    if importer is None or not importer.result_data.get('sheets'):
        QtGui.QMessageBox.information(panel.form,tr('export_nesting_result_to_svg'),tr('no_nesting_result_to_export'))
        return False
    filename,_ = QtGui.QFileDialog.getSaveFileName(panel.form,tr('export_nesting_result_to_svg'),
                                                'Nesting_Result.svg',tr('svg_files_svg_svg_all_files'))
    if not filename:
        return False
    path = Path(filename)
    if path.suffix.lower() != '.svg':
        path = Path(str(path)+'.svg')
    try:
        document = render_result_svg(importer.result_data,tr)
        path.write_text(document,encoding='utf-8')
        return True
    except Exception as exc:
        QtGui.QMessageBox.critical(panel.form,tr('export_nesting_result_to_svg'),
                                 tr('nesting_result_svg_export_failed') % str(exc))
        return False
