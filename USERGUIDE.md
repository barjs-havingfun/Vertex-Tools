# Vertex Tools — User Guide

A step-by-step guide to every tool in Vertex Tools (version 3.5.0). The
[README](README.md) is the short reference; this guide explains **how to
use** each tool, with examples, tips and what to do when something goes
wrong.

## Contents

1. [Getting started](#1-getting-started)
2. [Average Vertex](#2-average-vertex)
   - [Fix Last Vertex](#fix-last-vertex)
   - [Move Last to Average](#move-last-to-average)
   - [Fix Whole Chain](#fix-whole-chain)
   - [Extrude New Vertex](#extrude-new-vertex)
   - [Preview & Apply](#preview--apply)
3. [Draw With Vertex](#3-draw-with-vertex)
   - [Draw](#draw)
   - [Typing exact sizes](#typing-exact-sizes)
   - [Drawing planes](#drawing-planes)
   - [Snapping](#snapping)
   - [Draw on Face](#draw-on-face)
   - [Draw for Bool](#draw-for-bool)
   - [Bool Cutters](#bool-cutters)
4. [Face Projection](#4-face-projection)
5. [The Shift+Q menu](#5-the-shiftq-menu)
6. [Recipes](#6-recipes)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Getting started

### Install

1. If you have the old separate add-ons (`Move Last Vertex to Average` or
   `Draw With Vertex`), disable and remove them first.
2. `Edit > Preferences > Add-ons`, then `⌄` (top right) > **Install from
   Disk...** and pick `vertex_tools.py`.
3. Tick **Vertex Tools** to enable it.

After updating the file, disable and re-enable the add-on (or restart
Blender) so the new version loads.

### Where to find it

Select a mesh and press `Tab` for **Edit Mode**. Then either:

- press `N` and open the **Vertex Tools** tab in the sidebar, or
- press **`Shift+Q`** over the viewport for the menu with every action.

The sidebar has four panels. Click a panel's header to fold it away.

| Panel | What it's for |
|---|---|
| **Average Vertex** | Fixing and extending rows of vertices: straight, curved or round |
| **Draw With Vertex** | Drawing new faces, edges, shapes cut into faces, and Boolean cutters |
| **Bool Cutters** | Managing the cutters made by Draw for Bool (only shown when there are any) |
| **Face Projection** | Looking straight at a slanted plane, and flattening selections |

### Two things that work everywhere

- **The bottom-left panel** (Adjust Last Operation). After almost every
  action, its options appear at the bottom left of the viewport. Change
  them and the action re-runs instantly. If it's collapsed, click its
  title to open it.
- **Undo** (`Ctrl+Z`) works for everything.

---

## 2. Average Vertex

Use it when vertices you placed by hand are slightly off: not quite on a
line, not quite evenly spaced, not quite round. It fits a line, curve or
circle through the vertices and moves them onto it.

### The panel

```
Fit:  [ Line | Curve | Circle ]
      [ Keep Distance ]
      ✓ 12 verts, edge path
      [ Fix Last Vertex    ]
      [ Fix Whole Chain    ]
      [ Extrude New Vertex ]
      [ Move Last to Average ]
```

**Step 1: choose the Fit.** Every button below uses it.

| Fit | Use it for |
|---|---|
| **Line** | Straight rows: edges of a panel, a row of holes |
| **Curve** | Free bends: a fender line, an S-curve. Curve Degree (bottom-left panel) sets how bendy: 1 = line, 2 = simple arc (default), 3 = S-curve |
| **Circle** | Anything round: arcs, rims, bolt circles. A true circle, so the radius stays the same everywhere |

**Step 2: choose the spacing.**

- **Keep Distance off** (default): the points are also **evenly spaced**.
- **Keep Distance on**: points are only pulled onto the line / curve /
  circle. How far apart they are doesn't change.

**Step 3: check the status line.** Before you press anything, the line
under the buttons tells you what the add-on sees:

| Status | Meaning |
|---|---|
| `Select vertices` | Nothing is selected |
| `12 verts, click order` | You clicked every vertex one by one; that order is used |
| `12 verts, edge path` | The vertices are joined by selected edges in one open row |
| `12 verts, closed loop` | The edges go all the way round (a ring) |
| `12 verts, shape` | Loose vertices with no edges between them; the order comes from their shape |
| `Closed loop: use Circle` | A ring can't be put on a line or curve: switch Fit to Circle |
| `Extrude: Shift+click an end` | To extrude, the add-on needs to know which end to grow from |
| `… no chain order` (red) | The selection branches (e.g. a T-shape or a grid): select a single row |

### Fix Last Vertex

Moves **one** vertex (the last one you click) based on the others.

1. Click the reference vertices one by one (plain clicks, then
   `Shift+click` for each next one). Order matters here, so don't box
   select.
2. `Shift+click` the vertex to fix **last**.
3. Press **Fix Last Vertex**.

What happens depends on where the last vertex sits:

| Where the vertex is | Keep Distance off | Keep Distance on |
|---|---|---|
| Past either end of the row | Placed exactly one average spacing past the end (circle: one average angle step) | Pulled onto the line / curve / circle where it is |
| Between two vertices | Placed exactly halfway between its neighbors | Pulled onto the line / curve / circle where it is |

Options in the bottom-left panel:

- **Mode**: Smart (Line), Curve Fix, Circle Fix or Average Position.
- **Placement**: even spacing, or keep distance.
- **Curve Degree**.
- **Spacing Scale**: multiplies the spacing. `2.0` places the vertex two
  steps further out.
- **Window**: use only the last *N* clicked vertices as reference. Handy
  on long curved rows where only the nearby part matters. Keep it at 0
  when fixing a vertex in the middle of a row.

**Example:** you're placing screw holes along an edge and the fifth one
is a bit off. Click holes 1–4, `Shift+click` hole 5, then press **Fix
Last Vertex** with Fit = Line. Hole 5 lands exactly one spacing after
hole 4, on the line.

### Move Last to Average

Moves the last clicked vertex to the **center** (average position) of
the other selected vertices. Fit and Keep Distance don't matter here.

**Example:** click the 4 corners of a face, `Shift+click` a stray vertex,
then press **Move Last to Average**. The vertex moves to the face's
center.

### Fix Whole Chain

Moves **every** selected vertex onto one line / curve / circle in a
single click. You don't need to click them one by one. Any of these
works:

| How you select | Example |
|---|---|
| `Alt+click` an edge | Selects a whole edge loop or edge ring row |
| `A` | All of a circle mesh |
| Box select (`B` or drag) | A row of connected vertices, or loose vertices without edges |
| Click one by one | Any vertices, in the order you clicked |

Then press **Fix Whole Chain**. With Fit = Circle there are two buttons:

- **Fix Chain**: spaced evenly from the first to the last vertex (an arc).
  On a **closed ring**, this goes all the way round.
- **Full Circle**: spaced evenly around the *whole* circle, even if the
  vertices only covered part of it (6 vertices → 60° apart).

**Example:** you drew a wobbly circle with Draw. Press `A`, set Fit =
Circle, and press **Fix Chain**. It becomes a perfect, evenly spaced
circle.

### Extrude New Vertex

Adds new vertices that **continue** the row: straight on, following the
curve, or around the circle, with the same spacing.

1. Select the row.
   - If you click the vertices one by one, the last click is the end
     it grows from.
   - If you select it another way (`Alt+click`, box select),
     `Shift+click` the **end vertex** to grow from last, so it becomes the
     active (white) vertex.
2. Press **Extrude New Vertex**.

Bottom-left panel: **Count** (how many new vertices), **Spacing Scale**,
**Window**, **Curve Degree**.

The new vertices are selected and become the new end, so pressing it
again (or `Shift+R`, Repeat Last) keeps going.

**Example:** you have 4 holes of a bolt circle. Select them, set Fit =
Circle, press **Extrude New Vertex** and set Count = 4 in the bottom-left
panel. You get 4 more holes on the same circle.

### Preview & Apply

A sub-panel inside Average Vertex (closed by default; click its title).
Use it when you want to **see the result before** changing anything.

1. Pick the **action** from the list (any Fix Last / Whole Chain /
   Extrude variant, or Flatten to Plane) and set its options.
2. Press **Preview**. Cyan ghost points show where the vertices would go,
   with lines from where they are now. The ghosts update live while you
   change options or the selection.
3. Press **Apply** to do it. To cancel instead, press **Cancel** (the
   Preview button changes to it), `Esc`, or click anywhere outside the
   sidebar.

If the action can't work with your selection, the reason is shown in red
under the buttons.

---

## 3. Draw With Vertex

Draw new geometry by clicking in the viewport, like in a 2D CAD program.

### Draw

1. Choose the **Shape** in the panel (or press `R` / `C` while drawing):

   | Shape | How to draw |
   |---|---|
   | **Points** | Click each corner. Finish with `Enter`, `Space` or right-click, or click the **first point** again to close the shape |
   | **Rectangle** | Click one corner, then the opposite corner |
   | **Circle** | Click the center, then a point on the edge. **Sides** sets how many sides (6 = hexagon). `+` / `-` while drawing |

2. Choose the **Result**: **Face**, or **Edges Only** (`P` while drawing)
   for just vertices and edges. With Edges Only and Points, finishing
   without closing gives an open path.
3. Press **Draw** and click in the viewport. An orange outline and fill
   preview the result.

Rectangles and circles finish by themselves on the second click.

While drawing:

| Key | Action |
|---|---|
| `LMB` | Add a point |
| `0`–`9`, `.` | Type an exact size (see below) |
| `Ctrl` (hold) | Lock the direction to angle steps (45° by default, **Ctrl Angle Step**) |
| `Backspace` / `Ctrl+Z` | Remove the last point |
| `Enter` / `Space` / `RMB` | Finish |
| `Esc` | Cancel |
| `R` / `C` | Rectangle / Circle (press again: back to Points) |
| `+` / `-` | More / fewer circle sides |
| `P` | Edges Only on / off |
| `X` / `Y` / `Z` | Lock the plane to that axis (press again: back to View) |
| `S` | Surface plane (press again: back to View) |
| `G` `V` `E` `A` `M` | Grid / Vertex / Edge / Align snap, Merge: on / off |
| `F` | Fill preview on / off |
| `Alt+Z` | X-ray on / off |
| `MMB` / wheel | Orbit, pan, zoom as usual |

The **header** (top of the viewport) shows the shape, plane, number of
points and which snaps are on. The **status bar** (bottom of the window)
lists the keys, so you don't have to remember them.

New faces face toward you, and the new geometry is selected when done.

### Typing exact sizes

After the first point, **type a number** instead of clicking:

| Shape | The number is | Example |
|---|---|---|
| Points | The **length** to the next point, in the direction of the mouse | Point the mouse right, type `2`, `Enter`: the next point is exactly 2 to the right |
| Rectangle | **Width**, then `Tab`, **Height** | Type `3` `Tab` `1.5` `Enter`: a 3 × 1.5 rectangle, toward the mouse's corner |
| Circle | The **radius** | Type `0.5` `Enter`: a circle of radius 0.5 |

- The mouse still decides the **direction**; the number decides the
  **size**. Combine it with `Ctrl` for exact angles.
- For a rectangle, leave one field empty to keep the mouse's value for
  it.
- `Backspace` deletes a digit, `Tab` jumps to the next field, and `Esc`
  stops typing (the drawing continues).
- Numbers are in your **scene's units**. In a scene set to millimeters,
  `5` means 5 mm.

### Drawing planes

Points are placed on an invisible plane. Choose it in the panel (or with
keys while drawing):

| Plane | Use it for |
|---|---|
| **View** | Drawing flat to the screen (default) |
| **Nearest Axis** | Automatically the world plane (XY, XZ, YZ) you're looking at most directly |
| **Surface** (`S`) | Drawing right onto the surface under the mouse, on any visible object. Rectangles and circles lie flat on the surface where you first click. **Surface Offset** lifts the points slightly off it |
| **X / Y / Z** | Locked to a world plane: side, front or top |

The plane goes through the **3D cursor**, or through your first point if
that point snapped onto an existing vertex. To draw on a slanted plane,
use **Face Projection > Align + Draw** (see section 4).

### Snapping

The **Snap** row in the panel has the toggles (hover an icon for its
name):

| Snap | What it does | Color |
|---|---|---|
| **Grid** (`G`) | Snaps to a grid on the drawing plane (**Grid Size**). On axis planes it lines up with the world grid | Green |
| **Vertex** (`V`) | Snaps to existing vertices | Green, or blue with Merge |
| **Edge** (`E`) | Snaps onto existing edges, and to their exact midpoint near the middle. The edge lights up pink | Green, or blue with Merge |
| **Align** (`A`) | CAD-style tracking: hover a vertex (it gets a yellow dot), move away, and the cursor snaps level with it (same height or same side-to-side position) with a cyan guide line. Points you've drawn work the same way. Where two guides cross, it snaps to the crossing | Green |
| **Merge** (`M`) | A point on an existing vertex or edge is **joined** to it, so the new face connects to your mesh instead of floating on top. Edges are split at the point. **Merge Distance** also catches points that land on a vertex by grid or angle snapping | Blue |
| **Fill** (`F`) | Shows / hides the filled preview (not a snap) | — |

Snapping only uses what you can **see**. Vertices and edges hidden
behind geometry are ignored, unless X-ray is on (`Alt+Z`, works while
drawing).

### Draw on Face

Draws a shape **into an existing face**, flat on that face's plane:
panels, windows, insets, logos, screw holes.

1. Press **Draw on Face**. The face under the mouse is highlighted.
2. Click on the face. It's outlined in blue, and everything you draw now
   stays flat on it, even if a point was a bit off.
3. Draw the shape (Points, Rectangle or Circle, with all snaps and typed
   sizes). Keep it **inside** the face.
4. Finish. In the bottom-left panel, choose the **Face Method**; switching
   it re-applies instantly, without drawing again:

| Face Method | Result |
|---|---|
| **Cut In** (default) | The shape becomes its own face, cut into the face. The rest stays filled. A shape floating in the middle gets 2 connecting edges (a face can't have a hole) |
| **Replace (leave gap)** | The shape becomes a face and the rest of the old face is deleted. The outline edges stay, so you can fill the gap your own way (e.g. `Edge > Bridge Edge Loops`) |
| **Auto-Bridge** | The shape becomes a face and the ring around it is filled with clean faces, joined into quads where possible |

For **Auto-Bridge** there are extra options in the same panel:

- **Attach Mode**:
  - **Nearest** (default): the shortest connections.
  - **Even**: connections spread evenly around both outlines. Good for a
    circle inside a square.
  - **Blender Bridge**: Blender's own Bridge Edge Loops.
- **Twist**: rotates which points connect to which.
- **Quad Angle**: higher makes more quads, `0°` makes triangles only.

If your choice would make overlapping faces, it automatically falls
back to one that works, and the message at the bottom tells you which.

**Tip:** with **Merge** on, snap the shape's corners onto the face's own
corners or edges. The shape then shares those edges with the rest of the
face, for example a square tucked into the corner of a panel.

**Draw on Face or the Knife (`K`)?** Use Draw on Face for exact, clean
shapes inside **one** flat face. Use the Knife for cuts across several
faces, open cuts from edge to edge, or cutting through to the back.

### Draw for Bool

Draws a shape and **pulls it in or out** to cut a hole or add a block.
The result is a separate **cutter object** with a live Boolean, so you
can keep adjusting it (deeper, angled, moved) before you make it
permanent.

The three buttons (the **Bool** row) decide what happens:

| Button | Push into the surface | Pull out of it |
|---|---|---|
| **Auto** | Cuts a hole / pocket | Adds a block |
| **Cut** | Cuts a pocket | Cuts away anything above the surface |
| **Extrude** | Fills: e.g. the part of a shape hanging over the edge gets filled down | Adds a raised block |

**Both Directions** (the toggle under the buttons, or `B` while pulling)
pulls the same distance to both sides of the plane. It's like a CAD
"symmetric" extrude, e.g. a slot cut through a wall from its middle.

#### Step by step

1. **Press Auto, Cut or Extrude.** The header asks you to pick where to
   draw, and nothing can be drawn yet:
   - **Click a face**: you draw on that face's plane. Unlike Draw on Face,
     the shape **may go past the face's edges**. The face under the mouse
     is highlighted.
   - **`Space`, or click empty space**: you draw on the view plane through
     the 3D cursor.
   - `Esc` / right-click cancels.
2. **Draw the shape** as usual. All snaps and typed sizes work.
   Rectangles and circles move on by themselves after the second click;
   for Points, press `Enter`.
3. **Move the mouse to pull** the shape. The cut or add shows live.

   | Key | Action |
   |---|---|
   | Type a number | Exact depth, in the direction you're pulling. `-` flips it, `Backspace` / `Esc` stop typing |
   | `A` | Align: hover any vertex of the mesh to pull to exactly its height (green dot + guide line) |
   | `Ctrl` (hold) | Depth snaps to the Grid Size |
   | `Tab` | Switch Auto / Cut / Extrude |
   | `B` | Both Directions on / off |
   | `LMB` / `Enter` | Done |
   | `RMB` / `Esc` | Cancel (nothing is left behind) |

   If you're looking straight down onto the face, pull with mouse **up =
   out**, **down = in**.
4. **Fine-tune in the bottom-left panel:** Mode, the exact **Depth** (+ =
   out, - = in) and Both Directions. Changes rebuild the cutter
   instantly.
5. **You're now editing the cutter**, with its far end (cap) selected:
   - `G` moves the cap, which changes the depth.
   - `S` scales the cap, which tapers the walls into an **angled cut** (a
     countersink, a chamfered pocket).
   - Grab any vertex or edge of the cutter to reshape it.

   The Boolean updates as you edit.
6. Press **Back to Mesh** (Bool Cutters panel or `Shift+Q`) to keep
   modeling. You can stack several cutters before applying them.

### Bool Cutters

This panel appears when you're on a cutter, or on a mesh that has
cutters.

**When a cutter is active:**

| Button | What it does |
|---|---|
| **Difference / Union / Intersect** | Change what the cutter does, any time |
| **Solver** | Boolean solver. `Exact` (default) is the most reliable; the others (`Float` / `Fast`, and `Manifold` in newer Blender) are quicker on heavy meshes |
| **Edit Cutter** | Edit this cutter's shape |
| **Back to Mesh** | Return to editing your mesh |
| **Apply Bool** | Make this cut / add permanent and delete the cutter |
| **Delete Cutter** | Throw the cutter away **without** applying; the mesh goes back to how it was |

**When the mesh is active**, it lists all its cutters. Each row has:

- ✎ to edit that cutter
- 👁 to hide its effect for a moment
- ✕ to delete it

**Apply All Bools** applies every cutter at once.

**Where the cutters live:** each cutter is named after what it does
(`Cut`, `Add`, `Intersect`, then `.001` …) and kept in a **VT Cutters**
collection inside your mesh's collection. Cutters:

- are parented to your mesh, so they move with it
- show as wireframes
- are hidden in renders

The collection disappears when its last cutter is applied or deleted.

---

## 4. Face Projection

Turns the view to look **straight at** a plane, so you can work on
slanted surfaces as if they were flat.

**Select** one of these:

| Selection | Plane used |
|---|---|
| 3 vertices | The plane through them |
| 2 edges | The best-fit plane through them |
| 1 or more faces | The faces' direction (you look at their front) |
| More vertices | The best-fit plane through all of them |

**Then press:**

| Button | What it does |
|---|---|
| **Align View to Selection** | Looks straight at the plane, centers on it and switches to orthographic |
| **Align View + Cursor** | The same, and puts the 3D cursor on the plane, rotated to match |
| **Align + Draw** | Aligns, places the cursor and starts **Draw** right away. The fastest way to draw exactly on a slanted plane |
| **Back to Previous View** | Returns to the view before aligning. It remembers several steps |
| **Flatten to Plane** | Moves all selected vertices onto their best-fit plane. Fixes faces that are slightly bent |

Options in the bottom-left panel:

- **Roll**: how the view is turned.
  - **World Up** (default): world Z stays up.
  - **Edge Horizontal**: the first two clicked vertices, or the longest
    edge, lie flat on screen.
  - **Keep Current**.
- **Flip**: look from the other side.
- **Center View**.
- **Orthographic**.
- **Move 3D Cursor**.

---

## 5. The Shift+Q menu

In Edit Mode, `Shift+Q` opens every action in columns:

| Column | Contains |
|---|---|
| **Average Vertex** | Every Fix Last, Whole Chain and Extrude variant by name, plus Preview / Apply for the panel's action |
| **Draw With Vertex** | Draw Points, Rectangle, Circle, Edges Only, on Surface; Draw on Face; Draw for Bool (Auto / Cut / Extrude) |
| **Face Projection** | All alignment buttons, Back to Previous View, Flatten to Plane |
| **Bool Cutters** | Edit Cutter, Back to Mesh, Apply Bool, Delete Cutter. Only shown when there are cutters |

Menu entries ignore the panel's Fit switch: each says exactly what it
does. To change the key: `Edit > Preferences > Keymap`, search
`VIEW3D_MT_vertex_tools`. The menu is also at `Vertex` menu > `Vertex
Tools`.

---

## 6. Recipes

**A perfect bolt circle of 8 holes**
1. Draw a Circle with 8 sides (**Sides** = 8, Result = Edges Only).
2. Or, if you have some holes already: select them, set Fit = Circle,
   then use **Full Circle** (to space them all the way round) or
   **Extrude New Vertex** with a Count (to add more).

**Straighten a wonky edge loop**
1. `Alt+click` the loop.
2. Fit = Line for a straight row, or Circle for a ring.
3. Press **Fix Whole Chain**.

**A 20 × 10 mm window in a slanted wall**
1. Set the scene units to millimeters.
2. Select the wall face and press **Align View to Selection**.
3. Choose Rectangle, press **Draw on Face**, then click the face at the
   window's first corner.
4. Type `20`, `Tab`, `10`, `Enter`.
5. In the bottom-left panel, choose **Cut In** or **Auto-Bridge**.

**A 5 mm deep pocket with angled walls**
1. Press **Cut** and click the top face.
2. Draw a rectangle.
3. Push the mouse in, type `5`, then `Enter`.
4. You're now editing the cutter with its bottom cap selected. Press `S`
   and scale it down a little: the walls slope.
5. Press **Back to Mesh**. Later, press **Apply Bool** when it's final.

**A rib exactly as tall as an existing feature**
1. Press **Extrude** and click the base face.
2. Draw the rib's outline.
3. While pulling, hover a vertex on top of the existing feature. With
   Align (`A`) on, the depth snaps to its height.
4. Click to confirm.

**Line up a new point with an old vertex**
1. While drawing, hover the old vertex for a moment so it gets a yellow
   dot.
2. Move away: when the cursor is level with it, a cyan guide appears and
   the point snaps to that height.

---

## 7. Troubleshooting

| Message / problem | What to do |
|---|---|
| *Can't find the chain order* | The selection branches (a T, a grid, two separate rows). Select one row or ring only, or click the vertices one by one |
| *This is a closed loop, use the circle* | Rings only work with Fit = Circle |
| *Which end? Shift+click the end vertex…* | Extrude needs to know which end to grow from: `Shift+click` that end vertex so it's the active one |
| *This is a closed loop, there is no end to extend* | You can't extrude a ring. Select an open row |
| *No active vertex. Select vertices one by one…* | Fix Last needs a last-clicked vertex: click the references, then `Shift+click` the target last |
| *…needs at least 3 other vertices* | Curve and Circle need 3 reference points; Line needs 2 |
| *The points are on one line, there is no circle to follow* | The vertices are in a straight row: use Fit = Line |
| *You are drawing on empty space* (Draw on Face) | Click on a face of the mesh you're editing. For empty space, use Draw or Draw for Bool |
| *The shape goes outside the face* | Draw on Face shapes must stay inside the face. Use Draw for Bool to go past the edge |
| *That vertex is already part of this shape* | With Merge on, each vertex can be used once per shape. Click somewhere else, or turn Merge off (`M`) |
| Snapping ignores a vertex | It's hidden behind something. Turn on X-ray (`Alt+Z`) |
| The typed number gives a strange size | Numbers use the scene's units: check `Scene Properties > Units` |
| The Boolean looks broken or has holes | Try the other **Solver** in the Bool Cutters panel, or pull the cutter slightly deeper so it doesn't end exactly on a face |
| The Bool Cutters panel isn't showing | It shows only when the active object is a cutter or has cutters |
| Changes in the file don't show up in Blender | Disable and re-enable the add-on, or restart Blender |
