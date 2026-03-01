#!/usr/bin/env python3
"""
UNIVAC4K — Overstrike ASCII Art Generator

Converts images to multi-pass overstriked ASCII art for teletype output.
Each line can be printed multiple times (carriage return without line feed)
to build up ink density, approximating grayscale images.

Uses pixel-level glyph matching within each character cell to maximize
spatial fidelity.
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TTY35TD-Book.ttf")
PRINTABLE_CHARS = [chr(c) for c in range(0x20, 0x7F)]


def rasterize_font(font_path, point_size=20):
    """Render all printable ASCII characters as grayscale ink maps."""
    font = ImageFont.truetype(font_path, point_size)

    cell_w = int(font.getlength("M"))
    ascent, descent = font.getmetrics()
    cell_h = ascent + descent

    glyphs = {}
    densities = {}

    for ch in PRINTABLE_CHARS:
        img = Image.new("L", (cell_w, cell_h), 255)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), ch, font=font, fill=0)
        # Ink values: 0.0 = no ink (white), 1.0 = full ink (black)
        arr = 1.0 - (np.array(img, dtype=np.float32) / 255.0)
        glyphs[ch] = arr
        densities[ch] = float(arr.mean())

    return glyphs, densities, cell_w, cell_h, font


def load_and_prepare_image(image_path, target_cols, cell_w, cell_h):
    """Load image and resize to full pixel resolution (cell_w * cols, cell_h * rows)."""
    img = Image.open(image_path).convert("L")
    orig_w, orig_h = img.size

    # Calculate target rows preserving aspect ratio
    target_rows = int((target_cols * cell_w * orig_h) / (cell_h * orig_w))
    target_rows = max(1, target_rows)

    # Resize to full sub-cell resolution: each character cell maps to cell_w x cell_h pixels
    full_w = target_cols * cell_w
    full_h = target_rows * cell_h
    img_resized = img.resize((full_w, full_h), Image.LANCZOS)
    pixels = np.array(img_resized, dtype=np.float32)

    # Convert to ink density: 0=no ink, 1=full ink
    target_ink = 1.0 - (pixels / 255.0)

    return target_ink, target_rows


def _accumulate_ink(current, glyph):
    """Probabilistic ink accumulation: 1 - (1 - current)(1 - glyph)"""
    return 1.0 - (1.0 - current) * (1.0 - glyph)


def generate_passes_accurate(target_ink, glyphs, max_passes, cell_w, cell_h):
    """Generate overstrike passes using pixel-level spatial matching.

    Instead of matching average density, this compares the full pixel grid
    within each cell against each candidate glyph to minimize squared error.
    """
    full_h, full_w = target_ink.shape
    cols = full_w // cell_w
    rows = full_h // cell_h

    char_list = PRINTABLE_CHARS
    glyph_arrays = np.stack([glyphs[ch] for ch in char_list])  # (num_chars, cell_h, cell_w)

    result_lines = []

    for row in range(rows):
        y0 = row * cell_h
        y1 = y0 + cell_h
        passes = []

        # Extract target cells for this row: (cols, cell_h, cell_w)
        target_row = np.stack([target_ink[y0:y1, c * cell_w:(c + 1) * cell_w] for c in range(cols)])
        # Current accumulated ink per cell
        current_ink = np.zeros((cols, cell_h, cell_w), dtype=np.float32)

        for _ in range(max_passes):
            pass_chars = []

            for col in range(cols):
                target_cell = target_row[col]
                current_cell = current_ink[col]

                # Current error (sum of squared differences)
                current_error = np.sum((current_cell - target_cell) ** 2)

                if current_error < 0.01:
                    pass_chars.append(" ")
                    continue

                # Accumulate each candidate glyph onto current ink
                candidates = _accumulate_ink(current_cell, glyph_arrays)  # (num_chars, h, w)

                # Compute SSE for each candidate
                candidate_errors = np.sum((candidates - target_cell) ** 2, axis=(1, 2))

                best_idx = int(np.argmin(candidate_errors))

                if candidate_errors[best_idx] < current_error:
                    current_ink[col] = candidates[best_idx]
                    pass_chars.append(char_list[best_idx])
                else:
                    pass_chars.append(" ")

            pass_str = "".join(pass_chars)
            if pass_str.strip():
                passes.append(pass_str)

        result_lines.append(passes)

        pct = (row + 1) / rows * 100
        print(f"\rProcessing: {pct:.0f}% ({row + 1}/{rows} rows)", end="", flush=True)

    print()
    return result_lines


def generate_passes_fast(target_ink, densities, max_passes, cell_w, cell_h):
    """Generate overstrike passes using density approximation (fast mode).

    Uses per-cell average density matching instead of pixel-level comparison.
    """
    full_h, full_w = target_ink.shape
    cols = full_w // cell_w
    rows = full_h // cell_h

    char_density_pairs = sorted(densities.items(), key=lambda x: x[1])
    char_list = [p[0] for p in char_density_pairs]
    density_list = np.array([p[1] for p in char_density_pairs])

    # Compute per-cell average target density
    target_density = np.zeros((rows, cols))
    for r in range(rows):
        for c in range(cols):
            target_density[r, c] = target_ink[
                r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w
            ].mean()

    result_lines = []

    for row in range(rows):
        target_row = target_density[row]
        passes = []
        current_density = np.zeros(cols)

        for _ in range(max_passes):
            pass_chars = []

            for col in range(cols):
                target_d = target_row[col]
                current_d = current_density[col]

                if target_d - current_d < 0.005:
                    pass_chars.append(" ")
                    continue

                candidate_densities = 1.0 - (1.0 - current_d) * (1.0 - density_list)
                errors = np.abs(candidate_densities - target_d)
                best_idx = int(np.argmin(errors))

                if errors[best_idx] < abs(current_d - target_d):
                    current_density[col] = candidate_densities[best_idx]
                    pass_chars.append(char_list[best_idx])
                else:
                    pass_chars.append(" ")

            pass_str = "".join(pass_chars)
            if pass_str.strip():
                passes.append(pass_str)

        result_lines.append(passes)

        pct = (row + 1) / rows * 100
        print(f"\rProcessing (fast): {pct:.0f}% ({row + 1}/{rows} rows)", end="", flush=True)

    print()
    return result_lines


def render_preview(result_lines, glyphs, cell_w, cell_h, output_path):
    """Render the overstrike result back into a preview image."""
    num_rows = len(result_lines)
    num_cols = max(
        (max(len(p) for p in passes) if passes else 0) for passes in result_lines
    )
    if num_cols == 0:
        num_cols = 1

    img_w = num_cols * cell_w
    img_h = num_rows * cell_h
    ink = np.zeros((img_h, img_w), dtype=np.float32)

    for row_idx, passes in enumerate(result_lines):
        y = row_idx * cell_h
        for pass_str in passes:
            for col_idx, ch in enumerate(pass_str):
                if ch == " ":
                    continue
                x = col_idx * cell_w
                glyph = glyphs.get(ch)
                if glyph is not None:
                    gh, gw = glyph.shape
                    region = ink[y : y + gh, x : x + gw]
                    ink[y : y + gh, x : x + gw] = _accumulate_ink(region, glyph)

    img_array = ((1.0 - ink) * 255).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(img_array)
    _, ext = os.path.splitext(output_path)
    if not ext:
        output_path += ".png"
    img.save(output_path)
    print(f"Preview saved to: {output_path}")


def build_output(result_lines, width, max_passes):
    """Build the JSON output structure."""
    lines = []
    for i, passes in enumerate(result_lines):
        lines.append({"line": i, "passes": passes})

    return {
        "width": width,
        "height": len(result_lines),
        "max_passes": max_passes,
        "lines": lines,
    }


def main():
    parser = argparse.ArgumentParser(
        description="UNIVAC4K — Overstrike ASCII Art Generator",
        epilog="Converts images to multi-pass overstriked ASCII art for teletype output.",
    )
    parser.add_argument("image", help="Path to input image file")
    parser.add_argument(
        "--output", "-o", default="output.json", help="Output JSON file path (default: output.json)"
    )
    parser.add_argument(
        "--max-passes", "-p", type=int, default=6,
        help="Maximum number of overstrike passes per line (default: 6)",
    )
    parser.add_argument(
        "--width", "-w", type=int, default=72, help="Output width in characters (default: 72)"
    )
    parser.add_argument("--preview", default=None, help="Path to save a preview PNG of the result")
    parser.add_argument(
        "--fast", action="store_true",
        help="Use fast density approximation instead of pixel-accurate compositing",
    )
    parser.add_argument(
        "--font-size", type=int, default=20, help="Font rendering size in points (default: 20)"
    )

    args = parser.parse_args()

    if not os.path.isfile(args.image):
        print(f"Error: Image file not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(FONT_PATH):
        print(f"Error: Font file not found: {FONT_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading font: {FONT_PATH} at {args.font_size}pt")
    glyphs, densities, cell_w, cell_h, _ = rasterize_font(FONT_PATH, args.font_size)
    print(f"Cell dimensions: {cell_w}x{cell_h} pixels")
    print(f"Characters loaded: {len(glyphs)}")

    sorted_by_density = sorted(densities.items(), key=lambda x: x[1], reverse=True)
    print("Densest characters: " + " ".join(f"{ch}({d:.2f})" for ch, d in sorted_by_density[:10]))

    max_single = sorted_by_density[0][1]
    max_theoretical = 1.0 - (1.0 - max_single) ** args.max_passes
    print(f"Max single-char density: {max_single:.3f}")
    print(f"Theoretical max with {args.max_passes} passes: {max_theoretical:.3f}")

    print(f"\nLoading image: {args.image}")
    target_ink, target_rows = load_and_prepare_image(args.image, args.width, cell_w, cell_h)
    print(f"Output dimensions: {args.width} cols x {target_rows} rows")
    print(f"Image rasterized to: {target_ink.shape[1]}x{target_ink.shape[0]} pixels")
    print(f"Max passes: {args.max_passes}")
    print(f"Mode: {'fast (density approximation)' if args.fast else 'accurate (pixel-level matching)'}")
    print()

    if args.fast:
        result_lines = generate_passes_fast(target_ink, densities, args.max_passes, cell_w, cell_h)
    else:
        result_lines = generate_passes_accurate(target_ink, glyphs, args.max_passes, cell_w, cell_h)

    total_passes = sum(len(p) for p in result_lines)
    max_used = max(len(p) for p in result_lines) if result_lines else 0
    print(f"\nTotal passes across all lines: {total_passes}")
    print(f"Maximum passes used on a single line: {max_used}")

    output_data = build_output(result_lines, args.width, args.max_passes)
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"Output saved to: {args.output}")

    if args.preview:
        print("\nRendering preview...")
        render_preview(result_lines, glyphs, cell_w, cell_h, args.preview)


if __name__ == "__main__":
    main()
