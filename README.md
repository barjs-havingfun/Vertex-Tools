# Vertex Tools

A Blender add-on with two point-by-point modeling tools, bundled in one
file (`vertex_tools.py`) and shown together in the sidebar under
**N Panel > Tool > Vertex Tools**:

- **Average Vertex**: fix or extend a chain of vertices. Snap a misplaced
  point into line with its neighbors, or extrude a new point that
  continues the pattern.
- **Draw With Vertex**: click points in the viewport to build a face on a
  plane, with grid, vertex and angle snapping.

---

## Average Vertex

### Why

When you're placing vertices one by one along a path (a profile, a spline
guide, a row of screw holes, anything laid out point by point), it's easy
for one point to end up slightly off — not quite on the line, not quite
evenly spaced. Nudging it by eye is tedious and imprecise. This tool does
the math for you: fit a line or curve through the *other* selected
points, then place the **last selected vertex** relative to that fit.

### Fix Selected Vertex

Select your reference vertices one by one (click, not box-select — the
order matters), then click one more vertex last: that's the one that gets
moved. Five ways to place it:

- **Smart: Average Distance** — Fits a straight line through the
  reference points. If the target sits beyond either end of the chain, it
  is placed one average inter-point spacing further out. If it sits
  between two neighbors, it is placed exactly halfway between them.
- **Smart: Keep Distance** — Same line fit, but the target's position
  *along* the line is left untouched; only its perpendicular offset is
  corrected. Use this when a point is already roughly the right distance
  along the chain but has drifted sideways.
- **Curve: Average Distance** — Like Smart, but fits a polynomial curve
  (arc / S-curve, adjustable degree) through the reference points instead
  of a straight line. Needs at least 3 reference points.
- **Curve: Keep Distance** — The curve equivalent of Keep Distance: snaps
  the point onto the fitted curve without changing its position along it.
- **Move to Average** — Simplest option: places the target at the
  centroid of all reference points.

### Extrude New Vertex

No target vertex needed — select the chain (in order), pick a direction,
and a brand-new vertex is created past the last selected point, connected
by an edge, with the spacing/curvature inferred from the rest of the
chain.

- **Extrude Along Line** — continues the straight-line fit.
- **Extrude Along Curve** — continues the fitted curve (needs 3+ points).

The new vertex is automatically selected and added to the selection
history, so pressing the operator again (or `Shift+R` to repeat) keeps
extending the chain one point at a time.

### Options

| Property | Applies to | Description |
|---|---|---|
| Placement | Smart / Curve fix | `Average Distance` vs `Keep Distance` |
| Curve Degree | Curve modes | 1 = line, 2 = arc, 3 = S-curve (capped at points − 1) |
| Spacing Scale | Average Distance / Extrude | Multiplier on the computed spacing |
| Window | All modes | Use only the last *N* selected points as reference (0 = use all). Useful for long or curved chains where only the local neighborhood should matter |

### Usage

In Edit Mode, vertex select mode (`1`):

- **Fix a point:** click your reference vertices in order, click the
  vertex to fix last, then run it from the **Average Vertex** section or
  the `Vertex` menu.
- **Extend a chain:** click the chain vertices in order, then run
  Extrude Along Line/Curve. Repeat with `Shift+R` to keep going.

All computation happens in world space, so it works correctly across
object scale and rotation.

---

## Draw With Vertex

### What it does

Run **Draw Face By Points** from the **Draw With Vertex** section (or the
`Mesh` menu), click points in the viewport, and a face is created from
them. Points are placed on a drawing plane that passes through the 3D
cursor (and is re-anchored on the first point you click). A live preview
shows the outline and, optionally, a filled face.

### Drawing plane

| Plane | Description |
|---|---|
| View | Faces the camera exactly |
| Nearest Axis | The world axis plane closest to the view direction |
| X / Y / Z | Locked to the plane perpendicular to that axis (side / front / top) |

### Snapping

- **Snap to Vertices** — snaps to existing mesh vertices; the new face is
  welded to them, so it connects to your existing geometry.
- **Snap to Grid** — snaps to a grid on the drawing plane (adjustable
  Grid Size). On axis planes the grid lines up with the world grid.
- **Ctrl angle snap** — hold `Ctrl` to constrain the direction from the
  last point to the Angle Step (default 45°).
- Clicking near the **first point** closes the shape and creates the face.

The new face is oriented so its normal points toward the viewer.

### Controls while drawing

| Key | Action |
|---|---|
| `LMB` | Add a point (click the first point to close) |
| `Ctrl` (hold) | Angle snap |
| `X` / `Y` / `Z` | Lock the plane to that axis (press again to return to View) |
| `G` | Toggle grid snap |
| `V` | Toggle vertex snap |
| `F` | Toggle fill preview |
| `Backspace` / `Ctrl+Z` | Remove the last point |
| `Enter` / `Space` / `RMB` | Finish and create the face |
| `Esc` | Cancel |
| `MMB` / wheel | Orbit, pan and zoom as usual (the plane stays fixed) |

---

## Installation

1. If you installed the older separate add-ons (`Move Last Vertex to
   Average` or `Draw With Vertex`), disable and remove them first. They
   register the same operators and would clash.
2. `Edit > Preferences > Add-ons > Install...`, pick `vertex_tools.py`.
3. Enable **Vertex Tools**.
4. In Edit Mode, press `N` and open the `Tool` tab: you'll find the
   **Vertex Tools** panel with the **Average Vertex** and **Draw With
   Vertex** sections.

## Requirements

- Blender 3.0+ (also works with Blender 4.x)
- NumPy (bundled with Blender's Python)

## License

GPL-3.0-or-later (matches Blender's add-on licensing requirements).
