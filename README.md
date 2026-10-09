# To Install

Download (`vertex_tools.py`) and Edit > Preferences > Addon > Install From Disk. 

---

# Vertex Tools

A Blender add-on with three point-by-point modeling tools, bundled in one
file (`vertex_tools.py`) and shown in their own sidebar tab,
**N Panel > Vertex Tools**, or in a menu with **`Shift+Q`** (Edit Mode).
Each tool is a collapsible panel, so you can fold away the ones you're
not using:

- **Average Vertex**: fix or extend a chain of vertices along a line,
  curve or circle. Snap a misplaced point into place, straighten a whole
  chain, or extrude new points that continue the pattern, with a ghost
  preview before you apply.
- **Draw With Vertex**: click points, rectangles or circles in the
  viewport to build faces or edges, on a plane or right on a surface, with
  grid, vertex, edge and angle snapping. Draw shapes into a face, or pull
  them into live Boolean cutters / adders.
- **Face Projection**: turn the view to look straight at any plane you
  select (3 vertices, 2 edges or a face), flatten a selection onto its
  plane, and draw on it.

---

## Shift+Q menu

In Edit Mode, press **`Shift+Q`** to open the Vertex Tools menu with all
actions in three columns (Average Vertex, Draw With Vertex, Face
Projection). To change it: `Edit > Preferences > Keymap`, search for
`VIEW3D_MT_vertex_tools` (under 3D View > Mesh).

The menu is also in `Vertex` menu > `Vertex Tools`.

---

## Average Vertex

### Why

When you're placing vertices one by one along a path (a profile, a spline
guide, a row of screw holes, anything laid out point by point), it's easy
for one point to end up slightly off — not quite on the line, not quite
evenly spaced. Nudging it by eye is tedious and imprecise. This tool does
the math for you: fit a line, curve or circle through the selected
points, then place the vertices relative to that fit.

### Fit types

| Fit | Use it for |
|---|---|
| Line | Straight rows |
| Curve | Free-form bends: a polynomial (arc / S-curve, adjustable degree) |
| Circle | Round things: arcs, bolt circles, rims. A true circle, so the radius stays constant |

### Fix Selected Vertex

Select your reference vertices one by one (click, not box-select — the
order matters), then click one more vertex last: that's the one that gets
moved.

- **Smart / Curve / Circle: Average Distance** — fits a line, curve or
  circle through the reference points. If the target sits beyond either
  end of the chain, it is placed one average spacing (or, for circles,
  one average angle step) further out. If it sits between two neighbors,
  it is placed exactly halfway between them.
- **Smart / Curve / Circle: Keep Distance** — same fit, but the target's
  position *along* it is left untouched; it is only snapped onto the
  line, curve or circle. Use this when a point is roughly the right
  distance along but has drifted sideways.
- **Move to Average** — places the target at the centroid of all
  reference points.

### Fix Whole Chain

Straighten or smooth a whole chain in one click. Select the chain either
by clicking the vertices in order, or by selecting one connected path of
edges (box select works for that).

- **Chain: Even Along Line** — one straight line, points evenly spaced
  from the first to the last.
- **Chain: Even Along Curve** — a curve, points at equal distances along
  it.
- **Chain: Even Along Arc** — a circle, points at equal angles from the
  first to the last.
- **Chain: Full Circle** — a circle, points evenly spaced around the
  *whole* circle (e.g. 6 points → 60° apart).

In the redo panel (bottom left), set **Placement** to `Keep Distance` to
only snap each point onto the fit without changing the spacing.

### Extrude New Vertex

Select the chain (in order) and new vertices are created past the last
selected point, connected by edges, with the spacing / curvature taken
from the chain.

- **Extrude Along Line / Curve / Circle**.
- **Count** (redo panel) — add several points in one go.

The new vertices are selected and added to the selection history, so
running it again (or `Shift+R` to repeat) keeps extending the chain.

### Preview & Apply

The **Preview & Apply** subpanel (inside Average Vertex, collapsed by
default — click its header to open it) lets you look before you change
anything:

1. Pick the **action** (any Fix / Whole Chain / Extrude action, or
   Flatten to Plane) and its options.
2. Press **Preview**: ghost points (cyan) show where the vertices would
   go, with lines from their current position. Extruded points show as a
   ghost chain. The ghosts update live while you change the options.
3. Press **Apply** to do it, or cancel the preview: the button turns into
   **Cancel**, or press `Esc`, or click anywhere outside the sidebar.

If the selection doesn't fit the action, the reason is shown under the
buttons.

### Options

| Property | Applies to | Description |
|---|---|---|
| Placement | Fix / Whole Chain | `Average / Even Spacing`, `Keep Distance`, or `Full Circle` (whole chain + circle only) |
| Curve Degree | Curve fits | 1 = line, 2 = arc, 3 = S-curve (capped at points − 1) |
| Spacing Scale | Average Distance / Extrude | Multiplier on the computed spacing |
| Window | Fix / Extrude | Use only the last *N* selected points as reference (0 = use all). Useful for long or curved chains where only the local neighborhood should matter |
| Count | Extrude | How many new points to add |

All computation happens in world space, so it works correctly across
object scale and rotation.

---

## Draw With Vertex

### What it does

Press **Draw** in the **Draw With Vertex** section (or use the `Shift+Q`
menu / `Mesh` menu) and click in the viewport. Points are placed on a
drawing plane that passes through the 3D cursor (and is re-anchored on
the first point you click). A live preview shows the outline and,
optionally, a filled face.

### Shapes

| Shape | How to draw |
|---|---|
| Points | Click points one by one, `Enter` to finish (or click the first point to close) |
| Rectangle | Two clicks: opposite corners. Hold `Ctrl` for 45° diagonals (squares) |
| Circle | Two clicks: center, then radius. **Sides** sets the number of sides (6 = hexagon), `+` / `-` while drawing |

Rectangles and circles finish by themselves on the second click.

### Result

- **Face** — creates a face.
- **Edges Only** — creates just vertices and edges: an open path, or a
  closed loop if you click the first point again. Rectangles and circles
  become closed edge loops. Handy for profiles you then tidy up with
  Fix Whole Chain.

### Draw on Face

**Draw on Face** (under **Draw**) draws a shape *into* an existing face,
flat on its plane. Handy together with Face Projection: align the view to
a face, then draw on it.

1. Press **Draw on Face** and click on a face of the mesh you're editing.
   That face is outlined in blue and everything you draw stays flat on
   its plane. Clicking on empty space gives an error: use **Draw** for
   that.
2. Draw as usual: Points, Rectangle or Circle, with all the snapping. With
   **Merge** on, points snapped to the face's corners or edges are shared
   with it, so e.g. a square in the corner of the face shares its edges
   with the rest of the face.
3. Finish, then pick the **Face Method** in the panel at the bottom left
   (it re-applies instantly):

| Face Method | Result |
|---|---|
| **Cut In** (default) | The shape becomes its own face, cut into the face. The rest of the face stays filled. A shape floating inside gets 2 connecting edges (a face can't have a hole); a shape touching the face's edge needs none |
| **Replace (leave gap)** | The shape becomes a face and the rest of the old face is removed. Its outline edges stay, so you can fill the gap yourself (e.g. `Edge > Bridge Edge Loops`) |
| **Auto-Bridge** | The shape becomes a face and the ring around it is filled. Every point is connected to its *nearest* points on the other outline (no long faces reaching to far corners), and triangles are joined into quads where they make good quads (e.g. a square in a square gives 4 clean quads). A shape touching the face's edge is cut in instead |

**Auto-Bridge options** (shown in the same bottom-left panel when
Auto-Bridge is picked, they re-apply instantly):

| Option | What it does |
|---|---|
| **Attach Mode** | `Nearest` (default): of all ways to connect the two outlines, the one with the shortest connections. `Even`: connections spread evenly around both outlines, nice when one has many more points (a circle in a square). `Blender Bridge`: Blender's own Bridge Edge Loops |
| **Twist** (slider) | Rotates which points connect to which. `Nearest` connects as if the shape were turned by that many steps; `Even` and `Blender Bridge` shift the starting pair |
| **Quad Angle** (slider) | How willing it is to join triangles into quads. Higher = more quads (even bent ones), `0°` = triangles only |

Every result is checked: if a mode or twist would make overlapping
faces, it falls back to Twist 0 (then the other modes) and the message
at the bottom tells you what was used.

The shape has to stay inside the face; if it goes outside, nothing is
changed and you get a message. New faces keep the old face's direction.

#### Draw on Face vs. Blender's Knife tool (`K`)

Both put new edges into an existing face, but they're built for
different jobs.

**Where Draw on Face is better:**

| | Draw on Face | Knife tool |
|---|---|---|
| **Exact shapes** | Rectangles and circles / polygons (any number of sides) in two clicks | Only point by point; a circle has to be clicked out by hand |
| **Stays flat** | Everything is flattened onto the face's plane, even if a point was off | Follows the surface where you click; no flattening |
| **Grid snapping** | Grid on the face's own plane, plus `Ctrl` angle steps | Snaps to vertices / edges / midpoints, angle steps with `A`, no grid |
| **What happens to the rest of the face** | You choose afterwards: **Cut In**, **Replace (leave gap)** or **Auto-Bridge**, and can switch in the redo panel without redrawing | Always cut in; anything else is manual work afterwards |
| **Filling around a shape** | Auto-Bridge fills the ring for you, with Attach Mode, Twist and Quad Angle controls, and checks it never overlaps | Not available (Bridge Edge Loops afterwards, by hand) |
| **Holes in a face** | Handled for you: 2 connecting edges (Cut In) or a filled ring (Auto-Bridge) | Also connects a loop floating inside a face, but you don't choose how |
| **Result** | The new shape is a ready face, selected, facing the same way as the old face | New edges; you select the new face yourself |
| **Snapping** | Only to what you can see (unless X-ray), and Merge Distance catches near-misses | Snaps to what's under the cursor |
| **Workflow** | Pairs with Face Projection: **Align View** to a face, then **Draw on Face** on it | Works from any view |

**Where the Knife tool is better:**

- **Cutting across several faces** in one go. Draw on Face works on one
  face at a time, and the shape has to stay inside it.
- **Open cuts**: a single line from one edge to another. Draw on Face
  always makes a closed shape.
- **Cut Through** (`Z`): cutting the back side of the mesh too.
- **Arbitrary paths** that follow a curved surface.

**In short:** use **Draw on Face** for clean, exact shapes inside one
flat face (panels, windows, insets, logos, screw holes) where you want
control over the faces around them. Use the **Knife** for freeform cuts
across the mesh.

### Draw for Bool

**Draw for Bool** (the **Bool** row under **Draw on Face**: **Auto**,
**Cut**, **Extrude**) draws a shape on a face, then lets you pull it in or
out by hand. The shape becomes a separate **cutter object** with a live
Boolean on your mesh, so you can keep moving and angling it before you
make it permanent.

1. In Edit Mode, press **Auto**, **Cut** or **Extrude**. First you
   **pick where to draw** (the header says so, and nothing can be drawn
   yet). The face under the mouse is highlighted:
   - **Click a face**: everything you draw stays flat on that face's
     plane, and unlike Draw on Face the shape **may go past the face's
     edges**.
   - **`Space`** (or click empty space): draw on the drawing plane, by
     default the view plane through the 3D cursor, and pull along the
     view direction.
2. Draw as usual (Points, Rectangle or Circle, with all the snapping).
   To cut / add the same distance to **both sides** of the plane, turn on
   the **Both Directions** toggle under the Auto / Cut / Extrude buttons
   first (or press `B` while pulling).
3. When the shape is finished, **move the mouse to pull it**: the cut / add
   updates live. You can pull either way in every mode:

| Mode | Push into the surface | Pull out of it |
|---|---|---|
| **Auto** | Cuts | Adds |
| **Cut** | Cuts a pocket | Cuts away anything above the surface |
| **Extrude** | Fills: e.g. the part of the shape hanging over the face's edge gets filled down | Adds a raised block |

   While pulling:

| Key | Action |
|---|---|
| `Tab` | Switch Auto / Cut / Extrude |
| `B` | **Both Directions**: pull the same distance to both sides of the plane (like a CAD *symmetric* extrude), e.g. a slot cut through a wall from its middle |
| `A` | Align Snap: hover any vertex of the mesh to pull to exactly its height (green dot + guide line) |
| `Ctrl` (hold) | Snap the depth to the Grid Size |
| `LMB` / `Enter` | Done |
| `RMB` / `Esc` | Cancel (nothing is left behind) |

   If the view looks straight down the face, pull with mouse
   **up = out**, **down = in**.
4. The **bottom-left panel** (Adjust Last Operation) then has **Mode**
   (Auto / Cut / Extrude), the exact **Depth** (+ = out, - = in) and
   **Both Directions**. Changing them rebuilds the cutter instantly. `B`
   also flips the panel toggle, so it's remembered for the next Draw for Bool.
5. After confirming you're in **Edit Mode on the cutter**, with its far
   cap selected: **`G`** changes the depth, **`S`** tapers the walls into
   an angled cut, and you can grab any of its edges or vertices. The
   Boolean updates while you edit.

The **Bool Cutters** panel (shown when the cutter or its mesh is active)
has:

| Button | What it does |
|---|---|
| **Difference / Union / Intersect** | Switch what the cutter does, any time |
| **Solver** | Boolean solver (`Exact` by default) |
| **Edit Cutter** | Edit a cutter again (on the mesh: one ✎ button per cutter, plus an eye to hide its effect) |
| **Back to Mesh** | Leave the cutter and edit your mesh again |
| **Apply Bool** | Make it permanent and delete the cutter. On a cutter: just that one. On the mesh: **Apply All Bools** |

The cutter is parented to your mesh (it moves with it), shows as a
wireframe and is hidden in renders. Each Draw for Bool adds a new cutter,
so you can stack several before applying. The cuts stay visible while
you're back in Edit Mode on your mesh.

### Drawing plane

| Plane | Description |
|---|---|
| View | Faces the camera exactly |
| Nearest Axis | The world axis plane closest to the view direction |
| Surface | Draws right on the surface under the mouse (any visible object, including the mesh you're editing). Rectangles and circles lie flat on the surface where you first click. **Surface Offset** lifts the points slightly off the surface |
| X / Y / Z | Locked to the plane perpendicular to that axis (side / front / top) |

The snap options are one row of icon toggles next to **Snap** (grid, vertex, edge,
merge, and fill preview). Hover an icon to see its name.

### Snapping

- **Only what you can see** — vertex and edge snapping ignore anything
  hidden behind geometry (the edited mesh or other objects). Turn on
  X-ray (`Alt+Z`, works while drawing) to snap to hidden parts too.
- **Snap to Vertices** — snaps the cursor to existing mesh vertices.
- **Snap to Edges** (`E` to toggle) — snaps onto an existing edge, the
  edge is highlighted pink. Near the middle of the edge it snaps exactly
  to the midpoint. With Merge on, the edge is split at that point, so the
  new face connects to it (and to the faces next to it). Vertex snap
  wins over edge snap when both are in range.
- **Merge** (on by default, `M` to toggle) — a point that sits on an
  existing vertex or edge is merged with it, so the new face really
  connects to your mesh (shared vertices and edges, no duplicates stacked
  on top). This also catches points that land on a vertex through grid or
  angle snapping, within **Merge Distance**. The cursor turns **blue**
  when the point will merge. With Merge off, a separate vertex is created
  on top of the existing one instead.
- **Align Snap** (on by default, `A` to toggle) — CAD-style tracking.
  Hover a vertex (it gets a small yellow dot: it's now *tracked*, the last
  4 are kept), then move away: when the cursor comes level with it, it
  snaps to **the same height** or **the same side-to-side position** on
  the drawing plane, with a cyan guide line back to it. Points you've
  already drawn work the same way without hovering, so you can line up a
  new point with any earlier one. Near two lines at once it snaps to
  where they cross. Off while holding `Ctrl` (angle snap wins).
- **Snap to Grid** — snaps to a grid on the drawing plane (adjustable
  Grid Size). On axis planes the grid lines up with the world grid.
- **Ctrl angle snap** — hold `Ctrl` to constrain the direction from the
  last point to the Angle Step (default 45°).

New faces are oriented so their normal points toward the viewer.

### Controls while drawing

| Key | Action |
|---|---|
| `LMB` | Add a point (click the first point to close) |
| `Ctrl` (hold) | Angle snap |
| `R` / `C` | Rectangle / Circle shape (press again for Points) |
| `+` / `-` | More / fewer circle sides |
| `P` | Toggle Edges Only (path) |
| `X` / `Y` / `Z` | Lock the plane to that axis (press again to return to View) |
| `S` | Surface plane (press again to return to View) |
| `G` | Toggle grid snap |
| `V` | Toggle vertex snap |
| `E` | Toggle edge snap |
| `A` | Toggle Align Snap |
| `M` | Toggle merge |
| `F` | Toggle fill preview |
| `Backspace` / `Ctrl+Z` | Remove the last point |
| `Enter` / `Space` / `RMB` | Finish |
| `Esc` | Cancel |
| `Alt+Z` | Toggle X-ray (snap to hidden vertices / edges too) |
| `MMB` / wheel | Orbit, pan and zoom as usual (the plane stays fixed) |

---

## Face Projection

### What it does

Turns the view so you look straight down onto the plane of your
selection, like Blender's `Shift+Numpad 7` (Align View to Active), but it
also works for vertices and edges, not only faces:

| Selection | Plane used |
|---|---|
| 3 vertices | The plane through them |
| 2 edges | The best-fit plane through their vertices |
| 1 or more faces | The faces' normal (you look at the front side) |
| More vertices | The best-fit plane through all of them |

Points that are all on one line don't define a plane and give an error.

### Buttons

- **Align View to Selection** — aligns, centers the view on the selection
  and switches to orthographic.
- **Align View + Cursor** — the same, and also moves and rotates the 3D
  cursor onto the plane.
- **Align + Draw** — aligns, puts the cursor on the plane and starts
  **Draw With Vertex** on it right away, so you can draw exactly on a
  slanted plane in one click.
- **Back to Previous View** — returns to the view you had before
  aligning (it remembers several steps).
- **Flatten to Plane** — moves all selected vertices onto the best-fit
  plane of the selection. Great for fixing slightly wonky faces. Also
  available as a Preview & Apply action.

### Options (redo panel, bottom left)

| Property | Description |
|---|---|
| Roll | How the view is turned on screen: `World Up` (default, world Z stays up like the Front/Side views; flat planes get world Y up like the Top view), `Edge Horizontal` (the first two clicked vertices, or the longest selected edge, lie horizontal) or `Keep Current` |
| Flip | Look at the plane from the other side |
| Center View | Center the view on the selection |
| Orthographic | Switch to an orthographic view |
| Move 3D Cursor | Move and rotate the 3D cursor onto the plane |

For vertices and edges, the view stays on the side you're currently
looking from.

---

## Installation

1. If you installed the older separate add-ons (`Move Last Vertex to
   Average` or `Draw With Vertex`), disable and remove them first. They
   register the same operators and would clash.
2. `Edit > Preferences > Add-ons > Install...` (Blender 4.2+: `⌄` menu >
   `Install from Disk...`), pick `vertex_tools.py`.
3. Enable **Vertex Tools**.
4. In Edit Mode, press `N` and open the **Vertex Tools** tab: you'll
   find the **Average Vertex**, **Draw With Vertex** and **Face
   Projection** panels. Or press `Shift+Q`.

## Requirements

- Blender 3.0+ (tested with Blender 5.2)
- NumPy (bundled with Blender's Python)

## License

GPL-3.0-or-later (matches Blender's add-on licensing requirements).
