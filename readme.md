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
- https://web.archive.org/web/20110323065548/http://www.verledentijd.com/2011/03/val-van-saigon/saigon-hubert-van-es/
- https://www.flickr.com/photos/nasa2explore/10697912315/in/album-72157630719371642/
- https://www.gettyimages.com/detail/news-photo/president-john-f-kennedy-first-lady-jacqueline-kennedy-news-photo/517330536 (Yes, it is PD)
- https://www.flickr.com/photos/35591378@N03/5680724572
- https://commons.wikimedia.org/wiki/File:Incendie_de_Notre_Dame_%C3%A0_Paris._vue_depuis_le_minist%C3%A8re_de_la_recherche._6.jpg
- https://www.invaluable.com/auction-lot/arthur-sasse-rare-albert-einstein-portrait-1951-18-c-7444493a21 (Yes, this too is PD)
- https://www.newspapers.com/article/corpus-christi-caller-times-marilyn-monr/1574793/ (Original PD photo, photo we used if from Wikimedia) https://en.wikipedia.org/wiki/File:Marilyn_Monroe_photo_pose_Seven_Year_Itch.jpg
- https://www.magnumphotos.com/newsroom/the-making-of-icons/

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

```python main.py ./Sample/Earthrise.jpg -p 20 --enhance --preview Earthrise```