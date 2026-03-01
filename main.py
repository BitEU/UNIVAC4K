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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


def _apply_clahe(ink_array, clip_limit=2.0, grid_size=8):
    """Apply CLAHE adaptive histogram equalization to ink density array."""
    try:
        import cv2
    except ImportError:
        print("Warning: opencv-python not installed, skipping CLAHE. "
              "Install with: pip install opencv-python", file=sys.stderr)
        return ink_array

    grayscale = ((1.0 - ink_array) * 255).clip(0, 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=clip_limit,
                            tileGridSize=(grid_size, grid_size))
    equalized = clahe.apply(grayscale)
    return 1.0 - (equalized.astype(np.float32) / 255.0)


def _apply_gamma(ink_array, gamma=1.0):
    """Apply gamma correction. gamma > 1 lifts shadows (makes darks lighter)."""
    if gamma == 1.0:
        return ink_array
    luminance = 1.0 - ink_array.clip(0, 1)
    corrected = np.power(luminance, 1.0 / gamma)
    return 1.0 - corrected


def _apply_unsharp(ink_array, radius=2, amount=100):
    """Apply unsharp masking to boost edge detail using PIL."""
    if amount <= 0 or radius <= 0:
        return ink_array
    grayscale = ((1.0 - ink_array) * 255).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(grayscale)
    img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(amount), threshold=0))
    result = np.array(img, dtype=np.float32)
    return 1.0 - (result / 255.0)


def _apply_density_clamp(ink_array, density_min=0.0, density_max=1.0):
    """Linearly rescale ink density from [0, 1] to [density_min, density_max]."""
    if density_min == 0.0 and density_max == 1.0:
        return ink_array
    return density_min + ink_array.clip(0, 1) * (density_max - density_min)


def preprocess_image(target_ink, clahe_clip=0.0, clahe_grid=8, gamma=1.0,
                     unsharp_radius=0, unsharp_amount=0,
                     density_min=0.0, density_max=1.0):
    """Apply preprocessing pipeline: CLAHE -> gamma -> unsharp mask -> density clamp."""
    result = target_ink.copy()

    if clahe_clip > 0:
        result = _apply_clahe(result, clahe_clip, clahe_grid)

    if gamma != 1.0:
        result = _apply_gamma(result, gamma)

    if unsharp_amount > 0 and unsharp_radius > 0:
        result = _apply_unsharp(result, unsharp_radius, unsharp_amount)

    if density_min > 0.0 or density_max < 1.0:
        result = _apply_density_clamp(result, density_min, density_max)

    return result


def _accumulate_ink(current, glyph):
    """Probabilistic ink accumulation: 1 - (1 - current)(1 - glyph)"""
    return 1.0 - (1.0 - current) * (1.0 - glyph)


def generate_passes_accurate(target_ink, glyphs, max_passes, cell_w, cell_h,
                             dither=False, dither_strength=0.8):
    """Generate overstrike passes using pixel-level spatial matching.

    Instead of matching average density, this compares the full pixel grid
    within each cell against each candidate glyph to minimize squared error.
    """
    full_h, full_w = target_ink.shape
    cols = full_w // cell_w
    rows = full_h // cell_h

    char_list = PRINTABLE_CHARS
    glyph_arrays = np.stack([glyphs[ch] for ch in char_list])  # (num_chars, cell_h, cell_w)

    # For dithering: compute per-cell mean target densities for error diffusion
    if dither:
        cell_targets = np.zeros((rows, cols), dtype=np.float32)
        for r in range(rows):
            for c in range(cols):
                cell_targets[r, c] = target_ink[
                    r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w
                ].mean()

    result_lines = []

    for row in range(rows):
        y0 = row * cell_h
        y1 = y0 + cell_h
        passes = []

        # Extract target cells for this row: (cols, cell_h, cell_w)
        target_row = np.stack([target_ink[y0:y1, c * cell_w:(c + 1) * cell_w] for c in range(cols)])

        # If dithering, scale pixel-level targets by the dithered cell density ratio
        if dither:
            for col in range(cols):
                original_mean = target_row[col].mean()
                if original_mean > 0.001:
                    scale = np.clip(cell_targets[row, col] / original_mean, 0.0, 2.0)
                    target_row[col] = (target_row[col] * scale).clip(0, 1)

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

        # Floyd-Steinberg error diffusion after all passes for this row
        if dither:
            for col in range(cols):
                achieved = current_ink[col].mean()
                error = (cell_targets[row, col] - achieved) * dither_strength
                if col + 1 < cols:
                    cell_targets[row, col + 1] += error * 7.0 / 16.0
                if row + 1 < rows:
                    if col - 1 >= 0:
                        cell_targets[row + 1, col - 1] += error * 3.0 / 16.0
                    cell_targets[row + 1, col] += error * 5.0 / 16.0
                    if col + 1 < cols:
                        cell_targets[row + 1, col + 1] += error * 1.0 / 16.0

        result_lines.append(passes)

        pct = (row + 1) / rows * 100
        print(f"\rProcessing: {pct:.0f}% ({row + 1}/{rows} rows)", end="", flush=True)

    print()
    return result_lines


def generate_passes_fast(target_ink, densities, max_passes, cell_w, cell_h,
                         dither=False, dither_strength=0.8):
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
    target_density = np.zeros((rows, cols), dtype=np.float32)
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

        # Floyd-Steinberg error diffusion after all passes for this row
        if dither:
            for col in range(cols):
                error = (target_density[row, col] - current_density[col]) * dither_strength
                if col + 1 < cols:
                    target_density[row, col + 1] += error * 7.0 / 16.0
                if row + 1 < rows:
                    if col - 1 >= 0:
                        target_density[row + 1, col - 1] += error * 3.0 / 16.0
                    target_density[row + 1, col] += error * 5.0 / 16.0
                    if col + 1 < cols:
                        target_density[row + 1, col + 1] += error * 1.0 / 16.0

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

    # Preprocessing options
    parser.add_argument(
        "--clahe", type=float, default=0.0, metavar="CLIP",
        help="Apply CLAHE adaptive histogram equalization with given clip limit "
             "(0=off, try 2.0-4.0 for dark images)",
    )
    parser.add_argument(
        "--clahe-grid", type=int, default=8,
        help="CLAHE tile grid size (default: 8)",
    )
    parser.add_argument(
        "--gamma", type=float, default=1.0,
        help="Gamma correction: >1 lifts shadows, <1 deepens darks (default: 1.0, "
             "try 1.5-2.2 for dark images)",
    )
    parser.add_argument(
        "--sharpen", type=float, nargs=2, default=[0, 0], metavar=("RADIUS", "AMOUNT"),
        help="Unsharp mask: radius (pixels) and amount (percent, 0-500). "
             "Example: --sharpen 2 150",
    )
    parser.add_argument(
        "--density-range", type=float, nargs=2, default=[0.0, 1.0],
        metavar=("MIN", "MAX"),
        help="Clamp output density to [MIN, MAX] range (default: 0.0 1.0, "
             "try 0.02 0.85 to avoid crushing blacks)",
    )
    parser.add_argument(
        "--dither", action="store_true",
        help="Enable Floyd-Steinberg error diffusion dithering between character cells",
    )
    parser.add_argument(
        "--dither-strength", type=float, default=0.8,
        help="Dithering strength 0.0-1.0 (default: 0.8)",
    )
    parser.add_argument(
        "--enhance", action="store_true",
        help="Enable recommended preprocessing preset: CLAHE + gamma + sharpen + "
             "density clamping + dithering",
    )

    args = parser.parse_args()

    # Expand --enhance preset (individual flags still override)
    if args.enhance:
        if args.clahe == 0.0:
            args.clahe = 2.5
        if args.gamma == 1.0:
            args.gamma = 1.4
        if args.sharpen == [0, 0]:
            args.sharpen = [2, 120]
        if args.density_range == [0.0, 1.0]:
            args.density_range = [0.02, 0.85]
        args.dither = True

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

    # Apply preprocessing pipeline
    any_preprocessing = (args.clahe > 0 or args.gamma != 1.0 or
                         args.sharpen[1] > 0 or
                         args.density_range != [0.0, 1.0])
    if any_preprocessing:
        print("Preprocessing:")
        if args.clahe > 0:
            print(f"  CLAHE: clip={args.clahe}, grid={args.clahe_grid}")
        if args.gamma != 1.0:
            print(f"  Gamma: {args.gamma}")
        if args.sharpen[1] > 0:
            print(f"  Unsharp mask: radius={args.sharpen[0]}, amount={args.sharpen[1]:.0f}%")
        if args.density_range != [0.0, 1.0]:
            print(f"  Density range: [{args.density_range[0]}, {args.density_range[1]}]")
        target_ink = preprocess_image(
            target_ink,
            clahe_clip=args.clahe,
            clahe_grid=args.clahe_grid,
            gamma=args.gamma,
            unsharp_radius=args.sharpen[0],
            unsharp_amount=args.sharpen[1],
            density_min=args.density_range[0],
            density_max=args.density_range[1],
        )

    print(f"Max passes: {args.max_passes}")
    print(f"Mode: {'fast (density approximation)' if args.fast else 'accurate (pixel-level matching)'}")
    if args.dither:
        print(f"Dithering: Floyd-Steinberg (strength={args.dither_strength})")
    print()

    if args.fast:
        result_lines = generate_passes_fast(target_ink, densities, args.max_passes,
                                            cell_w, cell_h,
                                            dither=args.dither,
                                            dither_strength=args.dither_strength)
    else:
        result_lines = generate_passes_accurate(target_ink, glyphs, args.max_passes,
                                                cell_w, cell_h,
                                                dither=args.dither,
                                                dither_strength=args.dither_strength)

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
