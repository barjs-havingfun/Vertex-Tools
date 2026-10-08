bl_info = {
    "name": "Vertex Tools",
    "author": "Baris",
    "version": (3, 1, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Edit Mode > N Panel > Vertex Tools tab, Shift+Q menu, and Vertex / Mesh menus",
    "description": "Average Vertex: fix or extend a chain of vertices (line, curve, circle or average). "
                   "Draw With Vertex: click points, rectangles or circles to build faces or edges. "
                   "Face Projection: look straight at the plane of a selection",
    "category": "Mesh",
}

import math

import bpy
import bmesh
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector, geometry, kdtree


# ############################################################################
#
#   AVERAGE VERTEX
#
# ############################################################################

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def fit_line(pts):
    """Least-squares line through points. Returns (centroid, unit direction) or None."""
    arr = np.array([tuple(p) for p in pts], dtype=float)
    centroid = arr.mean(axis=0)
    _, s, vt = np.linalg.svd(arr - centroid, full_matrices=False)
    if s[0] < 1e-9:
        return None
    return Vector(centroid.tolist()), Vector(vt[0].tolist()).normalized()


class Circle:
    """A circle in 3D: center, two unit axes (u, v) spanning its plane, and radius."""

    def __init__(self, center, u, v, radius):
        self.center, self.u, self.v, self.radius = center, u, v, radius

    def angle(self, p):
        d = p - self.center
        return math.atan2(d.dot(self.v), d.dot(self.u))

    def at(self, theta):
        theta = float(theta)
        return self.center + (self.u * math.cos(theta) + self.v * math.sin(theta)) * self.radius


def fit_circle(pts):
    """Best-fit circle through 3D points (plane by SVD, then a least-squares circle in that plane)."""
    arr = np.array([tuple(p) for p in pts], dtype=float)
    c0 = arr.mean(axis=0)
    _, s, vt = np.linalg.svd(arr - c0, full_matrices=False)
    if s[0] < 1e-9 or s[1] < 1e-6 * s[0]:
        raise ValueError("The points are on one line, there is no circle to follow.")
    u, v = vt[0], vt[1]
    x, y = (arr - c0) @ u, (arr - c0) @ v
    # x^2 + y^2 + D x + E y + F = 0
    a = np.column_stack([x, y, np.ones_like(x)])
    (d, e, f), *_ = np.linalg.lstsq(a, -(x * x + y * y), rcond=None)
    cx, cy = -d / 2.0, -e / 2.0
    r2 = cx * cx + cy * cy - f
    if r2 <= 1e-18:
        raise ValueError("Could not fit a circle through the points.")
    center = c0 + cx * u + cy * v
    return Circle(Vector(center.tolist()), Vector(u.tolist()), Vector(v.tolist()), math.sqrt(r2))


def _closest_u(coefs, target, u0, u1):
    """Curve parameter in [u0, u1] whose point is closest to target (two-pass sampling)."""
    lo, hi = u0, u1
    best = u0
    for _ in range(2):
        uu = np.linspace(lo, hi, 200)
        curve = np.stack([np.polyval(c, uu) for c in coefs], axis=1)
        d2 = ((curve - target) ** 2).sum(axis=1)
        best = float(uu[int(d2.argmin())])
        step = (hi - lo) / 199.0
        lo, hi = max(u0, best - step), min(u1, best + step)
    return best


def _poly_curve(pts, degree):
    """Polynomial curve through ordered points. Returns (coefs per axis, u per point, degree used)."""
    n = len(pts)
    seg = [(pts[i + 1] - pts[i]).length for i in range(n - 1)]
    total = sum(seg)
    if total < 1e-9:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    # Curve parameter u: 0 at the first point, 1 at the last, proportional to chord length
    u = np.concatenate(([0.0], np.cumsum(seg))) / total
    arr = np.array([tuple(p) for p in pts], dtype=float)
    deg = max(1, min(int(degree), n - 1))
    return [np.polyfit(u, arr[:, k], deg) for k in range(3)], u, deg


def _eval_curve(coefs, u):
    return Vector([float(np.polyval(cf, u)) for cf in coefs])


def curve_fix(pts, target, degree, keep, scale):
    """
    Place `target` on the curve that runs through the reference points `pts`.

    pts     : list of Vector, reference points (world space), at least 3
    target  : Vector, current position of the point to fix
    degree  : polynomial degree of the curve (clamped to len(pts) - 1)
    keep    : True  -> keep the point where it is along the curve (only snap it onto the curve)
              False -> average length: one average spacing beyond an end,
                       or halfway between its two neighbors
    scale   : multiplier for the average spacing (only used when extending, keep=False)

    Returns (new_position, message). Raises ValueError for unusable input.
    """
    n = len(pts)
    if n < 3:
        raise ValueError("Curve mode needs at least 3 other vertices.")

    fit = fit_line(pts)
    if fit is None:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    c, d = fit

    # Order the reference points along the main direction of the chain
    ts = [(p - c).dot(d) for p in pts]
    idx = sorted(range(n), key=lambda i: ts[i])
    sp = [pts[i] for i in idx]
    st = [ts[i] for i in idx]

    coefs, u, deg = _poly_curve(sp, degree)

    tgt = np.array(tuple(target), dtype=float)
    du = 1.0 / (n - 1)  # average spacing in u units
    t_new = (target - c).dot(d)

    if t_new >= st[-1]:
        where = "beyond the end"
        if keep:
            u_new = _closest_u(coefs, tgt, 1.0 + 0.1 * du, 1.0 + 3.0 * du)
        else:
            u_new = 1.0 + du * scale
    elif t_new <= st[0]:
        where = "beyond the start"
        if keep:
            u_new = _closest_u(coefs, tgt, -3.0 * du, -0.1 * du)
        else:
            u_new = -du * scale
    else:
        where = "between its two neighbors"
        lo = max(i for i in range(n) if st[i] < t_new)
        hi = min(i for i in range(n) if st[i] > t_new)
        if keep:
            m = 0.1 * (u[hi] - u[lo])
            u_new = _closest_u(coefs, tgt, u[lo] + m, u[hi] - m)
        else:
            u_new = (u[lo] + u[hi]) / 2.0

    how = "stayed in place" if keep else "average length"
    return _eval_curve(coefs, u_new), f"Curve fix: {where}, {how}, degree {deg}"


def arc_fix(pts, target, keep, scale):
    """
    Place `target` on the circle that runs through the reference points `pts`.
    Same rules as curve_fix: beyond an end -> one average angle step further,
    between two points -> halfway between them (by angle), keep -> only snap onto the circle.
    """
    n = len(pts)
    if n < 3:
        raise ValueError("Circle mode needs at least 3 other vertices.")
    circ = fit_circle(pts)
    two_pi = 2.0 * math.pi

    # The reference points cover an arc: the biggest angle gap between them is the open part
    th = sorted(circ.angle(p) % two_pi for p in pts)
    gaps = [(th[(i + 1) % n] - th[i]) % two_pi for i in range(n)]
    g = max(range(n), key=lambda i: gaps[i])
    start = th[(g + 1) % n]
    rel = sorted((t - start) % two_pi for t in th)
    span = rel[-1]
    step = span / (n - 1)

    t_ang = circ.angle(target)
    tt = (t_ang - start) % two_pi
    if tt > span:
        beyond_end = (tt - span) < (two_pi - span) / 2.0
        where = "beyond the end" if beyond_end else "beyond the start"
        theta = start + span + step * scale if beyond_end else start - step * scale
    else:
        lo = max((r for r in rel if r < tt), default=0.0)
        hi = min((r for r in rel if r > tt), default=span)
        where = "between its two neighbors"
        theta = start + (lo + hi) / 2.0

    if keep:
        theta = t_ang
    how = "stayed in place" if keep else "average angle"
    return circ.at(theta), f"Circle fix: {where}, {how}, radius {circ.radius:.4f}"


def extrude_calc(pts_chrono, fit, degree, scale):
    """
    Compute where a NEW point should go, continuing the chain past the last
    (most recently selected) reference point.

    pts_chrono : list of Vector, reference points in chronological (selection) order,
                 oldest -> newest. The chain is extended past pts_chrono[-1].
    fit        : 'LINE' (needs >= 2 points), 'CURVE' or 'CIRCLE' (need >= 3 points)
    degree     : polynomial degree for curve mode
    scale      : multiplier for the average spacing

    Returns new_position (Vector). Raises ValueError for unusable input.
    """
    n = len(pts_chrono)

    if fit == 'CURVE':
        if n < 3:
            raise ValueError("Curve extrude needs at least 3 reference points.")
        coefs, _, _ = _poly_curve(pts_chrono, degree)
        return _eval_curve(coefs, 1.0 + scale / (n - 1))

    if fit == 'CIRCLE':
        if n < 3:
            raise ValueError("Circle extrude needs at least 3 reference points.")
        circ = fit_circle(pts_chrono)
        th = np.unwrap([circ.angle(p) for p in pts_chrono])
        step = (th[-1] - th[0]) / (n - 1)
        return circ.at(th[-1] + step * scale)

    if n < 2:
        raise ValueError("Line extrude needs at least 2 reference points.")
    line = fit_line(pts_chrono)
    if line is None:
        raise ValueError("The reference points are at the same location, no direction to follow.")
    c, d = line
    if d.dot(pts_chrono[-1] - pts_chrono[0]) < 0:
        d.negate()
    spacing = sum((pts_chrono[i + 1] - pts_chrono[i]).length for i in range(n - 1)) / (n - 1)
    anchor = c + d * (pts_chrono[-1] - c).dot(d)
    return anchor + d * spacing * scale


def chain_fix(pts, fit, degree, placement):
    """
    New positions for a whole chain of points, fitted to one line, curve or circle.

    pts       : list of Vector, the chain in order (world space), at least 3
    fit       : 'LINE', 'CURVE' (polynomial) or 'CIRCLE'
    degree    : polynomial degree for curve mode
    placement : 'AVERAGE' -> evenly spaced from the first to the last point
                'KEEP'    -> every point keeps its place along the fit, only snapped onto it
                'FULL'    -> circle only: evenly spaced around the whole circle

    Returns list of Vector (same order). Raises ValueError for unusable input.
    """
    n = len(pts)
    if n < 3:
        raise ValueError("Select at least 3 vertices for a chain.")

    if fit == 'CIRCLE':
        circ = fit_circle(pts)
        th = np.unwrap([circ.angle(p) for p in pts])
        if placement == 'KEEP':
            return [circ.at(t) for t in th]
        if placement == 'FULL':
            step = 2.0 * math.pi / n * (1.0 if th[-1] >= th[0] else -1.0)
            return [circ.at(th[0] + k * step) for k in range(n)]
        return [circ.at(t) for t in np.linspace(th[0], th[-1], n)]

    if fit == 'LINE':
        line = fit_line(pts)
        if line is None:
            raise ValueError("The selected points are at the same location, no direction to follow.")
        c, d = line
        proj = [c + d * (p - c).dot(d) for p in pts]
        if placement == 'KEEP':
            return proj
        return [proj[0].lerp(proj[-1], i / (n - 1)) for i in range(n)]

    coefs, u, _ = _poly_curve(pts, degree)
    arr = np.array([tuple(p) for p in pts], dtype=float)
    if placement == 'KEEP':
        du = 1.0 / (n - 1)
        u_new = [_closest_u(coefs, arr[i], u[i] - du / 2, u[i] + du / 2) for i in range(n)]
    else:
        # Equal arc length steps along the curve from u = 0 to u = 1
        uu = np.linspace(0.0, 1.0, 2001)
        curve_pts = np.stack([np.polyval(cf, uu) for cf in coefs], axis=1)
        cum = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(curve_pts, axis=0), axis=1))))
        u_new = np.interp(np.linspace(0.0, cum[-1], n), cum, uu)
    return [_eval_curve(coefs, ui) for ui in u_new]


def selected_chain(bm):
    """
    The selected vertices as an ordered chain: selection order when every vertex has one,
    otherwise followed along the selected edges (must be one open path).
    Returns list of BMVert, or None.
    """
    selected = [v for v in bm.verts if v.select]
    ordered = [
        e for e in bm.select_history
        if isinstance(e, bmesh.types.BMVert) and e.select
    ]
    if len(ordered) == len(selected):
        return ordered

    sel = set(selected)
    links = {v: [e.other_vert(v) for e in v.link_edges if e.other_vert(v) in sel] for v in selected}
    ends = [v for v in selected if len(links[v]) == 1]
    if len(ends) != 2 or any(len(nb) > 2 for nb in links.values()):
        return None

    chain, prev = [ends[0]], None
    while len(chain) < len(selected):
        nxt = [v for v in links[chain[-1]] if v is not prev]
        if not nxt:
            return None
        prev = chain[-1]
        chain.append(nxt[0])
    return chain


# ----------------------------------------------------------------------------
# Plans: what an action would do. Used by the buttons, the preview and Apply,
# so the preview always shows exactly what Apply does.
# ----------------------------------------------------------------------------

class Plan:
    def __init__(self, moves=(), extrude_from=None, extrude_pts=(), msg=""):
        self.moves = list(moves)              # [(BMVert, new world position)]
        self.extrude_from = extrude_from      # BMVert the new points continue from
        self.extrude_pts = list(extrude_pts)  # [world position] of new points, in order
        self.msg = msg


def plan_fix_last(bm, mw, mode, placement, degree, scale, window):
    """Move the last selected (active) vertex, using the other selected vertices."""
    active = bm.select_history.active
    if not isinstance(active, bmesh.types.BMVert) or not active.select:
        raise ValueError("No active vertex. Select vertices one by one (click), the last click is the target.")

    others_all = [v for v in bm.verts if v.select and v != active]
    if not others_all:
        raise ValueError("Select at least one other vertex besides the last one.")

    # Other selected vertices in selection order (oldest -> newest)
    history_others = [
        e for e in bm.select_history
        if isinstance(e, bmesh.types.BMVert) and e.select and e != active
    ]
    ordered_ok = len(history_others) == len(others_all)

    # Reference vertices (honor Window when selection order is available)
    note = ""
    if window > 0 and ordered_ok:
        used = history_others[-window:]
    else:
        used = others_all
        if window > 0:
            note = " (Window ignored: no selection order)"

    pts = [mw @ v.co for v in used]
    n = len(pts)
    target = mw @ active.co
    keep = placement == 'KEEP'

    # ---------- Mode: average position ----------
    if mode == 'CENTER':
        new_world = sum(pts, Vector()) / n
        msg = f"Moved to the average of {n} vertices"

    # ---------- Mode: curve fix ----------
    elif mode == 'CURVE':
        new_world, msg = curve_fix(pts, target, degree, keep, scale)

    # ---------- Mode: circle / arc fix ----------
    elif mode == 'CIRCLE':
        new_world, msg = arc_fix(pts, target, keep, scale)

    # ---------- Mode: smart (straight line) ----------
    else:
        if n < 2:
            raise ValueError("Smart mode needs at least 2 other vertices to define a line.")

        fit = fit_line(pts)
        if fit is None:
            raise ValueError("The selected points are at the same location, no direction to follow.")
        c, d = fit

        # Position of every reference point along the fitted line
        ts = [(p - c).dot(d) for p in pts]
        idx = sorted(range(n), key=lambda i: ts[i])
        sp = [pts[i] for i in idx]
        st = [ts[i] for i in idx]
        t_new = (target - c).dot(d)

        if keep:
            # Preserve the point's position along the line, only remove its
            # perpendicular offset (direction correction, no distance change).
            if t_new >= st[-1]:
                zone = "beyond the end"
            elif t_new <= st[0]:
                zone = "beyond the start"
            else:
                zone = "between its two neighbors"
            new_world = c + d * t_new
            msg = f"Snapped onto the line ({zone}), distance kept, direction corrected"
        else:
            spacing = sum((sp[i + 1] - sp[i]).length for i in range(n - 1)) / (n - 1)
            if t_new >= st[-1]:
                new_world = c + d * (st[-1] + spacing * scale)
                msg = f"Extended beyond the end, spacing = {spacing:.4f}"
            elif t_new <= st[0]:
                new_world = c + d * (st[0] - spacing * scale)
                msg = f"Extended beyond the start, spacing = {spacing:.4f}"
            else:
                lo = max(i for i in range(n) if st[i] < t_new)
                hi = min(i for i in range(n) if st[i] > t_new)
                new_world = (sp[lo] + sp[hi]) / 2
                gap = (sp[hi] - sp[lo]).length
                msg = f"Placed between its two neighbors (gap = {gap:.4f}, each side = {gap / 2:.4f})"

    return Plan(moves=[(active, new_world)], msg=msg + note)


def plan_chain(bm, mw, fit, degree, placement):
    """Move every vertex of the selected chain onto one line / curve / circle."""
    chain = selected_chain(bm)
    if chain is None:
        raise ValueError("Can't find the chain order. Click the vertices one by one, "
                         "or select one connected path of edges.")
    new = chain_fix([mw @ v.co for v in chain], fit, degree, placement)
    how = {'KEEP': "snapped", 'FULL': "spaced around the full circle"}.get(placement, "evenly spaced")
    return Plan(moves=zip(chain, new), msg=f"Fixed {len(chain)} vertices onto the {fit.lower()}, {how}")


def plan_extrude(bm, mw, fit, degree, scale, window, count):
    """New points continuing the chain past the last selected vertex."""
    selected = [v for v in bm.verts if v.select]
    if len(selected) < 2:
        raise ValueError("Select at least 2 vertices (3 for curve / circle), one by one (click), in order.")
    ordered = [
        e for e in bm.select_history
        if isinstance(e, bmesh.types.BMVert) and e.select
    ]
    if len(ordered) != len(selected):
        raise ValueError("Some selected vertices have no selection order. Select them one by one (click).")

    chain = [mw @ v.co for v in ordered]
    new = []
    for _ in range(max(1, count)):
        pts = chain + new
        new.append(extrude_calc(pts[-window:] if window > 0 else pts, fit, degree, scale))
    word = "point" if len(new) == 1 else "points"
    return Plan(extrude_from=ordered[-1], extrude_pts=new,
                msg=f"Extruded {len(new)} new {word} continuing the {fit.lower()}")


def plan_flatten(bm, mw):
    """Move every selected vertex onto the best-fit plane of the selection."""
    center, n, _ = selection_plane(bm, mw)
    verts = [v for v in bm.verts if v.select]
    moves = []
    for v in verts:
        p = mw @ v.co
        moves.append((v, p - n * (p - center).dot(n)))
    return Plan(moves=moves, msg=f"Flattened {len(verts)} vertices onto their plane")


def apply_plan(bm, mw, plan):
    mw_inv = mw.inverted()
    for v, p in plan.moves:
        v.co = mw_inv @ p
    last = plan.extrude_from
    for p in plan.extrude_pts:
        new_vert = bmesh.ops.extrude_vert_indiv(bm, verts=[last])['verts'][0]
        new_vert.co = mw_inv @ p
        new_vert.select = True
        bm.select_history.add(new_vert)
        last = new_vert


def _run_plan(op, context, make_plan):
    """Shared execute() body: build the plan, apply it, report."""
    obj = context.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    try:
        plan = make_plan(bm, obj.matrix_world)
    except ValueError as e:
        op.report({'ERROR'}, str(e))
        return {'CANCELLED'}
    apply_plan(bm, obj.matrix_world, plan)
    bmesh.update_edit_mesh(obj.data)
    op.report({'INFO'}, plan.msg)
    return {'FINISHED'}


# ----------------------------------------------------------------------------
# Shared operator properties
# ----------------------------------------------------------------------------

FIT_ITEMS = [
    ('LINE', "Line", "Fit a straight line"),
    ('CURVE', "Curve", "Fit a polynomial curve (arc / S-curve, see Curve Degree)"),
    ('CIRCLE', "Circle", "Fit a true circle (arcs, round shapes, bolt circles)"),
]

PLACEMENT_ITEMS = [
    ('AVERAGE', "Average / Even Spacing",
     "Even spacing: one average spacing beyond an end, halfway between neighbors, "
     "or (whole chain) evenly from the first to the last point"),
    ('KEEP', "Keep Distance (Direction Only)",
     "Keep the point's current position along the line/curve/circle, only snap it onto it"),
    ('FULL', "Full Circle",
     "Whole chain + Circle only: space the points evenly around the whole circle"),
]


def _degree_prop():
    return bpy.props.IntProperty(
        name="Curve Degree",
        description="Curve only: 1 = straight line, 2 = simple arc, 3 = S-shaped curve "
                    "(limited to number of points - 1)",
        default=2, min=1, max=5,
    )


def _scale_prop():
    return bpy.props.FloatProperty(
        name="Spacing Scale",
        description="Multiplier for the average spacing",
        default=1.0, min=0.0, soft_max=3.0,
    )


def _window_prop():
    return bpy.props.IntProperty(
        name="Window",
        description="Use only the last N selected points (in selection order) as reference. "
                    "0 = use all selected points",
        default=0, min=0, soft_max=20,
    )


def _count_prop():
    return bpy.props.IntProperty(
        name="Count",
        description="How many new points to add",
        default=1, min=1, soft_max=50,
    )


def _edit_mesh_poll(context):
    return context.mode == 'EDIT_MESH' and context.edit_object is not None


# ----------------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------------

class MESH_OT_move_last_to_average(bpy.types.Operator):
    """Last selected vertex is fixed based on the other selected vertices"""
    bl_idname = "mesh.move_last_to_average"
    bl_label = "Move Last Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('AUTO', "Smart (Line)",
             "Fit a straight line through the other points. Beyond an end -> extend the line, "
             "between two points -> put it in the middle of its neighbors"),
            ('CURVE', "Curve Fix",
             "Like Smart, but follows the curve of the other points (needs at least 3 of them)"),
            ('CIRCLE', "Circle Fix",
             "Like Smart, but follows the circle through the other points (needs at least 3 of them)"),
            ('CENTER', "Average Position",
             "Place the last vertex at the average position of the other points"),
        ],
        default='AUTO',
    )
    placement: bpy.props.EnumProperty(
        name="Placement",
        description="Where along the line/curve/circle the point ends up",
        items=PLACEMENT_ITEMS[:2],
        default='AVERAGE',
    )
    degree: _degree_prop()
    spacing_scale: _scale_prop()
    window: bpy.props.IntProperty(
        name="Window",
        description="Use only the last N points (before the target) in selection order. 0 = use all selected points. "
                    "Keep 0 when fixing a vertex in the middle of the chain",
        default=0, min=0, soft_max=20,
    )

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def execute(self, context):
        return _run_plan(self, context, lambda bm, mw: plan_fix_last(
            bm, mw, self.mode, self.placement, self.degree, self.spacing_scale, self.window))


class MESH_OT_extrude_average_chain(bpy.types.Operator):
    """Extrude new vertices that continue the selected chain (line, curve or circle)"""
    bl_idname = "mesh.extrude_average_chain"
    bl_label = "Extrude Chain Point"
    bl_options = {'REGISTER', 'UNDO'}

    fit: bpy.props.EnumProperty(name="Follow", items=FIT_ITEMS, default='LINE')
    degree: _degree_prop()
    spacing_scale: _scale_prop()
    window: _window_prop()
    count: _count_prop()

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def execute(self, context):
        return _run_plan(self, context, lambda bm, mw: plan_extrude(
            bm, mw, self.fit, self.degree, self.spacing_scale, self.window, self.count))


class MESH_OT_fix_vertex_chain(bpy.types.Operator):
    """Fit a line, curve or circle through the whole selected chain and move every vertex onto it"""
    bl_idname = "mesh.fix_vertex_chain"
    bl_label = "Fix Whole Chain"
    bl_options = {'REGISTER', 'UNDO'}

    fit: bpy.props.EnumProperty(name="Fit", items=FIT_ITEMS, default='LINE')
    degree: _degree_prop()
    placement: bpy.props.EnumProperty(name="Placement", items=PLACEMENT_ITEMS, default='AVERAGE')

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def execute(self, context):
        return _run_plan(self, context, lambda bm, mw: plan_chain(
            bm, mw, self.fit, self.degree, self.placement))


class MESH_OT_flatten_to_plane(bpy.types.Operator):
    """Move all selected vertices onto the best-fit plane of the selection"""
    bl_idname = "mesh.flatten_to_plane"
    bl_label = "Flatten to Plane"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def execute(self, context):
        return _run_plan(self, context, plan_flatten)


# ----------------------------------------------------------------------------
# Preview & Apply
# ----------------------------------------------------------------------------

def _tag_redraw_views(self=None, context=None):
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


ACTION_ITEMS = [
    ('FIX_SMART', "Fix Last: Line", "Fix the last clicked vertex using a straight line"),
    ('FIX_CURVE', "Fix Last: Curve", "Fix the last clicked vertex using a curve"),
    ('FIX_CIRCLE', "Fix Last: Circle", "Fix the last clicked vertex using a circle"),
    ('FIX_CENTER', "Fix Last: Move to Average", "Move the last clicked vertex to the average of the others"),
    ('CHAIN_LINE', "Whole Chain: Line", "Move the whole chain onto a straight line"),
    ('CHAIN_CURVE', "Whole Chain: Curve", "Move the whole chain onto a curve"),
    ('CHAIN_CIRCLE', "Whole Chain: Circle", "Move the whole chain onto a circle"),
    ('EXTRUDE_LINE', "Extrude: Line", "Add new points continuing the line"),
    ('EXTRUDE_CURVE', "Extrude: Curve", "Add new points continuing the curve"),
    ('EXTRUDE_CIRCLE', "Extrude: Circle", "Add new points continuing the circle"),
    ('FLATTEN', "Flatten to Plane", "Move all selected vertices onto their best-fit plane"),
]


class AverageVertexSettings(bpy.types.PropertyGroup):
    action: bpy.props.EnumProperty(name="Action", items=ACTION_ITEMS, default='CHAIN_LINE',
                                   update=_tag_redraw_views)
    placement: bpy.props.EnumProperty(name="Placement", items=PLACEMENT_ITEMS, default='AVERAGE',
                                      update=_tag_redraw_views)
    degree: bpy.props.IntProperty(name="Curve Degree", default=2, min=1, max=5,
                                  description="1 = straight line, 2 = simple arc, 3 = S-shaped curve",
                                  update=_tag_redraw_views)
    spacing_scale: bpy.props.FloatProperty(name="Spacing Scale", default=1.0, min=0.0, soft_max=3.0,
                                           description="Multiplier for the average spacing",
                                           update=_tag_redraw_views)
    window: bpy.props.IntProperty(name="Window", default=0, min=0, soft_max=20,
                                  description="Use only the last N selected points. 0 = all",
                                  update=_tag_redraw_views)
    count: bpy.props.IntProperty(name="Count", default=1, min=1, soft_max=50,
                                 description="Extrude: how many new points to add",
                                 update=_tag_redraw_views)


def plan_from_settings(bm, mw, st):
    kind, _, variant = st.action.partition('_')
    if kind == 'FIX':
        mode = {'SMART': 'AUTO', 'CURVE': 'CURVE', 'CIRCLE': 'CIRCLE', 'CENTER': 'CENTER'}[variant]
        return plan_fix_last(bm, mw, mode, st.placement, st.degree, st.spacing_scale, st.window)
    if kind == 'CHAIN':
        return plan_chain(bm, mw, variant, st.degree, st.placement)
    if kind == 'EXTRUDE':
        return plan_extrude(bm, mw, variant, st.degree, st.spacing_scale, st.window, st.count)
    return plan_flatten(bm, mw)


_preview = {"running": False, "handle": None, "error": ""}


def _preview_draw():
    context = bpy.context
    obj = context.edit_object
    if not _preview["running"] or obj is None or context.mode != 'EDIT_MESH':
        return
    mw = obj.matrix_world
    bm = bmesh.from_edit_mesh(obj.data)
    try:
        plan = plan_from_settings(bm, mw, context.scene.vertex_tools_avg)
        _preview["error"] = ""
    except ValueError as e:
        _preview["error"] = str(e)
        return

    shader = _uniform_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    ghost = (0.1, 0.9, 1.0, 1.0)

    if plan.moves:
        lines = []
        for v, p in plan.moves:
            lines += [mw @ v.co, p]
        gpu.state.line_width_set(1.5)
        _draw(shader, 'LINES', lines, (1.0, 1.0, 1.0, 0.45))
        gpu.state.point_size_set(9.0)
        _draw(shader, 'POINTS', [p for _, p in plan.moves], ghost)

    if plan.extrude_pts:
        strip = [mw @ plan.extrude_from.co] + plan.extrude_pts
        gpu.state.line_width_set(2.0)
        _draw(shader, 'LINE_STRIP', strip, (0.1, 0.9, 1.0, 0.6))
        gpu.state.point_size_set(9.0)
        _draw(shader, 'POINTS', plan.extrude_pts, ghost)

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


def _stop_preview():
    if _preview["handle"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_preview["handle"], 'WINDOW')
    _preview["handle"] = None
    _preview["running"] = False
    _preview["error"] = ""


def _region_under_mouse(context, event):
    for area in context.window.screen.areas:
        for region in area.regions:
            if (region.x <= event.mouse_x < region.x + region.width
                    and region.y <= event.mouse_y < region.y + region.height):
                return area, region
    return None, None


class MESH_OT_vertex_tools_preview(bpy.types.Operator):
    """Show ghost points where the vertices would go. Press again (Cancel), Esc, or click
    anywhere outside the sidebar to hide the preview"""
    bl_idname = "mesh.vertex_tools_preview"
    bl_label = "Preview"

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def invoke(self, context, event):
        if _preview["running"]:  # the button shows "Cancel" while previewing
            _stop_preview()
            _tag_redraw_views()
            return {'CANCELLED'}
        _preview["running"] = True
        _preview["handle"] = bpy.types.SpaceView3D.draw_handler_add(_preview_draw, (), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        _tag_redraw_views()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not _preview["running"]:  # stopped by Apply or the Cancel button
            return {'FINISHED'}
        if context.mode != 'EDIT_MESH' or (event.type == 'ESC' and event.value == 'PRESS'):
            _stop_preview()
            _tag_redraw_views()
            return {'CANCELLED'}

        if event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.value == 'PRESS':
            area, region = _region_under_mouse(context, event)
            in_sidebar = area is not None and area.type == 'VIEW_3D' and region.type == 'UI'
            if not in_sidebar:
                # Click anywhere else cancels the preview (and is used up, so nothing gets deselected)
                _stop_preview()
                _tag_redraw_views()
                return {'CANCELLED'}

        _tag_redraw_views()
        return {'PASS_THROUGH'}


class MESH_OT_vertex_tools_apply(bpy.types.Operator):
    """Apply the chosen action (exactly what the preview shows)"""
    bl_idname = "mesh.vertex_tools_apply"
    bl_label = "Apply"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _edit_mesh_poll(context)

    def execute(self, context):
        st = context.scene.vertex_tools_avg
        result = _run_plan(self, context, lambda bm, mw: plan_from_settings(bm, mw, st))
        if 'FINISHED' in result:
            _stop_preview()
            _tag_redraw_views()
        return result


# ############################################################################
#
#   DRAW WITH VERTEX
#
# ############################################################################

SNAP_RADIUS_PX = 12.0

AXES = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}

PLANE_ITEMS = (
    ('VIEW', "View", "Plane faces the camera exactly"),
    ('AUTO', "Nearest Axis", "World axis plane closest to the view direction"),
    ('SURFACE', "Surface", "Draw on the surface under the mouse (any visible object). "
                           "Rectangles and circles lie on the surface at the first click"),
    ('X', "X", "Lock to the plane perpendicular to X (YZ plane, side view)"),
    ('Y', "Y", "Lock to the plane perpendicular to Y (XZ plane, front view)"),
    ('Z', "Z", "Lock to the plane perpendicular to Z (XY plane, top view)"),
)

SHAPE_ITEMS = (
    ('POINTS', "Points", "Click points one by one"),
    ('RECT', "Rectangle", "Two clicks: opposite corners"),
    ('CIRCLE', "Circle", "Two clicks: center, then radius (see Sides, 6 = hexagon)"),
)

RESULT_ITEMS = (
    ('FACE', "Face", "Create a face"),
    ('EDGES', "Edges Only", "Create only vertices and edges: an open path, "
                            "or a closed loop when you click the first point (shapes are always closed)"),
)


# ---------------------------------------------------------------------------
# Settings (shown in the sidebar panel, toggled live with hotkeys while drawing)
# ---------------------------------------------------------------------------

class DrawWithVertexSettings(bpy.types.PropertyGroup):
    plane_mode: bpy.props.EnumProperty(
        name="Plane",
        description="Which plane the clicked points are placed on",
        items=PLANE_ITEMS,
        default='VIEW',
    )
    shape: bpy.props.EnumProperty(name="Shape", items=SHAPE_ITEMS, default='POINTS')
    sides: bpy.props.IntProperty(
        name="Sides",
        description="Number of sides of a circle (6 = hexagon). + / - while drawing",
        default=32, min=3, max=256,
    )
    result: bpy.props.EnumProperty(name="Result", items=RESULT_ITEMS, default='FACE')
    use_grid_snap: bpy.props.BoolProperty(
        name="Snap to Grid",
        description="Snap clicked points to a grid on the drawing plane",
        default=False,
    )
    grid_size: bpy.props.FloatProperty(
        name="Grid Size",
        description="Spacing of the snapping grid",
        default=0.25, min=0.0001, soft_max=10.0, unit='LENGTH',
    )
    use_vertex_snap: bpy.props.BoolProperty(
        name="Snap to Vertices",
        description="Snap to existing vertices",
        default=True,
    )
    use_edge_snap: bpy.props.BoolProperty(
        name="Snap to Edges",
        description="Snap onto existing edges (and their midpoints). With Merge on, the edge "
                    "is split there so the new face connects to it",
        default=True,
    )
    use_merge: bpy.props.BoolProperty(
        name="Merge",
        description="Points that sit on an existing vertex are merged with it, so the new face "
                    "is really connected to the mesh. Off = a separate vertex is created on top",
        default=True,
    )
    merge_distance: bpy.props.FloatProperty(
        name="Merge Distance",
        description="Points closer than this to an existing vertex are merged with it "
                    "(also catches grid / angle snapped points that land on a vertex)",
        default=0.001, min=0.0, soft_max=0.1, unit='LENGTH',
    )
    surface_offset: bpy.props.FloatProperty(
        name="Surface Offset",
        description="Surface plane: lift the drawn points this far off the surface",
        default=0.0, min=0.0, soft_max=0.1, unit='LENGTH',
    )
    angle_step: bpy.props.FloatProperty(
        name="Ctrl Angle Step",
        description="Angle increment used while holding Ctrl",
        default=math.radians(45.0), min=math.radians(1.0), max=math.radians(90.0),
        subtype='ANGLE',
    )
    show_fill: bpy.props.BoolProperty(
        name="Preview Fill",
        description="Show a filled preview of the face while drawing",
        default=True,
    )


def _settings(context):
    return context.scene.draw_with_vertex


def _dist_to_segment(p, a, b):
    t = geometry.intersect_point_line(p, a, b)[1]
    return (p - a.lerp(b, min(max(t, 0.0), 1.0))).length


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _uniform_shader():
    # Blender 4.x renamed the builtin shaders
    try:
        return gpu.shader.from_builtin('UNIFORM_COLOR')
    except ValueError:
        return gpu.shader.from_builtin('3D_UNIFORM_COLOR')


def _draw(shader, prim, coords, color, indices=None):
    batch = batch_for_shader(shader, prim, {"pos": coords}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_callback(op, context):
    s = _settings(context)
    outline, closing = op.preview_outline(s)
    pts = list(op.points)
    if not outline and not pts and op.hover is None:
        return

    shader = _uniform_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if len(outline) >= 3 and s.show_fill and s.result == 'FACE':
        try:
            tris = geometry.tessellate_polygon([outline])
            _draw(shader, 'TRIS', outline, (1.0, 0.6, 0.1, 0.18), indices=tris)
        except Exception:
            pass

    if len(outline) >= 2:
        gpu.state.line_width_set(2.0)
        _draw(shader, 'LINE_STRIP', outline, (1.0, 0.6, 0.1, 1.0))
    if len(outline) >= 3 and closing != 'NONE':
        closing_alpha = 1.0 if closing == 'SOLID' else 0.35
        _draw(shader, 'LINES', [outline[-1], outline[0]], (1.0, 0.6, 0.1, closing_alpha))

    # Highlight the edge the cursor is snapped to
    if op.hover is not None and op.hover_edge_co is not None:
        gpu.state.line_width_set(3.0)
        _draw(shader, 'LINES', list(op.hover_edge_co), (1.0, 0.3, 0.9, 1.0))

    if pts:
        gpu.state.point_size_set(8.0)
        _draw(shader, 'POINTS', pts, (1.0, 1.0, 1.0, 1.0))

    # Highlight the cursor point: blue = will merge with an existing vertex / edge,
    # green = snapped to something
    on_mesh = op.hover_vidx is not None or op.hover_edge is not None
    if op.hover is not None and on_mesh and s.use_merge:
        gpu.state.point_size_set(14.0)
        _draw(shader, 'POINTS', [op.hover], (0.2, 0.6, 1.0, 1.0))
    elif op.hover is not None and (op.hover_snapped or op.hover_on_surface):
        gpu.state.point_size_set(12.0)
        _draw(shader, 'POINTS', [op.hover], (0.2, 1.0, 0.4, 1.0))

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

def _keep_items(items):
    return (('KEEP', "Current", "Use the current setting"),) + tuple(items)


class MESH_OT_draw_face_by_points(bpy.types.Operator):
    """Click points, a rectangle or a circle on a plane or surface, then press Enter
    to create a face (or edges) from them"""
    bl_idname = "mesh.draw_face_by_points"
    bl_label = "Draw With Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    # Optional overrides (menu entries like "Draw Rectangle"); KEEP = use the panel setting
    shape: bpy.props.EnumProperty(items=_keep_items(SHAPE_ITEMS), default='KEEP',
                                  options={'HIDDEN', 'SKIP_SAVE'})
    plane: bpy.props.EnumProperty(items=_keep_items(PLANE_ITEMS), default='KEEP',
                                  options={'HIDDEN', 'SKIP_SAVE'})
    result: bpy.props.EnumProperty(items=_keep_items(RESULT_ITEMS), default='KEEP',
                                   options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.area is not None
                and context.area.type == 'VIEW_3D')

    # --- viewport ------------------------------------------------------------

    @staticmethod
    def _view_region(context, event):
        """The 3D viewport region to draw in: the one under the mouse, else the largest one.
        (When started from the sidebar or a menu, context.region is not the viewport.)"""
        best = None
        for r in context.area.regions:
            if r.type != 'WINDOW':
                continue
            if r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height:
                return r
            if best is None or r.width * r.height > best.width * best.height:
                best = r
        return best

    def _set_mouse(self, event):
        self.mouse = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)

    def _ray(self):
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, self.mouse)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, self.mouse)
        return origin, direction

    # --- plane ---------------------------------------------------------------

    def _setup_plane(self, context):
        mode = _settings(context).plane_mode
        view_rot = self.rv3d.view_rotation
        view_dir = view_rot @ Vector((0.0, 0.0, -1.0))

        if mode == 'AUTO':
            mode = max(AXES, key=lambda a: abs(view_dir.dot(AXES[a])))
        self.plane_label = mode

        # Plane goes through the first placed point, or the 3D cursor
        self.plane_co = self.points[0].copy() if self.points else context.scene.cursor.location.copy()

        if mode in AXES:
            self.plane_no = AXES[mode].copy()
            self.plane_u, self.plane_v = {
                'X': (AXES['Y'], AXES['Z']),
                'Y': (AXES['X'], AXES['Z']),
                'Z': (AXES['X'], AXES['Y']),
            }[mode]
            # Grid lines up with the world grid
            self.grid_origin = self._project(Vector((0.0, 0.0, 0.0)))
        else:
            n = view_dir
            if mode == 'SURFACE' and self.points and self.first_normal is not None:
                n = self.first_normal.copy()  # tangent plane at the first click
            if n.dot(view_dir) < 0.0:
                n.negate()  # keep the normal pointing away from the viewer
            u = view_rot @ Vector((1.0, 0.0, 0.0))
            u = u - n * u.dot(n)
            u = u.normalized() if u.length > 1e-6 else n.orthogonal().normalized()
            self.plane_no, self.plane_u, self.plane_v = n, u, u.cross(n)
            self.grid_origin = self.plane_co.copy()

        # Move already placed free points onto the new plane
        for i, p in enumerate(self.points):
            if not self.point_fixed[i]:
                self.points[i] = self._project(p)

    def _project(self, p):
        return p - self.plane_no * (p - self.plane_co).dot(self.plane_no)

    # --- shapes --------------------------------------------------------------

    def _shape_points(self, s, p0, p1):
        """Outline of a rectangle (corners p0, p1) or circle (center p0, radius point p1) on the plane."""
        a = self._project(p0)
        d = self._project(p1) - a
        du, dv = d.dot(self.plane_u), d.dot(self.plane_v)
        if s.shape == 'RECT':
            if abs(du) < 1e-9 or abs(dv) < 1e-9:
                raise ValueError("the rectangle has no area")
            u, v = self.plane_u * du, self.plane_v * dv
            return [a, a + u, a + u + v, a + v]
        r = math.hypot(du, dv)
        if r < 1e-9:
            raise ValueError("the circle has no radius")
        th0 = math.atan2(dv, du)
        n = s.sides
        return [a + (self.plane_u * math.cos(th0 + 2 * math.pi * k / n)
                     + self.plane_v * math.sin(th0 + 2 * math.pi * k / n)) * r for k in range(n)]

    def preview_outline(self, s):
        """(points to draw, closing line 'SOLID' / 'FAINT' / 'NONE') for the live preview."""
        if s.shape == 'POINTS':
            pts = list(self.points)
            if self.hover is not None and not self.hover_closes:
                pts.append(self.hover)
            if self.hover_closes:
                return pts, 'SOLID'
            return pts, ('FAINT' if s.result == 'FACE' else 'NONE')
        if self.points and self.hover is not None:
            try:
                return self._shape_points(s, self.points[0], self.hover), 'SOLID'
            except ValueError:
                pass
        return [], 'NONE'

    def _final_points(self, s):
        """(points, vertex indices, edge indices, closed) of what gets built."""
        if s.shape == 'POINTS':
            closed = s.result == 'FACE' or self.closed
            return list(self.points), list(self.point_vidx), list(self.point_edge), closed

        pts = self._shape_points(s, self.points[0], self.points[1])
        vidx, edge = [None] * len(pts), [None] * len(pts)
        # Clicked points that are real vertices: rectangle corners 0 and 2, circle point 0
        links = [(0, 0), (2, 1)] if s.shape == 'RECT' else [(0, 1)]
        for k, click in links:
            vidx[k], edge[k] = self.point_vidx[click], self.point_edge[click]
            if vidx[k] is not None or edge[k] is not None:
                pts[k] = self.points[click].copy()
        return pts, vidx, edge, True

    # --- snapping ------------------------------------------------------------

    def _mouse_to_plane(self):
        origin, direction = self._ray()
        return geometry.intersect_line_plane(
            origin, origin + direction, self.plane_co, self.plane_no)

    def _raycast(self, context):
        """(location, normal) of the surface under the mouse, or None."""
        origin, direction = self._ray()
        hit, loc, normal, *_ = context.scene.ray_cast(self.depsgraph, origin, direction)
        if not hit:
            return None
        if normal.dot(direction) > 0.0:
            normal = -normal  # the side facing the viewer
        return loc + normal * _settings(context).surface_offset, normal

    def _nearest_screen_point(self, candidates):
        """Return (index, world_co) of the candidate closest to the mouse within the snap radius."""
        mouse = Vector(self.mouse)
        best, best_d = None, SNAP_RADIUS_PX
        for key, co in candidates:
            p2d = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, co)
            if p2d is None:
                continue
            d = (p2d - mouse).length
            if d < best_d:
                best, best_d = (key, co), d
        return best

    def _nearest_edge(self):
        """Return (edge_index, (a, b), world_co) of the edge closest to the mouse within the
        snap radius, or None. Snaps to the edge midpoint when the mouse is near it."""
        region, rv3d = self.region, self.rv3d
        mouse2d = Vector(self.mouse)
        mouse = mouse2d.to_3d()
        best, best_d = None, SNAP_RADIUS_PX
        for key, a, b in self.mesh_edges:
            a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, a)
            b2d = view3d_utils.location_3d_to_region_2d(region, rv3d, b)
            if a2d is None or b2d is None or (a2d - b2d).length < 1e-6:
                continue
            closest, t = geometry.intersect_point_line(mouse, a2d.to_3d(), b2d.to_3d())
            if not 0.0 <= t <= 1.0:
                continue
            d = (closest - mouse).length
            if d < best_d:
                best, best_d = (key, a, b, t), d
        if best is None:
            return None

        key, a, b, t = best
        mid = (a + b) / 2
        mid2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mid)
        if mid2d is not None and (mid2d - mouse2d).length < SNAP_RADIUS_PX:
            return key, (a, b), mid

        # Exact 3D point on the edge under the mouse ray (screen t is off in perspective)
        origin, direction = self._ray()
        hit = geometry.intersect_line_line(origin, origin + direction, a, b)
        if hit is not None:
            t = geometry.intersect_point_line(hit[1], a, b)[1]
        return key, (a, b), a.lerp(b, min(max(t, 0.0), 1.0))

    def _snap_grid_2d(self, p, grid):
        d = p - self.grid_origin
        u = round(d.dot(self.plane_u) / grid) * grid
        v = round(d.dot(self.plane_v) / grid) * grid
        return self.grid_origin + self.plane_u * u + self.plane_v * v

    def _update_hover(self, context, ctrl):
        s = _settings(context)
        self.hover_vidx = None
        self.hover_edge = None
        self.hover_edge_co = None
        self.hover_normal = None
        self.hover_snapped = False
        self.hover_closes = False
        self.hover_on_surface = False

        # Clicking near the first point closes the shape
        if s.shape == 'POINTS' and len(self.points) >= 3:
            if self._nearest_screen_point([(0, self.points[0])]):
                self.hover = self.points[0]
                self.hover_snapped = True
                self.hover_closes = True
                return

        if s.use_vertex_snap:
            hit = self._nearest_screen_point(self.mesh_verts)
            if hit:
                self.hover_vidx, self.hover = hit
                self.hover_snapped = True
                return

        if s.use_edge_snap:
            hit = self._nearest_edge()
            if hit:
                self.hover_edge, self.hover_edge_co, self.hover = hit
                self.hover_snapped = True
                return

        p = None
        # Surface: every point for Points, the first click for shapes (the rest stays on its plane)
        if s.plane_mode == 'SURFACE' and (s.shape == 'POINTS' or not self.points):
            hit = self._raycast(context)
            if hit:
                p, self.hover_normal = hit
                self.hover_on_surface = True

        if p is None:
            p = self._mouse_to_plane()
            if p is None:
                self.hover = None
                return

            if ctrl and self.points:
                # Constrain direction from the last point to angle_step increments
                last = self._project(self.points[-1])
                d = p - last
                du, dv = d.dot(self.plane_u), d.dot(self.plane_v)
                step = s.angle_step
                ang = round(math.atan2(dv, du) / step) * step
                direction = self.plane_u * math.cos(ang) + self.plane_v * math.sin(ang)
                length = d.dot(direction)
                if s.use_grid_snap:
                    length = round(length / s.grid_size) * s.grid_size
                p = last + direction * length
                self.hover_snapped = True
            elif s.use_grid_snap:
                p = self._snap_grid_2d(p, s.grid_size)
                self.hover_snapped = True

        # A point that lands on an existing vertex (e.g. via grid snap) sits on it
        if self.mesh_verts:
            co, idx, dist = self.kd.find(p)
            if dist <= s.merge_distance:
                self.hover_vidx = self.mesh_verts[idx][0]
                p = co
                self.hover_snapped = True

        self.hover = p

    # --- UI ------------------------------------------------------------------

    def _update_header(self, context):
        s = _settings(context)
        on = lambda b: "ON" if b else "off"
        shape = {'POINTS': "Points", 'RECT': "Rectangle", 'CIRCLE': f"Circle ({s.sides} sides, +/-)"}[s.shape]
        result = "Face" if s.result == 'FACE' else "Edges"
        context.area.header_text_set(
            f"Draw {shape} -> {result}: {len(self.points)} pt | Plane: {self.plane_label} "
            f"[X/Y/Z lock, S surface, again = view] | R rect, C circle | P edges only: "
            f"{on(s.result == 'EDGES')} | G grid: {on(s.use_grid_snap)} | "
            f"V vertex: {on(s.use_vertex_snap)} | E edge: {on(s.use_edge_snap)} | "
            f"M merge: {on(s.use_merge)} | F fill: {on(s.show_fill)} | "
            "Ctrl: angle | LMB add | Backspace undo | Enter/RMB finish | Esc cancel")

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        context.area.header_text_set(None)
        context.area.tag_redraw()

    # --- modal ---------------------------------------------------------------

    def _clear_points(self):
        self.points, self.point_vidx, self.point_edge, self.point_fixed = [], [], [], []
        self.first_normal = None
        self.closed = False

    def invoke(self, context, event):
        s = _settings(context)
        if self.shape != 'KEEP':
            s.shape = self.shape
        if self.plane != 'KEEP':
            s.plane_mode = self.plane
        if self.result != 'KEEP':
            s.result = self.result

        self.region = self._view_region(context, event)
        if self.region is None:
            self.report({'ERROR'}, "No 3D viewport to draw in")
            return {'CANCELLED'}
        self.rv3d = self.region.data
        self.depsgraph = context.evaluated_depsgraph_get()

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world
        # Indices of freshly created verts (previous face, extrude) can be stale
        bm.verts.index_update()
        bm.edges.index_update()
        self.mesh_verts = [(v.index, mw @ v.co) for v in bm.verts if not v.hide]
        self.mesh_edges = [(e.index, mw @ e.verts[0].co, mw @ e.verts[1].co)
                           for e in bm.edges if not e.hide]

        self.kd = kdtree.KDTree(len(self.mesh_verts))
        for i, (_, co) in enumerate(self.mesh_verts):
            self.kd.insert(co, i)
        self.kd.balance()

        self._clear_points()
        self.hover = None
        self.hover_vidx = None
        self.hover_edge = None
        self.hover_edge_co = None
        self.hover_normal = None
        self.hover_snapped = False
        self.hover_closes = False
        self.hover_on_surface = False
        self._set_mouse(event)
        self._setup_plane(context)

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (self, context), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        self._update_header(context)
        return {'RUNNING_MODAL'}

    def _refresh(self, context, ctrl, replane=False):
        if replane:
            self._setup_plane(context)
        self._update_hover(context, ctrl)
        self._update_header(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        s = _settings(context)

        # Let the user orbit/pan/zoom while drawing (the plane stays fixed)
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                          'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            self._set_mouse(event)
            self._update_hover(context, event.ctrl)
            return {'RUNNING_MODAL'}

        # Pressing/releasing Ctrl should update the preview without moving the mouse
        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
            self._update_hover(context, event.value == 'PRESS')
            return {'RUNNING_MODAL'}

        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            self._set_mouse(event)
            self._update_hover(context, event.ctrl)
            if self.hover_closes:
                self.closed = True
                return self._complete(context)
            if self.hover is not None:
                if (s.use_merge and self.hover_vidx is not None
                        and self.hover_vidx in self.point_vidx):
                    self.report({'WARNING'}, "That vertex is already part of this shape")
                    return {'RUNNING_MODAL'}
                self.points.append(self.hover.copy())
                self.point_vidx.append(self.hover_vidx)
                self.point_edge.append(self.hover_edge)
                self.point_fixed.append(self.hover_vidx is not None or self.hover_edge is not None
                                        or self.hover_on_surface)
                if len(self.points) == 1:
                    self.first_normal = self.hover_normal
                    # Re-anchor the plane on the first point
                    self._setup_plane(context)
                if s.shape != 'POINTS' and len(self.points) == 2:
                    return self._complete(context)
                self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type == 'BACK_SPACE' or (event.type == 'Z' and event.ctrl):
            if self.points:
                for lst in (self.points, self.point_vidx, self.point_edge, self.point_fixed):
                    lst.pop()
                if not self.points:
                    self.first_normal = None
                    self._setup_plane(context)
                self._refresh(context, False)
            return {'RUNNING_MODAL'}

        if event.type in {'X', 'Y', 'Z', 'S'}:
            target = 'SURFACE' if event.type == 'S' else event.type
            s.plane_mode = 'VIEW' if s.plane_mode == target else target
            return self._refresh(context, event.ctrl, replane=True)

        if event.type in {'R', 'C'}:
            target = 'RECT' if event.type == 'R' else 'CIRCLE'
            s.shape = 'POINTS' if s.shape == target else target
            self._clear_points()
            return self._refresh(context, event.ctrl, replane=True)

        if event.type in {'NUMPAD_PLUS', 'EQUAL', 'NUMPAD_MINUS', 'MINUS'}:
            s.sides += 1 if event.type in {'NUMPAD_PLUS', 'EQUAL'} else -1
            return self._refresh(context, event.ctrl)

        toggles = {'G': "use_grid_snap", 'V': "use_vertex_snap", 'E': "use_edge_snap",
                   'M': "use_merge", 'F': "show_fill"}
        if event.type in toggles:
            setattr(s, toggles[event.type], not getattr(s, toggles[event.type]))
            return self._refresh(context, event.ctrl)
        if event.type == 'P':
            s.result = 'FACE' if s.result == 'EDGES' else 'EDGES'
            return self._refresh(context, event.ctrl)

        if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE', 'RIGHTMOUSE'}:
            return self._complete(context)

        if event.type == 'ESC':
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _complete(self, context):
        self._finish(context)
        s = _settings(context)
        if s.shape == 'POINTS':
            need = 3 if s.result == 'FACE' else 2
            if len(self.points) < need:
                self.report({'WARNING'}, f"Need at least {need} points")
                return {'CANCELLED'}
        elif len(self.points) < 2:
            self.report({'WARNING'}, "Click twice: first the start, then the size")
            return {'CANCELLED'}
        try:
            pts, vidx, edge, closed = self._final_points(s)
            self._build(context, pts, vidx, edge, closed, s.result == 'FACE')
        except ValueError as e:
            self.report({'ERROR'}, f"Could not create it: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

    def _build(self, context, points, point_vidx, point_edge, closed, as_face):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        to_local = obj.matrix_world.inverted()

        use_merge = _settings(context).use_merge
        if use_merge:
            merged = [i for i in point_vidx if i is not None]
            if len(merged) != len(set(merged)):
                raise ValueError("two points merge into the same vertex")

        # Look up the existing vertices and edges first: creating or splitting
        # invalidates the lookup tables
        verts = [bm.verts[vidx] if use_merge and vidx is not None else None
                 for vidx in point_vidx]
        edges = [bm.edges[eidx] if use_merge and eidx is not None else None
                 for eidx in point_edge]

        # Split snapped edges, so the new vertex is shared with the edge (and its faces)
        pieces = {}  # original edge -> its pieces after splitting (several points on one edge)
        for i, e in enumerate(edges):
            if e is None:
                continue
            co = to_local @ points[i]
            parts = pieces.setdefault(e, [e])
            part = min(parts, key=lambda pe: _dist_to_segment(co, pe.verts[0].co, pe.verts[1].co))
            v0 = part.verts[0]
            length = part.calc_length()
            fac = (co - v0.co).length / length if length > 0.0 else 0.5
            new_edge, new_vert = bmesh.utils.edge_split(part, v0, min(max(fac, 0.0), 1.0))
            new_vert.co = co
            parts.append(new_edge)
            verts[i] = new_vert

        for i, p in enumerate(points):
            if verts[i] is None:
                verts[i] = bm.verts.new(to_local @ p)

        for elem in (*bm.verts, *bm.edges, *bm.faces):
            elem.select = False

        if as_face:
            # Reuses existing edges between merged vertices, so the face is connected
            face = bm.faces.new(verts)
            face.normal_update()
            # Make the face point toward the viewer
            view_dir = self.rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            if face.normal.dot(to_local.to_3x3() @ -view_dir) < 0.0:
                face.normal_flip()
            face.select = True
        else:
            pairs = list(zip(verts, verts[1:]))
            if closed and len(verts) > 2:
                pairs.append((verts[-1], verts[0]))
            for a, b in pairs:
                e = bm.edges.get((a, b))
                if e is None:
                    e = bm.edges.new((a, b))
                e.select = True

        for v in verts:
            v.select = True
        bm.select_flush(True)
        bmesh.update_edit_mesh(me)


# ############################################################################
#
#   FACE PROJECTION
#
# ############################################################################

def selection_plane(bm, mw):
    """
    Plane of the selected elements in world space.

    Selected faces -> their (area weighted) normal.
    Otherwise      -> best-fit plane through the selected vertices
                      (3 vertices, 2 edges, or more).

    Returns (center, unit normal, from_faces). Raises ValueError for unusable input.
    """
    verts = [v for v in bm.verts if v.select]
    if len(verts) < 3:
        raise ValueError("Select 3 vertices, 2 edges or a face.")
    pts = [mw @ v.co for v in verts]
    center = sum(pts, Vector()) / len(pts)

    faces = [f for f in bm.faces if f.select]
    if faces:
        nmat = mw.inverted_safe().transposed().to_3x3()
        n = sum(((nmat @ f.normal).normalized() * f.calc_area() for f in faces), Vector())
        if n.length > 1e-9:
            return center, n.normalized(), True

    arr = np.array([tuple(p - center) for p in pts], dtype=float)
    _, s, vt = np.linalg.svd(arr, full_matrices=False)
    if s[0] < 1e-9 or s[1] < 1e-6 * s[0]:
        raise ValueError("The selected points are on one line, they don't define a plane.")
    return center, Vector(vt[2].tolist()).normalized(), False


# Views before each alignment, per viewport: {region_3d pointer: [(state, aligned rotation)]}
_view_history = {}


def _view_state(rv3d):
    return (rv3d.view_rotation.copy(), rv3d.view_location.copy(),
            rv3d.view_distance, rv3d.view_perspective)


class VIEW3D_OT_align_view_to_selection(bpy.types.Operator):
    """Look straight at the plane of the selection (3 vertices, 2 edges or a face)"""
    bl_idname = "view3d.align_view_to_selection"
    bl_label = "Align View to Selection"
    bl_options = {'REGISTER', 'UNDO'}

    roll: bpy.props.EnumProperty(
        name="Roll",
        description="How the view is turned around the viewing direction",
        items=[
            ('WORLD', "World Up",
             "World Z points up on screen, like the Front / Side views "
             "(flat planes: world Y up, like the Top view)"),
            ('EDGE', "Edge Horizontal",
             "The first two clicked vertices (or the longest selected edge) lie horizontal on screen"),
            ('VIEW', "Keep Current",
             "Keep the current screen up direction as much as possible"),
        ],
        default='WORLD',
    )
    flip: bpy.props.BoolProperty(
        name="Flip",
        description="Look at the plane from the other side",
        default=False,
    )
    center: bpy.props.BoolProperty(
        name="Center View",
        description="Center the view on the selection",
        default=True,
    )
    ortho: bpy.props.BoolProperty(
        name="Orthographic",
        description="Switch to an orthographic view (true projection, no perspective)",
        default=True,
    )
    set_cursor: bpy.props.BoolProperty(
        name="Move 3D Cursor",
        description="Move the 3D cursor to the selection and rotate it to the plane. "
                    "Draw With Vertex (View plane) then draws exactly on this plane",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.space_data is not None
                and context.space_data.type == 'VIEW_3D')

    def _screen_axes(self, bm, mw, n, rv3d):
        """Screen right (x) and up (y) directions on the plane with normal n, from the Roll option."""
        def on_plane(d):
            d = d - n * d.dot(n)
            return d.normalized() if d.length > 1e-3 else None

        world_up = on_plane(Vector((0.0, 0.0, 1.0)))
        if world_up is None:  # flat plane: like the Top view, world Y up
            world_up = on_plane(Vector((0.0, 1.0, 0.0)))

        if self.roll == 'EDGE':
            clicked = [e for e in bm.select_history if isinstance(e, bmesh.types.BMVert) and e.select]
            edges = [e for e in bm.edges if e.select]
            x = None
            if len(clicked) >= 2:
                x = on_plane(mw @ clicked[1].co - mw @ clicked[0].co)
            elif edges:
                v0, v1 = max(edges, key=lambda e: e.calc_length()).verts
                x = on_plane(mw @ v1.co - mw @ v0.co)
            if x is not None:
                y = n.cross(x)
                # Keep it upright: don't let the world end up upside down
                if world_up is not None and y.dot(world_up) < 0.0:
                    x, y = -x, -y
                return x, y

        y = None
        if self.roll == 'VIEW':
            y = on_plane(rv3d.view_rotation @ Vector((0.0, 1.0, 0.0)))
        if y is None:
            y = world_up
        return y.cross(n), y

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        rv3d = context.space_data.region_3d  # also works from the sidebar

        try:
            center, n, from_faces = selection_plane(bm, obj.matrix_world)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Remember the view to go back to. Changing an option in the redo panel runs this
        # again on our own result: then keep the original "before" view.
        history = _view_history.setdefault(rv3d.as_pointer(), [])
        if not (history and history[-1][1].rotation_difference(rv3d.view_rotation).angle < 1e-4):
            history.append((_view_state(rv3d), None))
            del history[:-20]
        before = history[-1][0]

        # Faces: look at their front. Vertices / edges: stay on the side we looked from before
        toward_viewer = before[0] @ Vector((0.0, 0.0, 1.0))
        if not from_faces and n.dot(toward_viewer) < 0.0:
            n = -n
        if self.flip:
            n = -n

        rot = Matrix((*self._screen_axes(bm, obj.matrix_world, n, rv3d), n)).transposed().to_quaternion()

        if rv3d.view_perspective == 'CAMERA':
            rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = rot
        if self.center:
            rv3d.view_location = center
        if self.ortho:
            rv3d.view_perspective = 'ORTHO'
        history[-1] = (before, rot.copy())

        if self.set_cursor:
            m = rot.to_matrix().to_4x4()
            m.translation = center
            context.scene.cursor.matrix = m

        what = "faces" if from_faces else "vertices"
        self.report({'INFO'}, f"View aligned to the plane of the selected {what}")
        return {'FINISHED'}


class VIEW3D_OT_vertex_tools_view_back(bpy.types.Operator):
    """Go back to the view you had before aligning"""
    bl_idname = "view3d.vertex_tools_view_back"
    bl_label = "Back to Previous View"

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return (sd is not None and sd.type == 'VIEW_3D'
                and bool(_view_history.get(sd.region_3d.as_pointer())))

    def execute(self, context):
        rv3d = context.space_data.region_3d
        (rot, loc, dist, persp), _ = _view_history[rv3d.as_pointer()].pop()
        rv3d.view_perspective = persp
        rv3d.view_rotation = rot
        rv3d.view_location = loc
        rv3d.view_distance = dist
        return {'FINISHED'}


class VIEW3D_OT_align_and_draw(bpy.types.Operator):
    """Align the view to the selection, put the 3D cursor on its plane, and start drawing on it"""
    bl_idname = "view3d.align_and_draw"
    bl_label = "Align + Draw"

    @classmethod
    def poll(cls, context):
        return VIEW3D_OT_align_view_to_selection.poll(context)

    def invoke(self, context, event):
        if 'FINISHED' not in bpy.ops.view3d.align_view_to_selection(set_cursor=True):
            return {'CANCELLED'}
        _settings(context).plane_mode = 'VIEW'
        bpy.ops.mesh.draw_face_by_points('INVOKE_DEFAULT')
        return {'FINISHED'}


# ############################################################################
#
#   UI: N Panel > Vertex Tools tab, and the Shift+Q menu
#
# ############################################################################

class _VertexToolsPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Vertex Tools"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'


def _op(layout, idname, text, icon='NONE', **props):
    op = layout.operator(idname, text=text, icon=icon)
    for k, v in props.items():
        setattr(op, k, v)
    return op


def _labeled_row(layout, label, factor=0.27):
    """A row with a short label on the left and the buttons side by side on the right."""
    split = layout.split(factor=factor, align=True)
    split.alignment = 'RIGHT'
    split.label(text=label)
    return split.row(align=True)


class VIEW3D_PT_average_vertex(_VertexToolsPanel, bpy.types.Panel):
    bl_label = "Average Vertex"

    def draw(self, context):
        layout = self.layout
        fix_id = MESH_OT_move_last_to_average.bl_idname
        chain_id = MESH_OT_fix_vertex_chain.bl_idname
        extrude_id = MESH_OT_extrude_average_chain.bl_idname

        layout.label(text="Fix Selected Vertex:")
        col = layout.column(align=True)
        _op(col, fix_id, "Smart: Average Distance", 'MODIFIER', mode='AUTO', placement='AVERAGE')
        _op(col, fix_id, "Smart: Keep Distance", 'SNAP_NORMAL', mode='AUTO', placement='KEEP')
        col = layout.column(align=True)
        _op(col, fix_id, "Curve: Average Distance", 'CURVE_DATA', mode='CURVE', placement='AVERAGE')
        _op(col, fix_id, "Curve: Keep Distance", 'PINNED', mode='CURVE', placement='KEEP')
        col = layout.column(align=True)
        _op(col, fix_id, "Circle: Average Distance", 'MESH_CIRCLE', mode='CIRCLE', placement='AVERAGE')
        _op(col, fix_id, "Circle: Keep Distance", 'PROP_CON', mode='CIRCLE', placement='KEEP')
        _op(layout, fix_id, "Move to Average", 'SNAP_MIDPOINT', mode='CENTER')

        layout.separator()
        layout.label(text="Fix Whole Chain:")
        col = layout.column(align=True)
        _op(col, chain_id, "Chain: Even Along Line", 'IPO_LINEAR', fit='LINE')
        _op(col, chain_id, "Chain: Even Along Curve", 'IPO_BEZIER', fit='CURVE')
        _op(col, chain_id, "Chain: Even Along Arc", 'IPO_CIRC', fit='CIRCLE')
        _op(col, chain_id, "Chain: Full Circle", 'MESH_CIRCLE', fit='CIRCLE', placement='FULL')

        layout.separator()
        layout.label(text="Extrude New Vertex:")
        col = layout.column(align=True)
        _op(col, extrude_id, "Extrude Along Line", 'FORWARD', fit='LINE')
        _op(col, extrude_id, "Extrude Along Curve", 'SPHERECURVE', fit='CURVE')
        _op(col, extrude_id, "Extrude Along Circle", 'MESH_CIRCLE', fit='CIRCLE')


class VIEW3D_PT_average_vertex_preview(_VertexToolsPanel, bpy.types.Panel):
    bl_label = "Preview & Apply"
    bl_parent_id = "VIEW3D_PT_average_vertex"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(icon='HIDE_OFF' if _preview["running"] else 'HIDE_ON')

    def draw(self, context):
        layout = self.layout
        st = context.scene.vertex_tools_avg
        layout.prop(st, "action", text="")

        kind, _, variant = st.action.partition('_')
        col = layout.column(align=True)
        if kind in {'FIX', 'CHAIN'} and variant != 'CENTER':
            col.prop(st, "placement", text="")
        if variant == 'CURVE':
            col.prop(st, "degree")
        if (kind == 'FIX' and variant != 'CENTER' and st.placement != 'KEEP') or kind == 'EXTRUDE':
            col.prop(st, "spacing_scale")
        if kind in {'FIX', 'EXTRUDE'}:
            col.prop(st, "window")
        if kind == 'EXTRUDE':
            col.prop(st, "count")

        row = layout.row(align=True)
        row.scale_y = 1.3
        if _preview["running"]:
            row.operator(MESH_OT_vertex_tools_preview.bl_idname, text="Cancel", icon='CANCEL')
        else:
            row.operator(MESH_OT_vertex_tools_preview.bl_idname, text="Preview", icon='HIDE_OFF')
        row.operator(MESH_OT_vertex_tools_apply.bl_idname, text="Apply", icon='CHECKMARK')
        if _preview["running"] and _preview["error"]:
            layout.label(text=_preview["error"], icon='ERROR')


class VIEW3D_PT_draw_with_vertex(_VertexToolsPanel, bpy.types.Panel):
    bl_label = "Draw With Vertex"

    def draw(self, context):
        s = _settings(context)
        layout = self.layout
        row = layout.row()
        row.scale_y = 1.3
        row.operator(MESH_OT_draw_face_by_points.bl_idname, text="Draw", icon='GREASEPENCIL')

        layout.label(text="Shape:")
        row = layout.row(align=True)
        row.prop(s, "shape", expand=True)
        if s.shape == 'CIRCLE':
            layout.prop(s, "sides")
        row = layout.row(align=True)
        row.prop(s, "result", expand=True)

        layout.label(text="Plane:")
        col = layout.column(align=True)
        row = col.row(align=True)
        for item in ('VIEW', 'AUTO', 'SURFACE'):
            row.prop_enum(s, "plane_mode", item)
        row = col.row(align=True)
        for item in ('X', 'Y', 'Z'):
            row.prop_enum(s, "plane_mode", item)
        if s.plane_mode == 'SURFACE':
            layout.prop(s, "surface_offset")

        # Snapping toggles as one compact icon row (hover for the name)
        row = _labeled_row(layout, "Snap")
        row.prop(s, "use_grid_snap", text="", icon='SNAP_GRID')
        row.prop(s, "use_vertex_snap", text="", icon='SNAP_VERTEX')
        row.prop(s, "use_edge_snap", text="", icon='SNAP_EDGE')
        row.prop(s, "use_merge", text="", icon='AUTOMERGE_ON' if s.use_merge else 'AUTOMERGE_OFF')
        row.separator()
        row.prop(s, "show_fill", text="", icon='SHADING_SOLID')

        col = layout.column(align=True)
        sub = col.row(align=True)
        sub.active = s.use_grid_snap
        sub.prop(s, "grid_size")
        sub = col.row(align=True)
        sub.active = s.use_merge
        sub.prop(s, "merge_distance")
        col.prop(s, "angle_step")

        layout.label(text="Plane passes through the 3D cursor", icon='INFO')


class VIEW3D_PT_face_projection(_VertexToolsPanel, bpy.types.Panel):
    bl_label = "Face Projection"

    def draw(self, context):
        layout = self.layout
        align_id = VIEW3D_OT_align_view_to_selection.bl_idname

        layout.label(text="3 vertices, 2 edges or a face:")
        col = layout.column(align=True)
        _op(col, align_id, "Align View to Selection", 'VIEW_ORTHO', set_cursor=False)
        _op(col, align_id, "Align View + Cursor", 'PIVOT_CURSOR', set_cursor=True)
        col.operator(VIEW3D_OT_align_and_draw.bl_idname, text="Align + Draw", icon='GREASEPENCIL')
        layout.operator(VIEW3D_OT_vertex_tools_view_back.bl_idname, icon='LOOP_BACK')
        layout.separator()
        layout.operator(MESH_OT_flatten_to_plane.bl_idname, icon='MESH_PLANE')


class VIEW3D_MT_vertex_tools(bpy.types.Menu):
    bl_label = "Vertex Tools"
    bl_idname = "VIEW3D_MT_vertex_tools"

    def draw(self, context):
        fix_id = MESH_OT_move_last_to_average.bl_idname
        chain_id = MESH_OT_fix_vertex_chain.bl_idname
        extrude_id = MESH_OT_extrude_average_chain.bl_idname
        draw_id = MESH_OT_draw_face_by_points.bl_idname
        align_id = VIEW3D_OT_align_view_to_selection.bl_idname

        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        row = layout.row()

        col = row.column()
        col.label(text="Average Vertex", icon='MODIFIER')
        _op(col, fix_id, "Fix Last: Line", mode='AUTO', placement='AVERAGE')
        _op(col, fix_id, "Fix Last: Line, Keep Distance", mode='AUTO', placement='KEEP')
        _op(col, fix_id, "Fix Last: Curve", mode='CURVE', placement='AVERAGE')
        _op(col, fix_id, "Fix Last: Circle", mode='CIRCLE', placement='AVERAGE')
        _op(col, fix_id, "Fix Last: Move to Average", mode='CENTER')
        col.separator()
        _op(col, chain_id, "Chain: Even Along Line", fit='LINE')
        _op(col, chain_id, "Chain: Even Along Curve", fit='CURVE')
        _op(col, chain_id, "Chain: Even Along Arc", fit='CIRCLE')
        _op(col, chain_id, "Chain: Full Circle", fit='CIRCLE', placement='FULL')
        col.separator()
        _op(col, extrude_id, "Extrude Along Line", fit='LINE')
        _op(col, extrude_id, "Extrude Along Curve", fit='CURVE')
        _op(col, extrude_id, "Extrude Along Circle", fit='CIRCLE')
        col.separator()
        col.operator(MESH_OT_vertex_tools_preview.bl_idname,
                     text="Cancel Preview" if _preview["running"] else "Preview (panel action)",
                     icon='HIDE_OFF')
        col.operator(MESH_OT_vertex_tools_apply.bl_idname, text="Apply (panel action)", icon='CHECKMARK')

        col = row.column()
        col.label(text="Draw With Vertex", icon='GREASEPENCIL')
        _op(col, draw_id, "Draw Points", shape='POINTS', result='FACE')
        _op(col, draw_id, "Draw Rectangle", shape='RECT')
        _op(col, draw_id, "Draw Circle", shape='CIRCLE')
        _op(col, draw_id, "Draw Edges Only (Path)", shape='POINTS', result='EDGES')
        _op(col, draw_id, "Draw on Surface", plane='SURFACE')

        col = row.column()
        col.label(text="Face Projection", icon='VIEW_ORTHO')
        _op(col, align_id, "Align View to Selection", set_cursor=False)
        _op(col, align_id, "Align View + Cursor", set_cursor=True)
        col.operator(VIEW3D_OT_align_and_draw.bl_idname, text="Align + Draw")
        col.operator(VIEW3D_OT_vertex_tools_view_back.bl_idname)
        col.separator()
        col.operator(MESH_OT_flatten_to_plane.bl_idname)


def average_vertex_menu_func(self, context):
    self.layout.separator()
    self.layout.menu(VIEW3D_MT_vertex_tools.bl_idname, icon='MODIFIER')


def draw_with_vertex_menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MESH_OT_draw_face_by_points.bl_idname, icon='GREASEPENCIL')


# ############################################################################
#
#   Registration
#
# ############################################################################

classes = (
    MESH_OT_move_last_to_average,
    MESH_OT_extrude_average_chain,
    MESH_OT_fix_vertex_chain,
    MESH_OT_flatten_to_plane,
    AverageVertexSettings,
    MESH_OT_vertex_tools_preview,
    MESH_OT_vertex_tools_apply,
    DrawWithVertexSettings,
    MESH_OT_draw_face_by_points,
    VIEW3D_OT_align_view_to_selection,
    VIEW3D_OT_vertex_tools_view_back,
    VIEW3D_OT_align_and_draw,
    VIEW3D_PT_average_vertex,
    VIEW3D_PT_average_vertex_preview,
    VIEW3D_PT_draw_with_vertex,
    VIEW3D_PT_face_projection,
    VIEW3D_MT_vertex_tools,
)

addon_keymaps = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.draw_with_vertex = bpy.props.PointerProperty(type=DrawWithVertexSettings)
    bpy.types.Scene.vertex_tools_avg = bpy.props.PointerProperty(type=AverageVertexSettings)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.append(average_vertex_menu_func)
    bpy.types.VIEW3D_MT_edit_mesh.append(draw_with_vertex_menu_func)

    # Shift+Q in Edit Mode opens the Vertex Tools menu (change it in Preferences > Keymap)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Mesh", space_type='EMPTY')
        kmi = km.keymap_items.new("wm.call_menu", 'Q', 'PRESS', shift=True)
        kmi.properties.name = VIEW3D_MT_vertex_tools.bl_idname
        addon_keymaps.append((km, kmi))


def unregister():
    _stop_preview()
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.types.VIEW3D_MT_edit_mesh.remove(draw_with_vertex_menu_func)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(average_vertex_menu_func)
    del bpy.types.Scene.vertex_tools_avg
    del bpy.types.Scene.draw_with_vertex
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
