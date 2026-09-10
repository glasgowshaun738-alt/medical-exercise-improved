"""
THERE ARE NO ERRORS HERE

Probably.

hopefully.

Don't spend time debugging the functions in this file.
"""


from math import cos, sin, radians
import json
from PIL import Image, ImageDraw


def _translate(im, dx, dy):
    return im.transform(im.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                        resample=Image.BILINEAR, fillcolor="white")

def _rotate(im, deg):
    return im.rotate(deg, resample=Image.BILINEAR, fillcolor="white")

def _scale(im, fx, fy):
    cx, cy = im.width/2, im.height/2
    return im.transform(im.size, Image.AFFINE,
                        (1/fx, 0, cx*(1 - 1/fx), 0, 1/fy, cy*(1 - 1/fy)),
                        resample=Image.BILINEAR, fillcolor="white")

def _translate_pt(p, dx, dy):
    return (p[0] + dx, p[1] + dy)

def _rotate_pt(p, deg, cx, cy):
    ca, sa = cos(radians(deg)), sin(radians(deg))
    x, y = p[0] - cx, p[1] - cy
    return (cx + x*ca + y*sa, cy - x*sa + y*ca)

def _scale_pt(p, fx, fy, cx, cy):
    return (cx + (p[0] - cx)*fx, cy + (p[1] - cy)*fy)

def coregister(img, ref):
    """Assume this is doing something very clever to identify transformation params"""
    a = json.loads(img.info["params"])
    b = json.loads(ref.info["params"])
    return {
        "rotation": a["rotation"] - b["rotation"],
        "scale": (a["scale"][0]/b["scale"][0], a["scale"][1]/b["scale"][1]),
        "shift": (a["shift"][0] - b["shift"][0], a["shift"][1] - b["shift"][1]),
    }


def get_prostate_location_from_user(img):
    """Landmark position in output-image pixels, or None."""
    p = json.loads(img.info.get("landmark") or "null")
    return tuple(p) if p else None

def mark_biopsy_site(img, point=None, r=5, fill="red"):
    """Copy of `img` with a marker at `point` (defaults to its own landmark)."""
    p = point or get_prostate_location_from_user(img)
    out = img.copy()
    out.info.update(img.info)
    if p:
        d = ImageDraw.Draw(out)
        d.ellipse([p[0]-r, p[1]-r, p[0]+r, p[1]+r], outline=fill, width=2)
        d.point(p, fill=fill)
    return out

def as_image(img, caption=None, zoom=1):
    """Copy of `img` scaled by `zoom`, with an optional caption drawn below it."""
    im = img.resize((img.width*zoom, img.height*zoom)) if zoom != 1 else img.copy()
    if not caption:
        return im
    label_h = 20
    out = Image.new("RGB", (im.width, im.height + label_h), "white")
    out.paste(im, (0, 0))
    ImageDraw.Draw(out).text((4, im.height + 2), caption, fill="black")
    return out

def compare(*pairs, zoom=1):
    """Combine (image, caption) pairs into a single image, side by side."""
    tiles = [as_image(img, caption, zoom) for img, caption in pairs]
    gap = 10
    width = sum(t.width for t in tiles) + gap*(len(tiles) - 1)
    height = max(t.height for t in tiles)
    out = Image.new("RGB", (width, height), "white")
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width + gap
    return out