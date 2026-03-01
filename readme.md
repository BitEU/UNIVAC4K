# UNIVAC4K

This is a small Python program to convert complex, high-resolution images to 72 character ASCII art with a tecnique called "halftoning via overstriking." By writing a character to the same spot several times, we can create high resolution images than is typical for digital ASCII art.

The sample photo is from the Library of Congress and can be accessed here: https://www.loc.gov/item/2017762891/

## Usage:


``` python main.py <image_path> [options]```

```
Options:

--output / -o — JSON output file (default: output.json)
--max-passes / -p — Max overstrike passes per line (default: 6, set as high as you want)
--width / -w — Output width in characters (default: 72)
--preview — Save a preview PNG showing what the overstriked output would look like
--fast — Use density approximation instead of pixel-accurate bitmap compositing (much faster for high pass counts)
--font-size — Font rendering size in points (default: 20)
```

```python main.py sample.tif -p 20 --preview PREVIEW```