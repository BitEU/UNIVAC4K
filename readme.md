# UNIVAC4K

This is a small Python program to convert complex, high-resolution images to 72 character ASCII art with a tecnique called "halftoning via overstriking." By writing a character to the same spot several times, we can create high resolution images than is typical for digital ASCII art.

The sample photos are from the Library of Congress, NASAm and other sources and can be accessed here: 

- https://www.loc.gov/item/2017762891/
- https://apollojournals.org/afj/ap08fj/16day4_orbit4.html
- https://www.nasa.gov/image-detail/337294main-pg62-as11-40-5903-full/
- https://science.nasa.gov/resource/first-image-of-a-black-hole/
- https://science.nasa.gov/resource/voyager-pale-blue-dot-download/
- https://digital.sciencehistory.org/works/skau3rn
- https://www.nasa.gov/image-detail/ingenuitys-blades-are-released-2/

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