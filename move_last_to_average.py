bl_info = {
    "name": "Move Last Vertex to Average",
    "author": "Baris",
    "version": (1, 6, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Edit Mode > N Panel > Tool, and Vertex menu",
    "description": "Fixes the last selected vertex using the other selected vertices (line, curve or average), "
                   "and extrudes a new vertex continuing the chain",
    "category": "Mesh",
}

import bpy
import bmesh
import numpy as np
from mathutils import Vector


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

    # Curve parameter u: 0 at the first point, 1 at the last, proportional to chord length
    seg = [(sp[i + 1] - sp[i]).length for i in range(n - 1)]
    total = sum(seg)
    if total < 1e-9:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    u = np.concatenate(([0.0], np.cumsum(seg))) / total

    # Polynomial curve P(u), one polynomial per coordinate
    arr = np.array([tuple(p) for p in sp], dtype=float)
    deg = max(1, min(int(degree), n - 1))
    coefs = [np.polyfit(u, arr[:, k], deg) for k in range(3)]

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

    new = Vector([float(np.polyval(cf, u_new)) for cf in coefs])
    how = "stayed in place" if keep else "average length"
    return new, f"Curve fix: {where}, {how}, degree {deg}"


def extrude_calc(pts_chrono, curve, degree, scale):
    """
    Compute where a NEW point should go, continuing the chain past the last
    (most recently selected) reference point.

    pts_chrono : list of Vector, reference points in chronological (selection) order,
                 oldest -> newest. The chain is extended past pts_chrono[-1].
    curve      : True -> follow the fitted curve (needs >= 3 points)
                 False -> follow the fitted straight line (needs >= 2 points)
    degree     : polynomial degree for curve mode
    scale      : multiplier for the average spacing

    Returns new_position (Vector). Raises ValueError for unusable input.
    """
    n = len(pts_chrono)

    if curve:
        if n < 3:
            raise ValueError("Curve extrude needs at least 3 reference points.")
        seg = [(pts_chrono[i + 1] - pts_chrono[i]).length for i in range(n - 1)]
        total = sum(seg)
        if total < 1e-9:
            raise ValueError("The reference points are at the same location, no curve to follow.")
        u = np.concatenate(([0.0], np.cumsum(seg))) / total
        arr = np.array([tuple(p) for p in pts_chrono], dtype=float)
        deg = max(1, min(int(degree), n - 1))
        coefs = [np.polyfit(u, arr[:, k], deg) for k in range(3)]
        du = 1.0 / (n - 1)
        u_new = 1.0 + du * scale
        return Vector([float(np.polyval(cf, u_new)) for cf in coefs])

    else:
        if n < 2:
            raise ValueError("Line extrude needs at least 2 reference points.")
        fit = fit_line(pts_chrono)
        if fit is None:
            raise ValueError("The reference points are at the same location, no direction to follow.")
        c, d = fit
        if d.dot(pts_chrono[-1] - pts_chrono[0]) < 0:
            d.negate()
        spacing = sum((pts_chrono[i + 1] - pts_chrono[i]).length for i in range(n - 1)) / (n - 1)
        anchor = c + d * (pts_chrono[-1] - c).dot(d)
        return anchor + d * spacing * scale


# ----------------------------------------------------------------------------
# Operator: fix the last selected vertex
# ----------------------------------------------------------------------------

class MESH_OT_move_last_to_average(bpy.types.Operator):
    """Last selected vertex is fixed based on the other selected vertices"""
    bl_idname = "mesh.move_last_to_average"
    bl_label = "Move Last Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('AUTO', "Smart (Auto)",
             "Fit a straight line through the other points. Beyond an end -> extend the line, "
             "between two points -> put it in the middle of its neighbors"),
            ('CURVE', "Curve Fix",
             "Like Smart, but follows the curve of the other points (needs at least 3 of them)"),
            ('CENTER', "Average Position",
             "Place the last vertex at the average position of the other points"),
        ],
        default='AUTO',
    )
    placement: bpy.props.EnumProperty(
        name="Placement",
        description="Smart and Curve Fix only: where along the line/curve the point ends up",
        items=[
            ('AVERAGE', "Average Distance",
             "Even spacing: one average spacing beyond an end, or halfway between its two neighbors"),
            ('KEEP', "Keep Distance (Direction Only)",
             "Keep the point's current position along the line/curve, only correct its direction "
             "by snapping it onto the line/curve"),
        ],
        default='AVERAGE',
    )
    degree: bpy.props.IntProperty(
        name="Curve Degree",
        description="Curve Fix only: 1 = straight line, 2 = simple arc, 3 = S-shaped curve "
                    "(limited to number of points - 1)",
        default=2,
        min=1,
        max=5,
    )
    spacing_scale: bpy.props.FloatProperty(
        name="Spacing Scale",
        description="Multiplier for the average spacing (Average Distance placement only)",
        default=1.0,
        min=0.0,
        soft_max=3.0,
    )
    window: bpy.props.IntProperty(
        name="Window",
        description="Use only the last N points (before the target) in selection order. 0 = use all selected points. "
                    "Keep 0 when fixing a vertex in the middle of the chain",
        default=0,
        min=0,
        soft_max=20,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world

        active = bm.select_history.active
        if not isinstance(active, bmesh.types.BMVert) or not active.select:
            self.report(
                {'ERROR'},
                "No active vertex. Select vertices one by one (click), the last click is the target."
            )
            return {'CANCELLED'}

        others_all = [v for v in bm.verts if v.select and v != active]
        if not others_all:
            self.report({'ERROR'}, "Select at least one other vertex besides the last one.")
            return {'CANCELLED'}

        # Other selected vertices in selection order (oldest -> newest)
        history_others = [
            e for e in bm.select_history
            if isinstance(e, bmesh.types.BMVert) and e.select and e != active
        ]
        ordered_ok = len(history_others) == len(others_all)

        # Reference vertices (honor Window when selection order is available)
        note = ""
        if self.window > 0 and ordered_ok:
            used = history_others[-self.window:]
        else:
            used = others_all
            if self.window > 0:
                note = " (Window ignored: no selection order)"

        pts = [mw @ v.co for v in used]
        n = len(pts)
        target = mw @ active.co

        # ---------- Mode: average position ----------
        if self.mode == 'CENTER':
            new_world = sum(pts, Vector()) / n
            msg = f"Moved to the average of {n} vertices"

        # ---------- Mode: curve fix ----------
        elif self.mode == 'CURVE':
            try:
                new_world, msg = curve_fix(
                    pts, target, self.degree, self.placement == 'KEEP', self.spacing_scale
                )
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

        # ---------- Mode: smart (straight line) ----------
        else:
            if n < 2:
                self.report({'ERROR'}, "Smart mode needs at least 2 other vertices to define a line.")
                return {'CANCELLED'}

            fit = fit_line(pts)
            if fit is None:
                self.report({'ERROR'}, "The selected points are at the same location, no direction to follow.")
                return {'CANCELLED'}
            c, d = fit

            # Position of every reference point along the fitted line
            ts = [(p - c).dot(d) for p in pts]
            idx = sorted(range(n), key=lambda i: ts[i])
            sp = [pts[i] for i in idx]
            st = [ts[i] for i in idx]
            t_new = (target - c).dot(d)

            if self.placement == 'KEEP':
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
                    new_world = c + d * (st[-1] + spacing * self.spacing_scale)
                    msg = f"Extended beyond the end, spacing = {spacing:.4f}"
                elif t_new <= st[0]:
                    new_world = c + d * (st[0] - spacing * self.spacing_scale)
                    msg = f"Extended beyond the start, spacing = {spacing:.4f}"
                else:
                    lo = max(i for i in range(n) if st[i] < t_new)
                    hi = min(i for i in range(n) if st[i] > t_new)
                    new_world = (sp[lo] + sp[hi]) / 2
                    gap = (sp[hi] - sp[lo]).length
                    msg = f"Placed between its two neighbors (gap = {gap:.4f}, each side = {gap / 2:.4f})"

        active.co = mw.inverted() @ new_world
        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, msg + note)
        return {'FINISHED'}


# ----------------------------------------------------------------------------
# Operator: extrude a new vertex, continuing the chain
# ----------------------------------------------------------------------------

class MESH_OT_extrude_average_chain(bpy.types.Operator):
    """Extrude a new vertex that continues the selected chain (line or curve)"""
    bl_idname = "mesh.extrude_average_chain"
    bl_label = "Extrude Chain Point"
    bl_options = {'REGISTER', 'UNDO'}

    curve: bpy.props.BoolProperty(
        name="Follow Curve",
        description="Follow the curve of the selected points instead of a straight line "
                    "(needs at least 3 selected points)",
        default=False,
    )
    degree: bpy.props.IntProperty(
        name="Curve Degree",
        description="Curve mode only: 1 = straight line, 2 = simple arc, 3 = S-shaped curve "
                    "(limited to number of points - 1)",
        default=2,
        min=1,
        max=5,
    )
    spacing_scale: bpy.props.FloatProperty(
        name="Spacing Scale",
        description="Multiplier for the average spacing between the selected points",
        default=1.0,
        min=0.0,
        soft_max=3.0,
    )
    window: bpy.props.IntProperty(
        name="Window",
        description="Use only the last N selected points (in selection order) as reference. "
                    "0 = use all selected points",
        default=0,
        min=0,
        soft_max=20,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world
        mw_inv = mw.inverted()

        selected = [v for v in bm.verts if v.select]
        if len(selected) < 2:
            self.report({'ERROR'}, "Select at least 2 vertices (3 for curve), one by one (click), in order.")
            return {'CANCELLED'}

        ordered = [
            e for e in bm.select_history
            if isinstance(e, bmesh.types.BMVert) and e.select
        ]
        if len(ordered) != len(selected):
            self.report({'ERROR'}, "Some selected vertices have no selection order. Select them one by one (click).")
            return {'CANCELLED'}

        used = ordered[-self.window:] if self.window > 0 else ordered
        pts = [mw @ v.co for v in used]

        try:
            new_world = extrude_calc(pts, self.curve, self.degree, self.spacing_scale)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        last_vert = used[-1]
        ret = bmesh.ops.extrude_vert_indiv(bm, verts=[last_vert])
        new_vert = ret['verts'][0]
        new_vert.co = mw_inv @ new_world

        new_vert.select = True
        bm.select_history.add(new_vert)

        bmesh.update_edit_mesh(obj.data)
        kind = "curve" if self.curve else "line"
        self.report({'INFO'}, f"Extruded new point continuing the {kind}")
        return {'FINISHED'}


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

class VIEW3D_PT_move_last_to_average(bpy.types.Panel):
    bl_label = "Average Vertex"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        fix_id = MESH_OT_move_last_to_average.bl_idname
        extrude_id = MESH_OT_extrude_average_chain.bl_idname

        layout.label(text="Fix Selected Vertex:")
        col = layout.column(align=True)
        op = col.operator(fix_id, text="Smart: Average Distance", icon='MODIFIER')
        op.mode = 'AUTO'
        op.placement = 'AVERAGE'
        op = col.operator(fix_id, text="Smart: Keep Distance", icon='SNAP_NORMAL')
        op.mode = 'AUTO'
        op.placement = 'KEEP'

        col = layout.column(align=True)
        op = col.operator(fix_id, text="Curve: Average Distance", icon='CURVE_DATA')
        op.mode = 'CURVE'
        op.placement = 'AVERAGE'
        op = col.operator(fix_id, text="Curve: Keep Distance", icon='PINNED')
        op.mode = 'CURVE'
        op.placement = 'KEEP'

        op = layout.operator(fix_id, text="Move to Average", icon='SNAP_MIDPOINT')
        op.mode = 'CENTER'

        layout.separator()
        layout.label(text="Extrude New Vertex:")
        col = layout.column(align=True)
        op = col.operator(extrude_id, text="Extrude Along Line", icon='FORWARD')
        op.curve = False
        op = col.operator(extrude_id, text="Extrude Along Curve", icon='SPHERECURVE')
        op.curve = True


def menu_func(self, context):
    fix_id = MESH_OT_move_last_to_average.bl_idname
    extrude_id = MESH_OT_extrude_average_chain.bl_idname
    self.layout.separator()
    op = self.layout.operator(fix_id, text="Smart Fix Last Vertex: Average Distance")
    op.mode = 'AUTO'
    op.placement = 'AVERAGE'
    op = self.layout.operator(fix_id, text="Smart Fix Last Vertex: Keep Distance")
    op.mode = 'AUTO'
    op.placement = 'KEEP'
    op = self.layout.operator(fix_id, text="Curve Fix Last Vertex: Average Distance")
    op.mode = 'CURVE'
    op.placement = 'AVERAGE'
    op = self.layout.operator(fix_id, text="Curve Fix Last Vertex: Keep Distance")
    op.mode = 'CURVE'
    op.placement = 'KEEP'
    op = self.layout.operator(fix_id, text="Move Last Vertex to Average")
    op.mode = 'CENTER'
    self.layout.separator()
    op = self.layout.operator(extrude_id, text="Extrude Chain Point Along Line")
    op.curve = False
    op = self.layout.operator(extrude_id, text="Extrude Chain Point Along Curve")
    op.curve = True


classes = (
    MESH_OT_move_last_to_average,
    MESH_OT_extrude_average_chain,
    VIEW3D_PT_move_last_to_average,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
