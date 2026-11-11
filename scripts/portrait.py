"""Turn the photo from profile.yml into the ASCII portrait (assets/ascii.txt).

Runs automatically from build.py whenever the photo changes. Background removal
uses rembg when it's installed (the workflow installs it if remove_background is on).
"""
import hashlib
from pathlib import Path

COLS, ROWS = 60, 36
RAMP = " .'`^,:;-~=+*xjk%#&$@"


def to_ascii(photo, remove_background=False, invert=False):
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    im = Image.open(photo)
    im = im.convert("RGBA") if "A" in im.getbands() else im.convert("RGB")
    if remove_background:
        try:
            from rembg import remove, new_session
            im = remove(im, session=new_session("u2net_human_seg"))
        except ImportError:
            print("rembg not installed; keeping the background")
    if im.mode != "RGBA":
        im.putalpha(255)
    im = ImageOps.fit(im, (COLS * 22, ROWS * 40))
    alpha = im.split()[-1]
    mask = alpha.point(lambda p: 255 if p > 128 else 0)
    L = im.convert("L")
    if invert:
        L = ImageOps.invert(L)
    try:
        import cv2
        L = Image.fromarray(cv2.createCLAHE(clipLimit=3.0, tileGridSize=(6, 6)).apply(np.asarray(L)))
    except ImportError:
        pass
    L = ImageEnhance.Sharpness(ImageOps.equalize(L, mask=mask)).enhance(2.0)
    a = np.asarray(alpha.resize((COLS, ROWS), Image.BOX)) / 255
    g = np.asarray(L.resize((COLS, ROWS), Image.BOX)) / 255
    e = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
                   .resize((COLS, ROWS), Image.BOX)) / 255
    sel = e[a > 0.5]
    e = np.clip(e / max(float(np.percentile(sel, 98)) if sel.size else 1.0, 1e-6), 0, 1)
    v = np.clip(g + 0.15 * e, 0, 1)
    rows = []
    for y in range(ROWS):
        rows.append("".join(" " if a[y, x] < 0.45 else
                            RAMP[max(1, min(len(RAMP) - 1, int(v[y, x] * len(RAMP))))]
                            for x in range(COLS)).rstrip())
    return "\n".join(rows) + "\n"


def update(root, portrait_cfg):
    """Regenerate assets/ascii.txt if the configured photo changed. Returns True if updated."""
    photo = portrait_cfg.get("photo")
    if not photo:
        return False
    path = Path(root) / photo
    if not path.exists():
        print(f"portrait: {photo} not found, keeping the current ASCII art")
        return False
    opts = f"{bool(portrait_cfg.get('remove_background'))}{bool(portrait_cfg.get('invert'))}"
    digest = hashlib.sha256(path.read_bytes() + opts.encode()).hexdigest()
    stamp = Path(root) / "assets" / ".portrait-hash"
    if stamp.exists() and stamp.read_text().strip() == digest:
        return False
    art = to_ascii(path, bool(portrait_cfg.get("remove_background")), bool(portrait_cfg.get("invert")))
    (Path(root) / "assets" / "ascii.txt").write_text(art)
    stamp.write_text(digest + "\n")
    print(f"portrait: rebuilt ASCII art from {photo}")
    return True
