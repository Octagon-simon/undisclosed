#!/bin/bash
# ocr_swift.sh — Extract text + bounding boxes from an image using macOS Vision.
# Usage: ./ocr_swift.sh /path/to/screenshot.png
# Prints lines: "text || x,y,w,h" (normalized 0..1 coords).
set -euo pipefail

SRC="${1:?usage: ocr_swift.sh <image>}"
SWIFT_BIN="${TMPDIR:-/tmp}/ocr_swift_runner"
mkdir -p "$SWIFT_BIN"

# Vision supports png/jpeg/heic/tiff.
cat > "$SWIFT_BIN/ocr.swift" <<'EOF'
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    print("no image")
    exit(1)
}
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("cannot load image")
    exit(1)
}
let request = VNRecognizeTextRequest { req, _ in
    guard let observations = req.results as? [VNRecognizedTextObservation] else { return }
    for obs in observations {
        guard let candidate = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        // Vision origin is bottom-left; flip Y to top-left for CSS-like layout.
        let y = 1.0 - b.origin.y - b.size.height
        let s = String(format: "%.4f,%.4f,%.4f,%.4f", b.origin.x, y, b.size.width, b.size.height)
        print("\(candidate.string) || \(s)")
    }
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["en-US"]

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([request])
EOF

swift "$SWIFT_BIN/ocr.swift" "$SRC"
