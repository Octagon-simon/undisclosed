#!/usr/bin/env python3
"""
detect_blocks.py — lightweight UI "block" detection for screenshots.

Finds large homogeneous rectangles that likely correspond to layout regions
(nav, hero, cards, footer, etc.). Uses OpenCV connected components over a
coarse color-quantized image, in the spirit of UIED's element detection but
kept dependency-light (nothing but cv2 is required).

Usage:
    python3 detect_blocks.py /path/to/screenshot.png

Prints rectangles as:  x y width height   (pixel coords, top-left origin)
"""
import sys

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]

    try:
        import cv2
        import numpy as np
    except ImportError as e:
        print(f"[detect_blocks] OpenCV (and numpy) required: pip install opencv-python numpy — {e}")
        return 3

    img = cv2.imread(path)
    if img is None:
        print(f"[detect_blocks] cannot read {path}")
        return 3

    h, w = img.shape[:2]

    # Downscale for speed; keeps relative fidelity for block detection.
    scale = 1.0
    if max(w, h) > 1600:
        scale = 1600.0 / max(w, h)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    # Blur + color quantization creates flat regions that approximate blocks.
    blurred = cv2.bilateralFilter(img, 9, 75, 75)
    quant = np.clip((blurred // 32) * 32, 0, 255).astype(np.uint8)
    edges = cv2.Canny(quant, 40, 120)

    # Connected components of the edge map = candidate block outlines.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)

    MIN_W = max(8, int(img.shape[1] * 0.10))
    MIN_H = max(8, int(img.shape[0] * 0.06))

    print("# detected layout blocks (x y w h) — top-left origin")
    k = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        # Heuristic: keep sizable, non-edge-garbage components.
        if bw < MIN_W or bh < MIN_H:
            continue
        # skip huge frames touching all edges (usually the page border)
        if x <= 2 and y <= 2 and x + bw >= img.shape[1] - 2 and y + bh >= img.shape[0] - 2:
            continue
        k += 1
        # map back to original pixel space
        ox, oy, ow, oh = int(x / scale), int(y / scale), int(bw / scale), int(bh / scale)
        print(f"{ox} {oy} {ow} {oh}")

    if k == 0:
        print("# no blocks found (image may be flat or too small)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
