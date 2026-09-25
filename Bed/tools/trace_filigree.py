"""Trace the supplied raster filigree into simplified SVG polylines."""

import math
import sys
from xml.sax.saxutils import escape

import contourpy
import matplotlib.image as mpimg
import numpy as np


def _distance_to_segment(point, start, end):
    segment = end - start
    length_squared = float(segment.dot(segment))
    if length_squared <= 1e-12:
        return float(np.linalg.norm(point - start))
    amount = max(0.0, min(1.0, float((point - start).dot(segment)) / length_squared))
    return float(np.linalg.norm(point - (start + amount * segment)))


def _simplify(points, tolerance):
    if len(points) <= 2:
        return points
    distances = [
        _distance_to_segment(point, points[0], points[-1])
        for point in points[1:-1]
    ]
    if not distances or max(distances) <= tolerance:
        return np.array((points[0], points[-1]))
    split = distances.index(max(distances)) + 1
    return np.vstack(
        (_simplify(points[: split + 1], tolerance)[:-1], _simplify(points[split:], tolerance))
    )


def trace(source_path, output_path):
    image = mpimg.imread(source_path)
    rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
    gray = rgb.mean(axis=2)
    black_fraction = (gray < 0.45).mean(axis=1)
    band_rows = np.flatnonzero(
        (np.arange(gray.shape[0]) > gray.shape[0] * 0.75) & (black_fraction > 0.75)
    )
    crop_bottom = int(band_rows[0]) if len(band_rows) else gray.shape[0]
    gray = gray[2 : crop_bottom - 2, 2:-2]

    # Preserve the source resolution and treat essentially every non-white
    # pixel as engraved linework. The slight margin avoids tracing numerical
    # noise from pixels that decode as almost, but not exactly, pure white.
    ink = gray < 0.99
    ink[[0, -1], :] = False
    ink[:, [0, -1]] = False

    rows, columns = ink.shape
    generator = contourpy.contour_generator(z=ink.astype(float))
    contours = []
    for line in generator.lines(0.5):
        if len(line) < 5:
            continue
        closed = np.linalg.norm(line[0] - line[-1]) <= math.sqrt(2)
        if closed:
            line[-1] = line[0]
        simplified = _simplify(line, 0.35)
        if closed and np.linalg.norm(simplified[0] - simplified[-1]) > 1e-7:
            simplified = np.vstack((simplified, simplified[0]))
        if len(simplified) >= 4:
            contours.append(simplified)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{columns}" height="{rows}" viewBox="0 0 {columns} {rows}">',
        '<g fill="none" stroke="#000" stroke-width="0.6" stroke-linejoin="round" stroke-linecap="round">',
    ]
    point_count = 0
    for contour in contours:
        point_count += len(contour)
        points = " ".join(f"{point[0]:.3f},{point[1]:.3f}" for point in contour)
        lines.append(f'<polyline points="{escape(points)}"/>')
    lines.extend(("</g>", "</svg>"))
    with open(output_path, "w", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    print(
        f"Traced {len(contours)} contours and {point_count} points; "
        f"removed raster rows {crop_bottom}-{image.shape[0] - 1}."
    )


if __name__ in ("__main__", "trace_filigree"):
    paths = [argument for argument in sys.argv[1:] if argument.lower().endswith((".png", ".svg"))]
    if len(paths) != 2:
        raise ValueError("Pass one PNG source and one SVG output path.")
    trace(paths[0], paths[1])
