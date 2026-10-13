"""Paints Mentor's default wallpaper: a red moon behind dark mountains, over fog and still water.

Everything is drawn here from noise and gradients, so the picture is the project's own and can
be shipped with it. Run it after changing anything below:

    python build/make-wallpaper.py [output.jpg] [width]

Needs numpy and Pillow.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "distro", "rootfs", "usr", "share", "backgrounds", "mentor", "red-moon.jpg")
W = int(sys.argv[2]) if len(sys.argv) > 2 else 3840
H = W * 9 // 16
rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
u, v = xx / W, yy / H  # 0..1 across and down


def noise(scale, octaves=5, stretch=1.0, seed=None):
    """Fractal value noise in 0..1; `scale` is the size of the largest features in screen heights,
    `stretch` > 1 draws them out sideways."""
    r = np.random.default_rng(seed) if seed is not None else rng
    total, weight, amplitude = np.zeros((H, W), np.float32), 0.0, 1.0
    for octave in range(octaves):
        cell = max(2.0, scale * H / 2 ** octave)
        small = r.random((int(H / cell) + 3, int(W / (cell * stretch)) + 3), dtype=np.float32)
        layer = Image.fromarray((small * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
        total += np.asarray(layer, np.float32) / 255 * amplitude
        weight += amplitude
        amplitude *= 0.5
    return total / weight


def blur(array, radius):
    return np.asarray(Image.fromarray((np.clip(array, 0, 1) * 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(radius * W / 3840)), np.float32) / 255


def over(base, colour, alpha):
    return base * (1 - alpha[..., None]) + np.asarray(colour, np.float32) * alpha[..., None]


def ridge(height, roughness, peak_at, peak, seed):
    """The skyline of a range, as the row it reaches in each column (0 = top of the picture)."""
    r = np.random.default_rng(seed)
    line = np.zeros(W, np.float32)
    for octave in range(9):
        points = r.random(2 ** (octave + 2) + 3, dtype=np.float32)
        line += (1 - np.abs(2 * np.interp(np.linspace(0, len(points) - 1, W), np.arange(len(points)), points) - 1)) * roughness / 1.75 ** octave
    line -= line.mean()
    line += peak * np.exp(-(np.abs(np.linspace(0, 1, W) - peak_at) / 0.10) ** 1.35)   # one mountain stands above the rest
    return height - line


# --- sky: charcoal, a little lighter to the right where the cloud bank is
picture = np.empty((H, W, 3), np.float32)
picture[:] = np.asarray([0.105, 0.105, 0.115]) + (0.035 * (1 - v))[..., None]
cloud = noise(0.55, 5, 1.6, seed=3) * noise(1.4, 3, 1.2, seed=4)
picture = over(picture, (0.33, 0.34, 0.37), np.clip((cloud - 0.22) * 2.2, 0, 1) * np.clip((u - 0.55) * 2.2, 0, 1) * np.clip(1.25 - v * 1.6, 0, 1))

# --- the moon
mx, my, mr = 0.545 * W, 0.375 * H, 0.245 * H
distance = np.hypot(xx - mx, yy - my) / mr
glow = np.exp(-np.clip(distance - 1, 0, None) * 2.6) * 0.55 + np.exp(-np.clip(distance - 1, 0, None) * 9) * 0.5
picture = over(picture, (0.95, 0.10, 0.08), np.clip(glow, 0, 1) * (distance > 0.97))
disc = np.clip((1 - distance) * mr / 2.5, 0, 1)                      # a soft edge a few points wide
limb = np.clip(1 - distance ** 2, 0, 1) ** 0.16                      # darker towards the rim, like a sphere
light = np.clip(0.86 + 0.34 * ((mx - xx) / mr * -0.35 + (my - yy) / mr * 0.5), 0.5, 1.15)  # lit from above right
seas = noise(0.26, 5, 1.0, seed=11)
seas = np.clip((seas - 0.50) * 9, 0, 1) * 0.80 + np.clip((noise(0.06, 4, seed=12) - 0.58) * 6, 0, 1) * 0.20
moon = np.stack([1.0 * limb * light * (1 - 0.55 * seas), 0.13 * limb * light * (1 - 0.75 * seas) + 0.02,
                 0.10 * limb * light * (1 - 0.75 * seas) + 0.02], axis=-1)
veins = np.clip(1 - np.abs(noise(0.11, 3, seed=13) - 0.5) * 90, 0, 1) * 0.25 * (seas < 0.3)   # fine bright cracks
moon[..., 0] += veins * 0.25
moon[..., 1] += veins * 0.12
picture = picture * (1 - disc[..., None]) + np.clip(moon, 0, 1) * disc[..., None]

# --- red light spilling along the horizon behind the mountains
horizon = 0.555
spill = np.exp(-((v - horizon) / 0.035) ** 2) * (0.35 + 0.65 * noise(0.5, 3, 3.0, seed=20)) * np.exp(-((u - 0.52) / 0.36) ** 2)
picture = over(picture, (0.92, 0.10, 0.08), np.clip(spill * 0.95, 0, 1))

# --- mountains, far to near: each darker, the middle one tall enough to cut into the moon
for height, roughness, peak_at, peak, shade, seed in ((0.60, 0.075, 0.30, 0.030, 0.085, 31),
                                                      (0.625, 0.105, 0.515, 0.185, 0.045, 32),
                                                      (0.65, 0.090, 0.66, 0.060, 0.030, 33)):
    skyline = ridge(height, roughness, peak_at, peak, seed) * H
    inside = np.clip((yy - skyline[None, :]) / 1.5, 0, 1)
    strata = noise(0.02, 2, 9.0, seed=seed + 10) * 0.028 * np.clip(1 - (yy - skyline[None, :]) / (0.22 * H), 0, 1)  # faint lines of rock
    rim = np.exp(-np.clip(yy - skyline[None, :], 0, None) / (0.006 * H)) * np.exp(-((u - 0.54) / 0.2) ** 2) * 0.22       # red caught on the crest
    rock = np.stack([shade + strata + rim * 0.9, shade + strata + rim * 0.08, shade * 1.1 + strata + rim * 0.06], axis=-1)
    picture = picture * (1 - inside[..., None]) + rock * inside[..., None]

# --- fog: a thick bank across the middle, rising on the right, thinning over the water
bank = noise(0.34, 6, 2.2, seed=41)
billow = noise(0.09, 5, 1.6, seed=42)
level = 0.66 + 0.10 * (0.5 - u) * (u > 0.5) * 2 - 0.02 * np.sin(u * 7)
density = np.clip((v - level) / 0.06 + (bank - 0.5) * 3.0 + (billow - 0.5) * 2.2, 0, 1)
density *= np.clip(1.35 - (v - 0.70) / 0.17, 0, 1)                   # fades out towards the foreground
density = blur(density, 3)
shade = 0.22 + 0.50 * np.clip(bank * 0.9 + (billow - 0.5) * 1.5 + (noise(0.03, 3, 1.4, seed=43) - 0.5) * 0.35, 0, 1) + 0.16 * np.clip((u - 0.45) * 1.6, 0, 1)
fog = np.stack([shade * 0.98, shade, shade * 1.05], axis=-1)
fog[..., 0] += np.exp(-((v - 0.60) / 0.06) ** 2) * np.exp(-((u - 0.5) / 0.3) ** 2) * 0.16   # warmed by the red above it
picture = picture * (1 - density[..., None] * 0.93) + fog * (density[..., None] * 0.93)

# --- water and dark land in the foreground
ground = np.clip((v - 0.80) / 0.05, 0, 1)
water = 0.09 + 0.34 * np.clip((noise(0.05, 4, 14.0, seed=51) - 0.42) * 3, 0, 1) * np.exp(-((u - 0.52) / 0.33) ** 2) * np.clip(1.6 - (v - 0.8) / 0.12, 0, 1)
land = np.clip((noise(0.16, 5, 6.0, seed=52) - 0.50 + (v - 0.86) * 1.6) * 7, 0, 1)
tone = water * (1 - land) + 0.045 * land
picture = picture * (1 - ground[..., None]) + np.stack([tone * 0.95, tone, tone * 1.06], axis=-1) * ground[..., None]

# --- finish: darker corners, a touch of grain
vignette = 1 - 0.55 * np.clip(np.hypot((u - 0.5) * 1.25, (v - 0.48) * 1.5) - 0.28, 0, 1) ** 1.4
picture = picture * vignette[..., None] + (rng.random((H, W, 1), dtype=np.float32) - 0.5) * 0.012
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
Image.fromarray((np.clip(picture, 0, 1) * 255).astype(np.uint8)).save(OUT, quality=92)
print(f"wrote {OUT} ({W}x{H})")
