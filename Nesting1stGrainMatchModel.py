"""Rigid texture assemblies, with FreeCAD geometry loaded for perimeter export.

Layout transforms and result expansion are independent of Qt and FreeCAD.
"""
import copy
import math


def rotate(point, angle):
    a = math.radians(angle)
    return [point[0]*math.cos(a)-point[1]*math.sin(a),
            point[0]*math.sin(a)+point[1]*math.cos(a)]


def transform(points, pose):
    return [[q[0]+pose[0], q[1]+pose[1]] for q in (rotate(p, pose[2]) for p in points)]


def normalize_poses(parts, poses):
    """Validate manual placements and translate the entire assembly to its origin."""
    if len(parts) < 2 or len(poses) != len(parts):
        raise ValueError('Every matching part needs a placement.')
    result = []
    for pose in poses:
        if len(pose) != 3 or not all(math.isfinite(float(value)) for value in pose):
            raise ValueError('Matching placements must contain finite x, y and angle values.')
        result.append([float(pose[0]), float(pose[1]), float(pose[2]) % 360])
    outlines = [transform(part['points'], pose) for part, pose in zip(parts, result)]
    xmin = min(x for points in outlines for x, y in points)
    ymin = min(y for points in outlines for x, y in points)
    return [[round(pose[0]-xmin, 6), round(pose[1]-ymin, 6), pose[2]] for pose in result]


def definition_poses(parts, definition, spacing):
    """Manual coordinates are authoritative; older saved groups remain readable."""
    if 'manual_poses' in definition:
        return normalize_poses(parts, definition['manual_poses'])
    return solve(parts, definition['links'], spacing)


def polygon(points):
    """Canonical CCW vertices; merge straight sampled segments for stable side IDs."""
    p = [[round(float(x), 6), round(float(y), 6)] for x, y in points]
    if not all(math.isfinite(v) for point in p for v in point):
        raise ValueError('Part coordinates must be finite.')
    if len(p) > 1 and p[0] == p[-1]:
        p.pop()
    changed = True
    while changed and len(p) > 3:
        changed = False
        for i in range(len(p)):
            a, b, c = p[i-1], p[i], p[(i+1) % len(p)]
            ab = (b[0]-a[0], b[1]-a[1]); bc = (c[0]-b[0], c[1]-b[1])
            if (math.hypot(*ab) < 1e-7 or
                (abs(ab[0]*bc[1]-ab[1]*bc[0]) <= 1e-7*max(1, math.hypot(*ab)+math.hypot(*bc))
                 and ab[0]*bc[0]+ab[1]*bc[1] >= 0)):
                p.pop(i); changed = True; break
    area = sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(p, p[1:]+p[:1]))/2
    if len(p) < 3 or abs(area) < 1e-7:
        raise ValueError('A matching part needs a non-empty closed outline.')
    if area < 0:
        p.reverse()
    start = min(range(len(p)), key=lambda i: (p[i][0], -p[i][1]))
    return p[start:]+p[:start]


def edges(parts):
    result = []
    for i, part in enumerate(parts):
        points = polygon(part['points'])
        boundaries = part.get('matching_edges')
        if boundaries is None:
            boundaries = [dict(a=a, b=b) for a, b in zip(points, points[1:]+points[:1])]
        for side, boundary in enumerate(boundaries):
            result.append(dict(boundary, number=len(result)+1, part=i, side=side))
    return result


def solve(parts, links, spacing, partial=False):
    """Join edge midpoints, opposing their directions; links must form a tree."""
    spacing = float(spacing)
    if not math.isfinite(spacing) or spacing < 0:
        raise ValueError('Part spacing must be finite and nonnegative.')
    if len(parts) < 2 or (not partial and len(links) != len(parts)-1):
        raise ValueError('Use exactly one fewer connection than the number of parts.')
    numbered = {e['number']: e for e in edges(parts)}
    graph = [[] for _ in parts]; used = set(); roots = list(range(len(parts)))
    def root(i):
        while roots[i] != i:
            i = roots[i]
        return i
    for first, second in links:
        if partial and (first is None or second is None):
            continue
        if first not in numbered or second not in numbered:
            raise ValueError('Select both edges in every connection.')
        a, b = numbered[first], numbered[second]
        if a.get('curved') or b.get('curved'):
            raise ValueError('Choose straight edges for texture matching; curved boundaries are shown only as references.')
        if a['part'] == b['part'] or first in used or second in used:
            raise ValueError('Connect different parts; each edge can be used only once.')
        if root(a['part']) == root(b['part']):
            missing = [p.get('label', p.get('name', str(i+1))) for i, p in enumerate(parts) if not graph[i]]
            raise ValueError('These connections create a cycle between already joined parts.' +
                             (' Parts still unconnected: '+', '.join(missing)+'.' if missing else ''))
        roots[root(b['part'])] = root(a['part'])
        used.update((first, second))
        graph[a['part']].append((a, b)); graph[b['part']].append((b, a))
    active = [i for i in range(len(parts)) if graph[i]]
    if partial and not active:
        return [None]*len(parts)
    poses = {}; next_x = 0.
    # Each connected component can be previewed before the whole tree is complete.
    for start in active if partial else [0]:
        if start in poses:
            continue
        component = _solve_component(graph, start, spacing)
        shapes = [transform(parts[i]['points'], pose) for i, pose in component.items()]
        xmin = min(x for poly in shapes for x, y in poly); ymin = min(y for poly in shapes for x, y in poly)
        xmax = max(x for poly in shapes for x, y in poly)
        for i, pose in component.items():
            poses[i] = [pose[0]-xmin+next_x, pose[1]-ymin, pose[2]]
        next_x += xmax-xmin+max(20, spacing*2)
    if not partial and len(poses) != len(parts):
        missing = [p.get('label', p.get('name', str(i+1))) for i, p in enumerate(parts) if i not in poses]
        raise ValueError('Connect all parts. Still unconnected: '+', '.join(missing)+'.')
    return [poses.get(i) for i in range(len(parts))]


def _solve_component(graph, start, spacing):
    poses = {start: [0., 0., 0.]}; pending = [start]
    while pending:
        parent = pending.pop(0)
        for a, b in graph[parent]:
            child = b['part']
            if child in poses:
                continue
            pa, pb = transform([a['a'], a['b']], poses[parent])
            dx, dy = pb[0]-pa[0], pb[1]-pa[1]; length = math.hypot(dx, dy)
            bx, by = b['b'][0]-b['a'][0], b['b'][1]-b['a'][1]
            angle = (math.degrees(math.atan2(dy, dx)-math.atan2(by, bx))+180) % 360
            mid = rotate([(b['a'][0]+b['b'][0])/2, (b['a'][1]+b['b'][1])/2], angle)
            poses[child] = [(pa[0]+pb[0])/2 + spacing*dy/length-mid[0],
                            (pa[1]+pb[1])/2 - spacing*dx/length-mid[1], angle]
            pending.append(child)
    return poses


def _convex_hull(points, precision=6):
    """Monotone-chain convex hull of [x, y] points, returned CCW without a closing duplicate."""
    # Export uses stable rounded coordinates; live collision sweeps need full
    # precision so each successive move starts from a valid boundary position.
    pts = sorted({(float(x), float(y)) if precision is None else
                  (round(float(x), precision), round(float(y), precision)) for x, y in points})
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


def _close_duplicate(points, tol=1e-7):
    if len(points) > 1 and math.hypot(points[0][0]-points[-1][0], points[0][1]-points[-1][1]) <= tol:
        return points[:-1]
    return points


def _close_ring(points, tol=1e-9):
    """Ensure the ring's first and last points match (needed by Part.makePolygon)."""
    if len(points) < 3:
        return list(points)
    if abs(points[0][0]-points[-1][0]) > tol or abs(points[0][1]-points[-1][1]) > tol:
        return list(points) + [points[0]]
    return list(points)


def _gap_bridges(first, second, distance, contact):
    """Join only facing boundary spans; retain the surrounding concave profiles."""
    bridges = []
    for a, b in zip(first, first[1:]+first[:1]):
        length = math.dist(a, b)
        if length <= 1e-8:
            continue
        u = [(b[k]-a[k])/length for k in (0, 1)]
        outward = [u[1], -u[0]]  # Input rings are counterclockwise.
        for c, d in zip(second, second[1:]+second[:1]):
            other_length = math.dist(c, d)
            if other_length <= 1e-8:
                continue
            v = [(d[k]-c[k])/other_length for k in (0, 1)]
            # Export rounds vertices to micrometres. A rotated straight edge
            # can therefore differ slightly from its parallel neighbour.
            if abs(u[0]*v[1]-u[1]*v[0]) > 1e-6 or sum(u[k]*v[k] for k in (0, 1)) > 0:
                continue
            separation = sum((c[k]-a[k])*outward[k] for k in (0, 1))
            if separation <= 1e-8 or abs(separation-distance) > 1e-4:
                continue
            project = lambda p: sum(p[k]*u[k] for k in (0, 1))
            start = max(min(project(a),project(b)), min(project(c),project(d)))
            end = min(max(project(a),project(b)), max(project(c),project(d)))
            if end-start <= 1e-7:
                continue
            def on_edge(p, q, t):
                fraction = (t-project(p))/(project(q)-project(p))
                return [p[k]+fraction*(q[k]-p[k]) for k in (0, 1)]
            bridges.append([on_edge(a,b,start), on_edge(a,b,end),
                            on_edge(c,d,end), on_edge(c,d,start)])
    if bridges:
        return bridges
    # Nonparallel profiles or diagonally separated corners need a local neck.
    # Its anchors lie on the real boundaries, never on a global bounding box.
    sizes = [min(max(p[k] for p in ring)-min(p[k] for p in ring) for k in (0,1))
             for ring in (first, second)]
    width = max(1e-4, min(min(sizes)/100.0, max(.01, distance/100.0)))
    anchors = []
    for ring, point in zip((first, second), contact):
        for a, b in zip(ring, ring[1:]+ring[:1]):
            length = math.dist(a,b)
            if length <= 1e-8:
                continue
            t = sum((point[k]-a[k])*(b[k]-a[k]) for k in (0,1))/(length*length)
            projected = [a[k]+t*(b[k]-a[k]) for k in (0,1)]
            if -1e-6 <= t <= 1+1e-6 and math.dist(point,projected) <= 1e-5:
                for fraction in (max(0,t-width/length), min(1,t+width/length)):
                    anchors.append([a[k]+fraction*(b[k]-a[k]) for k in (0,1)])
    bridge = _convex_hull(anchors, precision=None)
    if len(bridge) < 3:
        raise ValueError('Unable to connect the exact texture-group contours.')
    return [bridge]


def outer_contour(polygons, holes_by_poly=None):
    """Exact member outlines, with local gap bridges to make one CLI polygon.

    Facing parallel edges are joined across their overlap. Other separated
    profiles use a narrow boundary-to-boundary neck. Interior layout gaps are
    reserved; only explicitly selected member holes are exported as holes.
    No convex-envelope fallback is used when geometry is unavailable or fails.
    """
    if not polygons:
        return [], []
    import Part
    from FreeCAD import Vector

    def face(points):
        result = Part.Face(Part.makePolygon(_close_ring([Vector(float(x),float(y),0) for x,y in points])))
        if not result.isValid() or result.Area <= 1e-9:
            raise ValueError('Invalid texture-group contour.')
        return result

    polygons = [polygon(points) for points in polygons]
    holes_by_poly = holes_by_poly or [[] for _ in polygons]
    if len(holes_by_poly) != len(polygons):
        raise ValueError('Every texture-group member needs a hole list.')
    profiles = [face(points) for points in polygons]
    selected_holes = [face(hole) for holes in holes_by_poly for hole in (holes or [])]
    material = []
    for profile, holes in zip(profiles, holes_by_poly):
        for hole in (holes or []):
            profile = profile.cut(face(hole))
        material.append(profile.extrude(Vector(0,0,1)))

    # Minimum spanning connections avoid joining unrelated, distant members.
    candidates = []
    for i, first in enumerate(profiles):
        for j in range(i+1,len(profiles)):
            distance, contacts, _ = first.distToShape(profiles[j])
            candidates.append((distance,i,j,contacts))
    components = list(range(len(profiles)))
    def root(index):
        while components[index] != index:
            index = components[index]
        return index
    for distance, i, j, contacts in sorted(candidates, key=lambda entry: entry[:3]):
        first, second = root(i), root(j)
        if first == second:
            continue
        components[second] = first
        # Area-overlapping or edge-touching members already fuse exactly.
        if distance <= 1e-7 and (profiles[i].common(profiles[j]).Area > 1e-7 or
                                profiles[i].common(profiles[j]).Length > 1e-7):
            continue
        contact = [[p.x,p.y] for p in contacts[0]]
        for bridge in _gap_bridges(polygons[i],polygons[j],distance,contact):
            material.append(face(bridge).extrude(Vector(0,0,1)))
    solid = material[0].multiFuse(material[1:]).removeSplitter() if len(material)>1 else material[0]
    bottom = [f for f in solid.Faces if f.BoundBox.ZLength < 1e-7 and abs(f.BoundBox.ZMin) < 1e-7]
    if len(bottom) != 1:
        raise ValueError('Unable to produce one exact texture-group perimeter.')
    cap = bottom[0]
    outer_wire = cap.OuterWire
    outer = polygon(_close_duplicate([[v.Point.x,v.Point.y] for v in outer_wire.OrderedVertexes],1e-7))
    holes = []
    marked = Part.makeCompound(selected_holes) if selected_holes else None
    for wire in cap.Wires:
        if wire.isSame(outer_wire) or marked is None:
            continue
        void = Part.Face(wire)
        if abs(void.common(marked).Area-void.Area) <= max(1e-6, void.Area*1e-7):
            holes.append(polygon(_close_duplicate([[v.Point.x,v.Point.y] for v in wire.OrderedVertexes],1e-7)))
    return outer, holes


def allowed_angles(part):
    return part.get('allowedAngles', [360*i/int(part.get('rotations', 1)) for i in range(int(part.get('rotations', 1)))])


def group_angles(parts, poses):
    candidates = [(a-poses[0][2]) % 360 for a in allowed_angles(parts[0])]
    policies = [{round(a % 360, 5) for a in allowed_angles(p)} for p in parts]
    return [a for a in candidates if all(round((a+pose[2]) % 360, 5) in policy
            or (round((a+pose[2]) % 360, 5) == 360 and 0 in policy)
            for pose, policy in zip(poses, policies))]


def pack_groups(parts, definitions, spacing, validate, preview_layouts=None):
    """Return ordinary engine parts and a separate, Python-only expansion recipe."""
    originals = {p['_ip_nesting']['preview_object_name']: p for p in parts}
    occupied = set(); replacements = {}; removed = set(); recipes = []
    for number, definition in enumerate(definitions):
        names = definition['names']
        if len(names) != len(set(names)) or occupied.intersection(names):
            raise ValueError('A part can belong to only one texture-matching group.')
        if any(name not in originals for name in names):
            raise ValueError('A texture-matching part was removed. Edit or remove its matching group.')
        members = [originals[name] for name in names]
        layout = (preview_layouts or {}).get(names[0])
        outlines = layout['outlines'] if layout else [polygon(p['points']) for p in members]
        if (len(outlines) != len(definition['outlines']) or
                any(len(a) != len(b) or any(math.dist(p, q) > 2e-5 for p, q in zip(a, b))
                    for a, b in zip(outlines, definition['outlines']))):
            raise ValueError('Texture-matching geometry changed. Reopen and confirm the group.')
        if len({p['quantity'] for p in members}) != 1:
            raise ValueError('All parts of a texture-matching group must have the same quantity.')
        if 'matching_edges' in definition:
            if len(definition['matching_edges']) != len(members):
                raise ValueError('Texture matching boundaries changed. Reopen the group.')
            members = [dict(p, matching_edges=boundary) for p, boundary in zip(members, definition['matching_edges'])]
        poses = layout['poses'] if layout else definition_poses(members, definition, spacing)
        validate(members, poses, spacing)
        if definition.get('grain') in ('X', 'Y'):
            # A grain-matched group is placed as one unit and may only be
            # flipped along its texture axis, so the envelope keeps 180-degree
            # symmetry rather than the individual parts' rotation rules.
            angles = [0.0, 180.0]
        elif definition.get('rotation_rule') is not None:
            angles = allowed_angles(definition['rotation_rule'])
        else:
            angles = group_angles(members, poses)
            if not angles:
                raise ValueError('The selected edges conflict with the parts\' rotation/texture rules.')
        transformed = [polygon(transform(p['points'], pose)) for p, pose in zip(members, poses)]
        transformed_holes = [[transform(h, pose) for h in (p.get('holes', []) or [])]
                             for p, pose in zip(members, poses)]
        outer, holes = outer_contour(transformed, transformed_holes)
        if len(outer) < 3:
            raise ValueError('The texture-matching group has no usable outer contour.')
        records = [dict(source_part_index=p['_ip_nesting']['source_part_index'], pose=pose,
                        points=p['points'], holes=p.get('holes', [])) for p, pose in zip(members, poses)]
        proxy_id = 'part_%d' % (len(parts)+number)
        metadata = dict(members[0]['_ip_nesting'])
        labels = [p['_ip_nesting'].get('label',p['_ip_nesting']['preview_object_name']) for p in members]
        source_types = {p['_ip_nesting'].get('source_type','unknown') for p in members}
        metadata.update(part_id=proxy_id,
                        label=definition.get('label', 'Texture matched parts: '+', '.join(labels)),
                        preview_object_name=names[0],
                        source_type=next(iter(source_types)) if len(source_types)==1 else 'mixed',
                        grain=definition.get('grain') or 'None',
                        instance_prefix=proxy_id+'_instance_')
        proxy = dict(id=proxy_id, points=outer, holes=holes,
                     quantity=members[0]['quantity'], allowedAngles=angles,
                     _ip_nesting=metadata)
        recipes.append(dict(id=proxy_id, members=records))
        first = min(i for i, p in enumerate(parts) if p['_ip_nesting']['preview_object_name'] in names)
        replacements[first] = proxy; removed.update(names); occupied.update(names)
    return ([replacements[i] if i in replacements else p for i, p in enumerate(parts)
             if i in replacements or p['_ip_nesting']['preview_object_name'] not in removed], recipes)


def expand_result(data, session):
    """Expand each rigid placement back into separately importable original parts."""
    result = copy.deepcopy(data)
    definitions = {p['id']: p for p in session.get('grain_matching_proxies', [])}
    if not definitions:
        return result
    source = {p['source_part_index']: p for p in session['parts']}
    changed = False; count = 0
    def members_for(part):
        key = str(part.get('source', part.get('id', '')))
        return definitions.get(key)
    for sheet in result.get('sheets', []):
        expanded = []
        for part in sheet.get('parts', []):
            group = members_for(part)
            if not group:
                expanded.append(part); continue
            changed = True
            for member in group['members']:
                i = member['source_part_index']; local = member['pose']
                offset = rotate(local[:2], part['rotation'])
                pose = [part['x']+offset[0], part['y']+offset[1], (part['rotation']+local[2]) % 360]
                expanded.append(dict(id='group_%s_%s' % (part['id'], i), source=source[i]['part_id'],
                    x=pose[0], y=pose[1], rotation=pose[2], points=transform(member['points'], pose),
                    holes=[transform(h, pose) for h in member['holes']],
                    _ip_nesting=dict(source_part_index=i)))
        sheet['parts'] = expanded; count += len(expanded)
    unplaced = []
    for part in result.get('unplaced', []):
        group = members_for(part)
        if group:
            changed = True
            for member in group['members']:
                i = member['source_part_index']
                unplaced.append(dict(part, source=source[i]['part_id'], points=member['points'],
                                     holes=member['holes'], _ip_nesting=dict(source_part_index=i)))
        else:
            unplaced.append(part)
    if changed:
        result['placed'] = count; result['unplaced'] = unplaced; result['unplacedCount'] = len(unplaced)
        def area(points):
            return abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(points, points[1:]+points[:1]))/2)
        material = sum(area(p['points'])-sum(area(h) for h in p.get('holes', []))
                       for s in result['sheets'] for p in s['parts'])
        stock = sum(area(s['points'])-sum(area(h) for h in s.get('holes', []))
                    for s in result['sheets'] if s['parts'])
        result['utilisation'] = 100*material/stock if stock else 0
        result['usedSheetWasteArea'] = stock-material
        # Engine offcut geometry is conservative because complete group envelopes
        # are reserved. Do not present its area as a measurement of expanded parts.
        result['grainMatchingEnvelopeReport'] = result.pop('reusableOffcut', None)
    return result
