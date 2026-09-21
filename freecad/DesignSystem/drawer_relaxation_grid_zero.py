"""Parametric drawer outline and motif-to-outline relaxed engraving."""

import math

import FreeCAD as App
import Part


def _closed_wire(points, z=0.0):
    vectors = [App.Vector(x, y, z) for x, y in points]
    vectors.append(vectors[0])
    return Part.makePolygon(vectors)


def _ornamental_outline(
    width, height, edge, side_wave, vertical_wave, slide_strip_width=0.0, z=0.0
):
    """Return a symmetric, gently scalloped closed outline."""
    samples = 48
    points = []

    # Bottom, right, top, and left are sampled separately so the corners close
    # exactly while retaining a smooth-looking CNC-friendly polyline.
    for index in range(samples + 1):
        t = index / samples
        x = edge + (width - 2 * edge) * t
        wave = math.sin(5 * math.pi * t) ** 2
        points.append((x, edge + vertical_wave * wave))
    for index in range(1, samples + 1):
        t = index / samples
        y = edge + (height - 2 * edge) * t
        distance_from_slide = abs(y - height / 2) - slide_strip_width / 2
        slide_gate = min(1.0, max(0.0, distance_from_slide / max(1.0, slide_strip_width / 2)))
        wave = math.sin(3 * math.pi * t) ** 2 * slide_gate**2
        points.append((width - edge - side_wave * wave, y))
    for index in range(1, samples + 1):
        t = index / samples
        x = width - edge - (width - 2 * edge) * t
        wave = math.sin(5 * math.pi * t) ** 2
        points.append((x, height - edge - vertical_wave * wave))
    for index in range(1, samples):
        t = index / samples
        y = height - edge - (height - 2 * edge) * t
        distance_from_slide = abs(y - height / 2) - slide_strip_width / 2
        slide_gate = min(1.0, max(0.0, distance_from_slide / max(1.0, slide_strip_width / 2)))
        wave = math.sin(3 * math.pi * t) ** 2 * slide_gate**2
        points.append((edge + side_wave * wave, y))
    return _closed_wire(points, z)


def _handle_cutout(width, height, edge, handle_width, handle_height):
    """Make an open-top, scalloped handhold cutting into the drawer front."""
    center = width / 2
    half = handle_width / 2
    top = height + 2.0
    shoulder = height - edge + 1.0
    bottom = shoulder - handle_height
    points = [(center - half, top)]
    samples = 48
    for index in range(samples + 1):
        t = index / samples
        y = shoulder - (shoulder - bottom) * t
        inward = 0.15 * half * math.sin(math.pi * t)
        flourish = 0.055 * half * math.sin(2 * math.pi * t)
        points.append((center - half + inward + flourish, y))
    for index in range(samples + 1):
        t = index / samples
        x = center - half + handle_width * t
        # A broad arch with three smaller ripples gives the grip a curved edge.
        arch = 0.20 * handle_height * (1.0 - (2.0 * t - 1.0) ** 2)
        ripple = 0.07 * handle_height * math.sin(3 * math.pi * t) ** 2
        points.append((x, bottom - arch + ripple))
    for index in range(samples, -1, -1):
        t = index / samples
        y = shoulder - (shoulder - bottom) * t
        inward = 0.15 * half * math.sin(math.pi * t)
        flourish = 0.055 * half * math.sin(2 * math.pi * t)
        points.append((center + half - inward - flourish, y))
    points.append((center + half, top))
    return Part.Face(_closed_wire(points))


def _polyline(points, z=0.0):
    vectors = []
    for x, y in points:
        point = App.Vector(x, y, z)
        if not vectors or (point - vectors[-1]).Length > 1e-7:
            vectors.append(point)
    closed = len(vectors) > 2 and (vectors[0] - vectors[-1]).Length <= 1e-7
    if closed:
        vectors.pop()
    curve = Part.BSplineCurve()
    curve.interpolate(vectors, PeriodicFlag=closed)
    return curve.toShape()


def _engraving(
    width,
    height,
    drawer_face,
    motif_source,
    motif_height,
    motif_center_y,
    transition_count,
    jacobi_iterations,
):
    """Create optionally relaxed distance-ratio level curves."""
    import contourpy
    import numpy as np
    from matplotlib.path import Path as PlotPath
    from scipy import ndimage

    transition_count = max(0, min(40, int(transition_count)))
    jacobi_iterations = max(0, min(500, int(jacobi_iterations)))

    source = motif_source.copy()
    source_box = source.BoundBox
    scale = motif_height / source_box.YLength
    transform = App.Matrix()
    transform.A11 = scale
    transform.A22 = scale
    transform.A33 = 1.0
    motif = source.transformGeometry(transform)
    motif.translate(
        App.Vector(
            width / 2 - motif.BoundBox.Center.x,
            motif_center_y - motif.BoundBox.Center.y,
            0,
        )
    )

    # Rasterize the physical drawer and motif paths onto a moderate grid.
    columns = 220
    rows = max(80, round(columns * height / width))
    x_values = np.linspace(0.0, width, columns)
    y_values = np.linspace(0.0, height, rows)
    dx = x_values[1] - x_values[0]
    dy = y_values[1] - y_values[0]
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    grid_points = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    inside = np.zeros(len(grid_points), dtype=bool)
    # XOR supports an outer wire plus any holes while remaining vectorized.
    for wire in drawer_face.Wires:
        boundary = wire.discretize(Deflection=0.5)
        polygon = np.array([(point.x, point.y) for point in boundary])
        inside ^= PlotPath(polygon, closed=True).contains_points(grid_points)
    inside = inside.reshape((rows, columns))

    domain = inside

    motif_mask = np.zeros_like(domain)
    sample_deflection = min(dx, dy) * 0.35
    for edge in motif.Edges:
        for point in edge.discretize(Deflection=sample_deflection):
            column = round(point.x / dx)
            row = round(point.y / dy)
            if 0 <= row < rows and 0 <= column < columns:
                motif_mask[row, column] = True
    motif_mask = ndimage.binary_dilation(motif_mask, iterations=1) & domain

    outer_boundary = domain & ~ndimage.binary_erosion(domain)
    distance_to_motif = ndimage.distance_transform_edt(
        ~motif_mask, sampling=(dy, dx)
    )
    distance_to_domain_edge = ndimage.distance_transform_edt(
        domain, sampling=(dy, dx)
    )
    field = distance_to_motif / np.maximum(
        1e-9, distance_to_motif + distance_to_domain_edge
    )
    field[~domain] = 1.0
    field[outer_boundary] = 1.0
    field[motif_mask] = 0.0

    active = domain & ~outer_boundary & ~motif_mask
    for _ in range(jacobi_iterations):
        average = 0.25 * (
            np.roll(field, 1, axis=0)
            + np.roll(field, -1, axis=0)
            + np.roll(field, 1, axis=1)
            + np.roll(field, -1, axis=1)
        )
        field[active] = average[active]
        field[outer_boundary] = 1.0
        field[motif_mask] = 0.0

    contour_generator = contourpy.contour_generator(
        x=x_values,
        y=y_values,
        z=np.ma.array(field, mask=~domain),
    )
    shapes = [Part.makeCompound(motif.Edges)]

    for curve_index in range(1, transition_count + 1):
        level = curve_index / (transition_count + 1)
        for line in contour_generator.lines(level):
            if len(line) < 4:
                continue
            points = [(float(point[0]), float(point[1])) for point in line]
            if math.dist(points[0], points[-1]) <= max(dx, dy) * 1.5:
                points[-1] = points[0]
            shapes.append(_polyline(points))

    pattern = Part.makeCompound(shapes)
    pattern.translate(App.Vector(0, 0, 0.15))
    return pattern


class ZeroCountRelaxationGridDrawerPlaneProxy:
    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        width = obj.FrameWidth.Value
        height = obj.FrameHeight.Value
        clearance = obj.Clearance.Value
        ply = obj.Ply.Value
        box_width = obj.DrawerBoxWidth.Value
        box_height = obj.DrawerBoxHeight.Value
        handle_width = obj.HandleWidth.Value
        handle_height = obj.HandleHeight.Value
        slide_strip_width = obj.SlideStripWidth.Value
        motif_height = obj.MotifHeight.Value
        transition_curve_count = obj.TransitionCurveCount
        jacobi_iterations = obj.JacobiIterations

        if min(width, height, ply, box_width, box_height, handle_width, handle_height) <= 0:
            raise ValueError("Drawer prototype dimensions must be positive.")
        front_edge = 2 * ply
        box_side = (width - box_width) / 2
        maximum_frame_side = max(0.5, front_edge - clearance)
        side_wave = max(0.0, box_side - clearance - maximum_frame_side)
        vertical_wave = min(12.0, max(2.0, (height - box_height) / 10))

        front_wire = _ornamental_outline(
            width,
            height,
            front_edge,
            side_wave,
            vertical_wave,
            slide_strip_width,
        )
        opening_wire = front_wire.makeOffset2D(clearance, 0, False, False, True)
        handle_cutout = _handle_cutout(
            width, height, front_edge, handle_width, handle_height
        )
        motif_center_y = (
            front_wire.BoundBox.YMin + handle_cutout.BoundBox.YMin
        ) / 2

        if obj.Kind == "FaceFrame":
            outer = Part.Face(_closed_wire([(0, 0), (width, 0), (width, height), (0, height)]))
            obj.Shape = outer.cut(Part.Face(opening_wire))
        elif obj.Kind == "DrawerFront":
            front = Part.Face(front_wire)
            obj.Shape = front.cut(handle_cutout)
        elif obj.Kind == "Engraving":
            obj.Shape = _engraving(
                width,
                height,
                Part.Face(front_wire).cut(handle_cutout),
                obj.MotifSource.Shape,
                motif_height,
                motif_center_y,
                transition_curve_count,
                jacobi_iterations,
            )
        elif obj.Kind == "DrawerBoxEnvelope":
            x = (width - box_width) / 2
            # Place the box just above the highest crest of the lower frame
            # border, retaining the same clearance used around the drawer face.
            y = front_edge + vertical_wave
            obj.Shape = _closed_wire(
                [(x, y), (x + box_width, y), (x + box_width, y + box_height), (x, y + box_height)],
                -0.15,
            )

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_drawer_plane_feature(
    part, name, label, kind, jacobi_expression
):
    feature = part.newObject("Part::FeaturePython", name)
    feature.Label = label
    feature.addProperty("App::PropertyString", "Kind", "Prototype")
    feature.Kind = kind
    for name in (
        "FrameWidth",
        "FrameHeight",
        "Clearance",
        "Ply",
        "DrawerBoxWidth",
        "DrawerBoxHeight",
        "HandleWidth",
        "HandleHeight",
        "SlideStripWidth",
        "MotifHeight",
    ):
        feature.addProperty("App::PropertyLength", name, "Parameters")
    feature.addProperty("App::PropertyInteger", "TransitionCurveCount", "Parameters")
    feature.addProperty("App::PropertyInteger", "JacobiIterations", "Parameters")
    feature.addProperty("App::PropertyLinkGlobal", "MotifSource", "Engraving")
    expressions = {
        "FrameWidth": "DrawerParameters.FaceFrameWidth",
        "FrameHeight": "DrawerParameters.FaceFrameHeight",
        "Clearance": "DrawerParameters.DrawerClearance",
        "Ply": "DrawerParameters.ply",
        "DrawerBoxWidth": "DrawerParameters.DrawerBoxWidth",
        "DrawerBoxHeight": "DrawerParameters.DrawerBoxHeight",
        "HandleWidth": "DrawerParameters.HandleWidth",
        "HandleHeight": "DrawerParameters.HandleHeight",
        "SlideStripWidth": "DrawerParameters.SlideStripWidth",
        "MotifHeight": "DrawerParameters.MotifHeight",
        "TransitionCurveCount": "DrawerParameters.TransitionCurveCount",
        "JacobiIterations": jacobi_expression,
    }
    for property_name, expression in expressions.items():
        feature.setExpression(property_name, expression)
    ZeroCountRelaxationGridDrawerPlaneProxy(feature)
    return feature
