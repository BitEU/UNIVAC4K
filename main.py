#!/usr/bin/env python3
"""
UNIVAC4K — Overstrike ASCII Art Generator

Converts images to multi-pass overstriked ASCII art for teletype output.
Each line can be printed multiple times (carriage return without line feed)
to build up ink density, approximating grayscale images.
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
    """Render all printable ASCII characters and return their bitmaps and densities."""
    font = ImageFont.truetype(font_path, point_size)

    # Determine cell dimensions from the monospaced font
    cell_w = int(font.getlength("M"))
    # Use font metrics for height
    ascent, descent = font.getmetrics()
    cell_h = ascent + descent

    glyphs = {}
    densities = {}

    for ch in PRINTABLE_CHARS:
        img = Image.new("L", (cell_w, cell_h), 255)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), ch, font=font, fill=0)
        # Convert to boolean array: True = ink
        arr = np.array(img) < 128
        glyphs[ch] = arr
        densities[ch] = arr.sum() / arr.size if arr.size > 0 else 0.0

    return glyphs, densities, cell_w, cell_h, font


def load_and_prepare_image(image_path, target_cols, cell_w, cell_h):
    """Load an image, convert to grayscale, and resize to fit the target column width."""
    img = Image.open(image_path).convert("L")
    orig_w, orig_h = img.size

    # Calculate target rows preserving aspect ratio, adjusted for character cell aspect ratio
    char_aspect = cell_w / cell_h
    img_aspect = orig_w / orig_h
    target_rows = int(target_cols / (img_aspect * char_aspect))
    target_rows = max(1, target_rows)

    # Resize image to target_cols × target_rows (one pixel per character cell)
    img_resized = img.resize((target_cols, target_rows), Image.LANCZOS)
    pixels = np.array(img_resized, dtype=np.float64)

    # Convert brightness (0=black, 255=white) to target ink density (0=no ink, 1=full ink)
    target_density = 1.0 - (pixels / 255.0)

    return target_density, target_rows


def generate_passes_accurate(target_density, glyphs, max_passes):
    """Generate overstrike passes using pixel-accurate bitmap compositing."""
    rows, cols = target_density.shape
    glyph_h, glyph_w = next(iter(glyphs.values())).shape

    # Precompute glyph arrays and their densities for fast comparison
    char_list = PRINTABLE_CHARS
    glyph_arrays = np.stack([glyphs[ch] for ch in char_list])  # (num_chars, glyph_h, glyph_w)
    total_pixels = glyph_h * glyph_w

    result_lines = []

    for row in range(rows):
        target_row = target_density[row]
        passes = []

        # Current accumulated ink per cell: array of boolean bitmaps
        current_ink = np.zeros((cols, glyph_h, glyph_w), dtype=bool)

        for pass_num in range(max_passes):
            pass_chars = []

            for col in range(cols):
                target_d = target_row[col]
                current_d = current_ink[col].sum() / total_pixels

                # If already close enough, use space
                if abs(current_d - target_d) < 0.01:
                    pass_chars.append(" ")
                    continue

                # If target is less than current (can't remove ink), use space
                if target_d <= current_d:
                    pass_chars.append(" ")
                    continue

                # Try each character: OR with current ink, measure resulting density
                candidates = current_ink[col] | glyph_arrays  # (num_chars, h, w)
                candidate_densities = candidates.sum(axis=(1, 2)) / total_pixels

                # Find character whose result is closest to target
                errors = np.abs(candidate_densities - target_d)
                best_idx = np.argmin(errors)

                best_char = char_list[best_idx]
                # Only use if it actually improves things
                if errors[best_idx] < abs(current_d - target_d):
                    current_ink[col] = candidates[best_idx]
                    pass_chars.append(best_char)
                else:
                    pass_chars.append(" ")

            pass_str = "".join(pass_chars)
            # Only add the pass if it has non-space content
            if pass_str.strip():
                passes.append(pass_str)

        result_lines.append(passes)

        # Progress indicator
        pct = (row + 1) / rows * 100
        print(f"\rProcessing: {pct:.0f}% ({row + 1}/{rows} rows)", end="", flush=True)

    print()
    return result_lines


def generate_passes_fast(target_density, densities, max_passes):
    """Generate overstrike passes using density approximation (fast mode)."""
    rows, cols = target_density.shape

    # Sort characters by density for efficient searching
    char_density_pairs = sorted(
        [(ch, d) for ch, d in densities.items()],
        key=lambda x: x[1],
    )
    char_list = [p[0] for p in char_density_pairs]
    density_list = np.array([p[1] for p in char_density_pairs])

    result_lines = []

    for row in range(rows):
        target_row = target_density[row]
        passes = []
        current_density = np.zeros(cols)

        for pass_num in range(max_passes):
            pass_chars = []

            for col in range(cols):
                target_d = target_row[col]
                current_d = current_density[col]

                if abs(current_d - target_d) < 0.01 or target_d <= current_d:
                    pass_chars.append(" ")
                    continue

                # Density after overstriking: 1 - (1 - current)(1 - new_char)
                candidate_densities = 1.0 - (1.0 - current_d) * (1.0 - density_list)
                errors = np.abs(candidate_densities - target_d)
                best_idx = np.argmin(errors)

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
    preview = np.ones((img_h, img_w), dtype=bool)  # True = white (no ink)

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
                    # OR ink: where glyph has ink, preview gets ink (False = ink)
                    region = preview[y : y + gh, x : x + gw]
                    # glyph True = ink, so we AND with NOT glyph (ink darkens)
                    preview[y : y + gh, x : x + gw] = region & ~glyph

    # Convert boolean to image (True=white=255, False=black=0)
    img_array = (preview.astype(np.uint8)) * 255
    img = Image.fromarray(img_array)
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
        "--max-passes", "-p", type=int, default=6, help="Maximum number of overstrike passes per line (default: 6)"
    )
    parser.add_argument(
        "--width", "-w", type=int, default=72, help="Output width in characters (default: 72)"
    )
    parser.add_argument(
        "--preview", default=None, help="Path to save a preview PNG of the result"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Use fast density approximation instead of pixel-accurate compositing"
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
    glyphs, densities, cell_w, cell_h, font = rasterize_font(FONT_PATH, args.font_size)
    print(f"Cell dimensions: {cell_w}x{cell_h} pixels")
    print(f"Characters loaded: {len(glyphs)}")

    # Show top 10 densest characters
    sorted_by_density = sorted(densities.items(), key=lambda x: x[1], reverse=True)
    print("Densest characters: " + " ".join(f"{ch}({d:.2f})" for ch, d in sorted_by_density[:10]))

    print(f"\nLoading image: {args.image}")
    target_density, target_rows = load_and_prepare_image(args.image, args.width, cell_w, cell_h)
    print(f"Output dimensions: {args.width} cols x {target_rows} rows")
    print(f"Max passes: {args.max_passes}")
    print(f"Mode: {'fast (density approximation)' if args.fast else 'accurate (bitmap compositing)'}")
    print()

    if args.fast:
        result_lines = generate_passes_fast(target_density, densities, args.max_passes)
    else:
        result_lines = generate_passes_accurate(target_density, glyphs, args.max_passes)

    # Count total passes used
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
