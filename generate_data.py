#%%
from math import cos, sin, radians, tau, hypot, ceil
import json, random
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageEnhance
from PIL.PngImagePlugin import PngInfo

OUT = 300                   # every image is emitted at OUT x OUT
W, H, STROKE = 680, 350, 6  # design space matching the SVG

# design-space segment lengths, taken from the original figure
HEAD_R, TORSO, SHOULDER_DROP = 30, 130, 30
UPPER_ARM, FOREARM, THIGH, SHIN = 60, 55, 55, 55

def _step(p, t, L):
    """Point L away from p, at t degrees clockwise from straight down."""
    return (p[0] + L*sin(radians(t)), p[1] + L*cos(radians(t)))

def paths_for_patient(seed=None, margin=12):
    """A random but plausible pose, in the same design space as PATHS.

    Returns (paths, landmark).  paths has the layout render() expects
    (head, torso, arms, legs); landmark is the hip, where the legs meet the
    torso, and is always paths[1][-1].
    """
    rnd = random.Random(seed)
    a = rnd.uniform

    hip = (W/2 + a(-20, 20), 230 + a(-12, 12))
    lean = a(-12, 12)                             # torso tilt from vertical
    neck = _step(hip, lean + 180, TORSO)
    shoulder = _step(neck, lean, SHOULDER_DROP)
    head = _step(neck, lean + 180 + a(-20, 20), HEAD_R)   # head centre

    def clear(p):                                 # keep limbs off the face
        return hypot(p[0] - head[0], p[1] - head[1]) > HEAD_R + 8

    limb = {}
    for s in (-1, 1):                             # -1 = left on screen, 1 = right
        for _ in range(40):                       # retry until the arm is clear
            up = s * rnd.triangular(15, 165, 40)  # upper arm, from straight down
            flex = s * a(0, 130)                  # elbow, always bends inward
            elbow = _step(shoulder, up, UPPER_ARM)
            hand = _step(elbow, up + flex, FOREARM)
            if clear(elbow) and clear(hand):
                break
        thigh = s * a(5, 35)
        knee = _step(hip, thigh, THIGH)
        foot = _step(knee, thigh + s*a(-20, 20), SHIN)
        limb[s] = (hand, elbow, knee, foot)

    paths = [
        [(head[0] + HEAD_R*cos(i*tau/64),
          head[1] + HEAD_R*sin(i*tau/64)) for i in range(65)],
        [neck, hip],
        [limb[-1][0], limb[-1][1], shoulder, limb[1][1], limb[1][0]],
        [limb[-1][3], limb[-1][2], hip, limb[1][2], limb[1][3]],
    ]

    # nudge the whole figure back inside the design box if a limb pokes out
    xs = [x for p in paths for x, _ in p]
    ys = [y for p in paths for _, y in p]
    dx = max(margin - min(xs), 0) + min(W - margin - max(xs), 0)
    dy = max(margin - min(ys), 0) + min(H - margin - max(ys), 0)
    paths = [[(x + dx, y + dy) for x, y in p] for p in paths]
    return paths

def _resample(pts, step):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, ceil(hypot(x1-x0, y1-y0)/step))
        out += [(x0 + (x1-x0)*i/n, y0 + (y1-y0)*i/n) for i in range(1, n+1)]
    return out

def save(img, path):
    """Save as PNG, embedding the render params and landmark as text chunks."""
    meta = PngInfo()
    for k in ("params", "landmark"):
        if k in img.info:
            meta.add_text(k, img.info[k])
    img.save(path, pnginfo=meta)

def render(size=(300, 300), shift=(0, 0), scale=(1, 1), rotation=0,
           skew=(0, 0), flip=False, jitter=0, jitter_step=25, thickness=1,
           blur=0, noise=0, brightness=1, contrast=1,
           seed=None, ss=4, bg="white", fg="black", patient=0):
    w, h = size
    rnd = random.Random(seed)
    img = Image.new("RGB", (w*ss, h*ss), bg)
    d = ImageDraw.Draw(img)
    fit = min(w/W, h/H)                      # fit design box into the output
    sx, sy = scale[0]*fit, scale[1]*fit
    ca, sa = cos(radians(rotation)), sin(radians(rotation))
    lw = max(1, round((abs(sx) + abs(sy))/2 * STROKE * thickness * ss))
    ox, oy = w/OUT, h/OUT                    # output px -> acquisition px

    def T(p):                                # about the centre, in this order
        x, y = p
        if jitter:
            x, y = x + rnd.gauss(0, jitter), y + rnd.gauss(0, jitter)
        x, y = (x - W/2)*sx, (y - H/2)*sy
        if flip:
            x = -x
        x, y = x + skew[0]*y, y + skew[1]*x
        x, y = x*ca - y*sa, x*sa + y*ca
        return ((x + w/2 + shift[0]*ox)*ss, (y + h/2 + shift[1]*oy)*ss)

    paths = paths_for_patient(patient)
    for i, pts in enumerate(paths):
        q = [T(p) for p in (_resample(pts, jitter_step) if jitter else pts)]
        if i == 1:                           # torso: last point is the landmark
            landmark = (q[-1][0]/ss/ox, q[-1][1]/ss/oy)
        d.line(q, fill=fg, width=lw, joint="curve")
        for x, y in (q[0], q[-1]):           # round caps
            d.ellipse([x-lw/2, y-lw/2, x+lw/2, y+lw/2], fill=fg)

    out = img.resize((w, h), Image.LANCZOS)
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    if brightness != 1:
        out = ImageEnhance.Brightness(out).enhance(brightness)
    if contrast != 1:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if noise:
        n = Image.effect_noise((w, h), noise).convert(out.mode)
        out = ImageChops.add(out, n, 1.0, -128)

    out = out.resize((OUT, OUT), Image.NEAREST)
    out.info["params"] = json.dumps(
        {"rotation": rotation, "scale": scale, "shift": shift}, sort_keys=True)
    out.info["landmark"] = json.dumps(landmark)
    return out
# %%
from ipywidgets import interact, FloatSlider as F

latest_image = None

@interact(rotation=F(0, min=-45, max=45),
          skew_x=F(0, min=-0.6, max=0.6, step=0.05),
          jitter=F(0, min=0, max=6, step=0.5),
          jitter_step=F(25, min=3, max=60, step=1),
          thickness=F(1, min=0.3, max=3, step=0.1),
          blur=F(0, min=0, max=4, step=0.1),
          noise=F(0, min=0, max=60, step=1))
def _(rotation, skew_x, jitter, jitter_step, thickness, blur, noise):
    global latest_image
    latest_image = render(size=(103, 103), rotation=rotation, skew=(skew_x, 0),
                  jitter=jitter, jitter_step=jitter_step, thickness=thickness,
                  blur=blur, noise=noise, seed=0)
    return latest_image
# %%
save(latest_image, 'lfi.png')

save(render(size=(200, 200)), 'hfi.png')

# %%
from coregistration_exercise import spatial_transform
from helper_functions import coregister, compare, mark_biopsy_site, get_prostate_location_from_user

hfi = render()

corruption = dict(size=(50, 50), jitter=3, blur=0.2, noise=10.0)
lfi = render(shift=(50, -50), rotation=1, **corruption) # good
# lfi = render(scale=(2, 2), rotation=-5, **corruption) # good
# lfi = render(scale=(1.3, 1.3), rotation=12, **corruption) # good
# lfi = render(shift=(50, -50), scale=(1.3, 1.3), rotation=12, **corruption) # bad
# lfi = render(rotation=20, skew=(0.5,0), **corruption) # accidentally ok

params = coregister(hfi, lfi)
sthfi = spatial_transform(hfi, params)

sthfi_landmark = get_prostate_location_from_user(sthfi)
compare((mark_biopsy_site(hfi), 'hfi'), (mark_biopsy_site(lfi, sthfi_landmark), 'lfi'), (mark_biopsy_site(sthfi), 'sthfi'))

# %%
corruption = dict(size=(50, 50), jitter=3, blur=0.2, noise=10.0)

# Patient 1
patient=1
save(render(patient=patient), f"./patient_{patient}.hfi.png")
save(render(patient=patient, shift=(50, -50), rotation=1, **corruption), f"./patient_{patient}.lfi.png")

# Patient 2
patient=2
save(render(patient=patient), f"./patient_{patient}.hfi.png")
save(render(patient=patient, scale=(2, 2), rotation=-5, **corruption), f"./patient_{patient}.lfi.png")

# Patient 3
patient=3
save(render(patient=patient), f"./patient_{patient}.hfi.png")
save(render(patient=patient, scale=(1.3, 1.3), rotation=12, **corruption), f"./patient_{patient}.lfi.png")

# Patient 4
patient=4
save(render(patient=patient), f"./patient_{patient}.hfi.png")
save(render(patient=patient, shift=(50, -50), scale=(1.3, 1.3), rotation=12, **corruption), f"./patient_{patient}.lfi.png")

# Patient 5
patient=5
save(render(patient=patient, scale=(2, 2), shift=(0, -30)), f"./patient_{patient}.hfi.png")
save(render(patient=patient, scale=(1.3, 1.3), rotation=12, **corruption), f"./patient_{patient}.lfi.png")

# Patient 6
patient=6
save(render(patient=patient), f"./patient_{patient}.hfi.png")
save(render(patient=patient, shift=(0, -70), scale=(1.3, 1.3), rotation=-25, **corruption), f"./patient_{patient}.lfi.png")


# %%
