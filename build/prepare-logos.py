#!/usr/bin/env python3
"""Turn the logo artwork in distro/splash/originals into what the system uses.

    python build/prepare-logos.py        (needs Pillow; in Arch: pacman -S python-pillow)

Each original is a round emblem on its own dark rectangle. For the boot splash
the rectangle's edges are faded out, so that on the black boot screen only the
emblem is seen: distro/splash/logo-N.png. The first one, cut to its circle, is
also the assistant's icon.

The results are kept in the repository; run this again only when the artwork changes.
"""
import pathlib

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORIGINALS = ROOT / "distro" / "splash" / "originals"
SPLASH = ROOT / "distro" / "splash"
ICON = ROOT / "distro" / "rootfs" / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "org.mentor.Chat.png"
SPLASH_WIDTH = 880  # fits the 1280x800 screen the VM boots with, with room for the spinner
FEATHER = 70


def faded(image):
    """The image with its border fading to transparent."""
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rectangle((FEATHER, FEATHER, width - FEATHER, height - FEATHER), fill=255)
    image.putalpha(mask.filter(ImageFilter.GaussianBlur(FEATHER / 2)))
    return image


def emblem(image, size):
    """The round emblem in the middle of the artwork, on a transparent square."""
    width, height = image.size
    radius = int(height * 0.47)
    box = (width // 2 - radius, height // 2 - radius, width // 2 + radius, height // 2 + radius)
    square = image.crop(box)
    mask = Image.new("L", square.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, square.width - 3, square.height - 3), fill=255)
    square.putalpha(ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(1.5)), mask))
    return square.resize((size, size), Image.LANCZOS)


originals = sorted(ORIGINALS.iterdir())
for number, path in enumerate(originals, 1):
    image = Image.open(path).convert("RGBA")
    scaled = image.resize((SPLASH_WIDTH, round(image.height * SPLASH_WIDTH / image.width)), Image.LANCZOS)
    faded(scaled).save(SPLASH / f"logo-{number}.png")
    print(f"logo-{number}.png from {path.name}")
ICON.parent.mkdir(parents=True, exist_ok=True)
emblem(Image.open(originals[0]).convert("RGBA"), 256).save(ICON)
print(f"{ICON.name} from {originals[0].name}")
