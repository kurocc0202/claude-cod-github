#!/usr/bin/env python3
"""Generate the 三井作造 character brush holder (筆筒) as a printable STL.

Four faces, one character each -- 三 front, 井 right, 作 back, 造 left -- built
from slab strokes that run into the corner posts, so the characters are the
wall rather than a decoration on it. Inside: a floor, three compartments.

The whole body is a union of axis-aligned boxes. Each box is written as its
own closed shell and the slicer unions them, which avoids needing a 3D boolean
and keeps every surface exactly axis-aligned.

Every vertical dimension is snapped to the layer height (0.2 mm by default),
so no stroke edge lands between two layers and nothing is thinner than one.

    python3 brush_holder.py                        # -> brush_holder.stl
    python3 brush_holder.py --preview holder.png   # render all four faces
    python3 brush_holder.py --layer 0.16

Standard library only.
"""

import argparse
import math
import struct
import sys
import zlib

# ---------------------------------------------------------------------------
# Body. Millimetres.
# ---------------------------------------------------------------------------

SIZE = 80.0            # outer width and depth of the body
HEIGHT = 95.0
PLINTH_H = 8.0         # solid base; its top face is the floor
PLINTH_OVER = 2.0      # how far the plinth steps out past the body
PLINTH_STEP = 4.0      # height of the stepped-out part
RIM_H = 7.0            # continuous frame around the top
RIM_W = 8.0
POST = 8.0             # square corner posts
WALL = 8.0             # how far a stroke stands proud of the inside

DIVIDER = 5.0          # internal divider thickness
DIVIDER_X = -6.0       # front-to-back divider, offset from centre
DIVIDER_Y = 4.0        # left-to-right divider, right half only

MIN_LAYERS = 2         # nothing shorter than this many layers

# Glyph grid: 16 x 16 cells across the face and up the character band.
GRID = 16
GLYPH_BOTTOM = PLINTH_H
GLYPH_TOP = HEIGHT - RIM_H

# Strokes are given as (u0, v0, u1, v1) in grid cells, origin bottom left of
# the face as seen from outside. The corner posts cover u 0.0-1.6 and
# 14.4-16.0, so a stroke reaching those is structurally tied in.
GLYPHS = {
    "三": [
        (0.0, 11.4, 16.0, 13.0),
        (1.2, 7.0, 14.8, 8.6),
        (0.0, 1.8, 16.0, 3.8),
    ],
    "井": [
        (0.0, 10.6, 16.0, 12.2),
        (0.0, 5.0, 16.0, 6.6),
        (4.2, 1.0, 5.8, 15.2),
        (9.6, 1.0, 11.2, 15.2),
    ],
    "作": [
        (1.6, 1.0, 3.2, 13.6),      # 亻 vertical
        (0.0, 11.0, 1.8, 13.6),     # 亻 head, into the left post
        (4.0, 12.4, 6.0, 14.6),     # 乍 top stroke
        (4.0, 11.0, 14.8, 12.6),    # 乍 first horizontal
        (8.0, 1.4, 9.6, 12.6),      # 乍 long vertical
        (5.6, 7.6, 14.0, 9.2),
        (5.6, 4.4, 14.0, 6.0),
        (5.6, 1.4, 16.0, 3.0),      # into the right post
    ],
    "造": [
        (8.4, 13.2, 10.2, 16.0),    # 告 top stub
        (5.6, 11.8, 13.6, 13.4),
        (8.4, 9.0, 10.2, 13.4),
        (4.6, 7.6, 14.8, 9.2),      # 告 long horizontal, into the right post
        (6.4, 3.6, 8.0, 7.8),       # 口 hangs off that horizontal
        (12.0, 3.6, 13.6, 7.8),
        (6.4, 3.6, 13.6, 5.2),
        (1.0, 13.0, 2.8, 15.0),     # 辶 dot, into the left post
        (1.0, 8.0, 3.0, 11.6),      # 辶 stem, into the left post
        (0.0, 1.0, 15.0, 2.8),      # 辶 sweep, clear of 口 above
    ],
}

# Face order going round the body, each with the outward axis and the
# direction the glyph reads in when you stand in front of it.
FACES = [
    ("三", "front", (0.0, -1.0), (1.0, 0.0)),
    ("井", "right", (1.0, 0.0), (0.0, 1.0)),
    ("作", "back", (0.0, 1.0), (-1.0, 0.0)),
    ("造", "left", (-1.0, 0.0), (0.0, -1.0)),
]


def snap(value, layer):
    """Nearest layer boundary. Not Python's round(), which is banker's."""
    return math.floor(value / layer + 0.5) * layer


# ---------------------------------------------------------------------------
# Mesh
# ---------------------------------------------------------------------------

class Mesh:
    def __init__(self, layer):
        self.vertices = []
        self.triangles = []
        self.layer = layer
        self.boxes = 0

    def box(self, x0, y0, z0, x1, y1, z1):
        """One closed rectangular shell. Heights snap to the layer grid."""
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        z0, z1 = min(z0, z1), max(z0, z1)

        z0 = snap(z0, self.layer)
        z1 = snap(z1, self.layer)
        if z1 - z0 < MIN_LAYERS * self.layer - 1e-9:
            z1 = z0 + MIN_LAYERS * self.layer
        if x1 - x0 < 1e-6 or y1 - y0 < 1e-6:
            return

        base = len(self.vertices)
        for z in (z0, z1):
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                self.vertices.append((x, y, z))

        def quad(a, b, c, d):
            self.triangles.append((base + a, base + b, base + c))
            self.triangles.append((base + a, base + c, base + d))

        quad(0, 3, 2, 1)          # bottom, normal -z
        quad(4, 5, 6, 7)          # top, normal +z
        quad(0, 1, 5, 4)          # -y
        quad(1, 2, 6, 5)          # +x
        quad(2, 3, 7, 6)          # +y
        quad(3, 0, 4, 7)          # -x
        self.boxes += 1

    def volume_mm3(self):
        total = 0.0
        for a, b, c in self.triangles:
            ax, ay, az = self.vertices[a]
            bx, by, bz = self.vertices[b]
            cx, cy, cz = self.vertices[c]
            total += (ax * (by * cz - bz * cy)
                      - ay * (bx * cz - bz * cx)
                      + az * (bx * cy - by * cx))
        return total / 6.0

    def check_shells_closed(self):
        """Each shell must be closed: every directed edge paired with its twin.

        The shells overlap each other on purpose -- that is the union -- so
        this checks closure, not that the result is a single manifold.
        """
        edges = set()
        for a, b, c in self.triangles:
            for e in ((a, b), (b, c), (c, a)):
                if e in edges:
                    raise ValueError("edge %r repeated with the same winding" % (e,))
                edges.add(e)
        for a, b in edges:
            if (b, a) not in edges:
                raise ValueError("edge %r has no twin: open shell" % ((a, b),))
        return len(edges) // 2


# ---------------------------------------------------------------------------
# Face layout
# ---------------------------------------------------------------------------

def cell_size():
    return SIZE / GRID, (GLYPH_TOP - GLYPH_BOTTOM) / GRID


def stroke_boxes(mesh, char, outward, read, layer):
    """Place one character's strokes on its face."""
    cu, cv = cell_size()
    half = 0.5 * SIZE
    ox, oy = outward
    rx, ry = read

    for u0, v0, u1, v1 in GLYPHS[char]:
        # Along the face, in millimetres from the centre.
        a0 = u0 * cu - half
        a1 = u1 * cu - half
        z0 = GLYPH_BOTTOM + v0 * cv
        z1 = GLYPH_BOTTOM + v1 * cv

        # Corner of the face, and the inward depth of the slab.
        fx0 = ox * half + rx * a0
        fy0 = oy * half + ry * a0
        fx1 = ox * half + rx * a1
        fy1 = oy * half + ry * a1

        x0 = min(fx0, fx1) - (WALL if ox > 0 else 0.0)
        x1 = max(fx0, fx1) + (WALL if ox < 0 else 0.0)
        y0 = min(fy0, fy1) - (WALL if oy > 0 else 0.0)
        y1 = max(fy0, fy1) + (WALL if oy < 0 else 0.0)
        mesh.box(x0, y0, z0, x1, y1, z1)


def connectivity_report(char):
    """Strokes that are not tied to a post, the plinth or the rim.

    Two rectangles count as joined when they overlap on both axes. Anchors are
    the corner posts and the bands the plinth and rim occupy.
    """
    cu, _ = cell_size()
    post_cells = POST / cu
    rects = list(GLYPHS[char])
    anchors = [
        (0.0, 0.0, post_cells, float(GRID)),               # left post
        (GRID - post_cells, 0.0, float(GRID), float(GRID)),  # right post
        (0.0, -1.0, float(GRID), 0.0),                     # plinth
        (0.0, float(GRID), float(GRID), GRID + 1.0),       # rim
    ]
    items = rects + anchors
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    def touches(p, q):
        return (min(p[2], q[2]) - max(p[0], q[0]) > 1e-9
                and min(p[3], q[3]) - max(p[1], q[1]) > 1e-9)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if touches(items[i], items[j]):
                union(i, j)

    anchored = {find(len(rects) + k) for k in range(len(anchors))}
    return [i for i in range(len(rects)) if find(i) not in anchored]


# ---------------------------------------------------------------------------

def build(layer):
    mesh = Mesh(layer)
    half = 0.5 * SIZE
    inner = half - WALL

    # Plinth: a stepped-out slab, then a flush block up to the floor.
    over = half + PLINTH_OVER
    mesh.box(-over, -over, 0.0, over, over, PLINTH_STEP)
    mesh.box(-half, -half, PLINTH_STEP, half, half, PLINTH_H)

    # Corner posts, full height.
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            x = sx * half
            y = sy * half
            mesh.box(x, y, PLINTH_H, x - sx * POST, y - sy * POST, HEIGHT)

    # Characters.
    for char, _name, outward, read in FACES:
        stroke_boxes(mesh, char, outward, read, layer)

    # Top rim: a closed frame so the mouth cannot splay.
    mesh.box(-half, -half, HEIGHT - RIM_H, half, -half + RIM_W, HEIGHT)
    mesh.box(-half, half - RIM_W, HEIGHT - RIM_H, half, half, HEIGHT)
    mesh.box(-half, -half, HEIGHT - RIM_H, -half + RIM_W, half, HEIGHT)
    mesh.box(half - RIM_W, -half, HEIGHT - RIM_H, half, half, HEIGHT)

    # Dividers: one full depth, one across the right half only.
    top = HEIGHT - RIM_H
    mesh.box(DIVIDER_X - 0.5 * DIVIDER, -inner, PLINTH_H,
             DIVIDER_X + 0.5 * DIVIDER, inner, top)
    mesh.box(DIVIDER_X + 0.5 * DIVIDER, DIVIDER_Y - 0.5 * DIVIDER, PLINTH_H,
             inner, DIVIDER_Y + 0.5 * DIVIDER, top)

    return mesh


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_stl(mesh, path, name="mitsui_brush_holder"):
    with open(path, "wb") as fh:
        fh.write(name.encode("ascii", "replace")[:79].ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(mesh.triangles)))
        for a, b, c in mesh.triangles:
            ax, ay, az = mesh.vertices[a]
            bx, by, bz = mesh.vertices[b]
            cx, cy, cz = mesh.vertices[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            fh.write(struct.pack("<12fH", nx / n, ny / n, nz / n,
                                 ax, ay, az, bx, by, bz, cx, cy, cz, 0))


def _png(path, width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))


def _shade(mesh, tri, light):
    a, b, c = tri
    ax, ay, az = mesh.vertices[a]
    bx, by, bz = mesh.vertices[b]
    cx, cy, cz = mesh.vertices[c]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    lam = max(0.0, (nx * light[0] + ny * light[1] + nz * light[2]) / n)
    return 0.26 + 0.74 * lam ** 0.8


def _render_view(mesh, width, height, azimuth, elevation, buf, ox, oy, canvas_w):
    ca, sa = math.cos(math.radians(azimuth)), math.sin(math.radians(azimuth))
    ce, se = math.cos(math.radians(elevation)), math.sin(math.radians(elevation))

    def view(p):
        x, y, z = p
        x, y = x * ca + y * sa, -x * sa + y * ca
        return x, z * ce - y * se, -(y * ce + z * se)

    pts = [view(v) for v in mesh.vertices]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = 0.86 * min(width, height) / span
    cx = 0.5 * (max(xs) + min(xs))
    cy = 0.5 * (max(ys) + min(ys))
    screen = [((p[0] - cx) * scale + width * 0.5,
               height * 0.5 - (p[1] - cy) * scale, p[2]) for p in pts]

    depth = [-1e18] * (width * height)
    light = (-0.40, 0.48, 0.78)

    for tri in mesh.triangles:
        a, b, c = tri
        x0, y0, z0 = screen[a]
        x1, y1, z1 = screen[b]
        x2, y2, z2 = screen[c]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if area >= -1e-9:
            continue
        shade = _shade(mesh, tri, light)
        base = 214.0 * shade
        colour = (int(min(255.0, base)), int(min(255.0, base)),
                  int(min(255.0, base + 3.0)))

        lo_x = max(0, int(min(x0, x1, x2)))
        hi_x = min(width - 1, int(max(x0, x1, x2)) + 1)
        lo_y = max(0, int(min(y0, y1, y2)))
        hi_y = min(height - 1, int(max(y0, y1, y2)) + 1)
        if lo_x > hi_x or lo_y > hi_y:
            continue
        inv = 1.0 / area
        for py in range(lo_y, hi_y + 1):
            sy = py + 0.5
            for px in range(lo_x, hi_x + 1):
                sx = px + 0.5
                w0 = ((x1 - sx) * (y2 - sy) - (x2 - sx) * (y1 - sy)) * inv
                if w0 < 0.0:
                    continue
                w1 = ((x2 - sx) * (y0 - sy) - (x0 - sx) * (y2 - sy)) * inv
                if w1 < 0.0:
                    continue
                w2 = 1.0 - w0 - w1
                if w2 < 0.0:
                    continue
                zz = w0 * z0 + w1 * z1 + w2 * z2
                idx = py * width + px
                if zz <= depth[idx]:
                    continue
                depth[idx] = zz
                o = ((oy + py) * canvas_w + ox + px) * 3
                buf[o] = colour[0]
                buf[o + 1] = colour[1]
                buf[o + 2] = colour[2]


def _fill(buf, canvas_w, x0, y0, x1, y1, colour):
    for py in range(max(0, int(y0)), max(0, int(y1))):
        row = py * canvas_w
        for px in range(max(0, int(x0)), max(0, int(x1))):
            o = (row + px) * 3
            buf[o], buf[o + 1], buf[o + 2] = colour


def _render_face_map(char, buf, canvas_w, ox, oy, tile):
    """Flat elevation of one face: the strokes as they read from outside.

    A straight-on 3D view of a hollow box shows the far wall through the gaps,
    which hides the character. This draws only the near face, so the glyph is
    actually checkable.
    """
    pad = 0.10 * tile
    span = tile - 2 * pad
    cu, _ = cell_size()
    post_cells = POST / cu
    plinth_cells = GRID * PLINTH_H / (GLYPH_TOP - GLYPH_BOTTOM)
    rim_cells = GRID * RIM_H / (GLYPH_TOP - GLYPH_BOTTOM)

    total_v = plinth_cells + GRID + rim_cells
    sx = span / GRID
    sy = span / total_v

    def rect(u0, v0, u1, v1, colour):
        # v is measured in glyph cells from the bottom of the character band.
        _fill(buf, canvas_w,
              ox + pad + u0 * sx,
              oy + pad + (total_v - plinth_cells - v1) * sy,
              ox + pad + u1 * sx,
              oy + pad + (total_v - plinth_cells - v0) * sy,
              colour)

    frame = (206, 206, 210)
    ink = (34, 34, 36)

    rect(0.0, -plinth_cells, GRID, 0.0, ink)                 # plinth
    rect(0.0, GRID, GRID, GRID + rim_cells, ink)             # rim
    rect(0.0, 0.0, post_cells, GRID, frame)                  # posts
    rect(GRID - post_cells, 0.0, GRID, GRID, frame)
    for u0, v0, u1, v1 in GLYPHS[char]:
        rect(u0, v0, u1, v1, ink)


def render_preview(mesh, path, tile=440):
    """Four flat face elevations on top, a three-quarter view underneath."""
    cols = 4
    width = tile * cols
    height = tile * 2
    bg = (245, 245, 247)
    buf = bytearray(bg[i % 3] for i in range(width * height * 3))

    for i, (char, _name, _o, _r) in enumerate(FACES):
        _render_face_map(char, buf, width, i * tile, 0, tile)

    _render_view(mesh, tile * 2, tile, 34.0, 24.0, buf, tile, tile, width)
    _png(path, width, height, buf)


# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layer", type=float, default=0.2,
                   help="printer layer height (mm); every vertical dimension "
                        "is snapped to it")
    p.add_argument("--preview", metavar="PNG",
                   help="render the four faces and a three-quarter view")
    p.add_argument("-o", "--out", default="brush_holder.stl")
    args = p.parse_args(argv)

    if args.layer <= 0.0:
        print("error: layer height must be positive", file=sys.stderr)
        return 2

    problems = []
    for char, name, _o, _r in FACES:
        loose = connectivity_report(char)
        for i in loose:
            problems.append("%s (%s) stroke %d %r floats free"
                            % (char, name, i, GLYPHS[char][i]))

    mesh = build(args.layer)
    edges = mesh.check_shells_closed()
    volume = mesh.volume_mm3()
    write_stl(mesh, args.out)

    cu, cv = cell_size()
    print("%s  %.0f x %.0f x %.0f mm  (plinth %.0f x %.0f)"
          % (args.out, SIZE, SIZE, HEIGHT, SIZE + 2 * PLINTH_OVER,
             SIZE + 2 * PLINTH_OVER))
    print("  faces: " + ", ".join("%s %s" % (n, c) for c, n, _o, _r in FACES))
    print("  %d boxes, %d triangles, %d edges, every shell closed"
          % (mesh.boxes, len(mesh.triangles), edges))
    print("  layer %.2f mm; glyph cell %.2f x %.2f mm (%d layers tall)"
          % (args.layer, cu, cv, int(round(cv / args.layer))))
    print("  floor at %.1f mm, usable depth %.1f mm"
          % (PLINTH_H, HEIGHT - RIM_H - PLINTH_H))
    print("  material %.1f cm3 before union overlap"
          % (volume / 1000.0,))

    if problems:
        print("  UNSUPPORTED STROKES:")
        for line in problems:
            print("    " + line)
    else:
        print("  every stroke ties into a post, the plinth or the rim")

    print("  note: horizontal strokes bridge up to %.0f mm between posts --"
          % (SIZE - 2 * POST))
    print("        print upright, mouth up, and turn bridging on")

    if args.preview:
        render_preview(mesh, args.preview)
        print("  preview %s" % args.preview)

    return 0


if __name__ == "__main__":
    sys.exit(main())
