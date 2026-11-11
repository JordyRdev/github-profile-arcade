"""'Contribution Grand Prix': a pseudo-3D, behind-the-car arcade racer driven by
the GitHub contribution calendar. Pure SVG + SMIL, so it animates in a README.

World model: everything on the ground is drawn once at reference depth z=1 and
scaled about the vanishing point by s = 1/z (cheap, arcade-style perspective).
The car's track distance D(t) (with acceleration and braking) drives every
object's depth z = d_obj - D(t).

Each day with contributions becomes a green block in one of three lanes; the
car steers into it, the score climbs, month billboards pass by, and a
checkered gate marks the finish with the yearly total.
"""
import datetime as dt
import math
from html import escape

H = 310
HORIZON = 122
CAM_H = 150                      # ground y (below horizon) at depth z=1
ROAD_W = 270                     # half road width at z=1
LANES = (-160, 0, 160)
Z_NEAR, Z_FAR = 0.78, 26.0
BAND_L = 1.6                     # depth of one stripe period
DAY_Z = 3.0                      # track distance per active day (empty days are squeezed)
START_T, RACE_T, END_T = 3.0, 24.0, 4.5
ACC_T, BRAKE_T = 1.6, 1.6
Z_SAMPLES = [26, 20, 15, 11, 8, 6, 4.6, 3.6, 2.8, 2.2, 1.8, 1.5, 1.25, 1.08, 0.95, 0.85, 0.78]

PALETTES = {
    # Las Vegas strip at night
    "dark": dict(
        scene="vegas",
        sky=["#05030f", "#120a2e", "#2d0f4f", "#8a2475"],
        ground=["#0c0a18", "#120f22"], side=["#1a1530", "#221c3f"], side_w=210,
        road=["#1c1a29", "#232136"], kerb=["#ff2bd6", "#21e6ff"], dash="#ffe14d",
        trunk="#2a1f3d", frond=["#0f4d36", "#2bd98a"],
        neon=["#ff2bd6", "#21e6ff", "#ffe14d", "#39ff88", "#ff7a1a"],
        hud="#ffffff", hud_dim="#d9c8ff", accent="#ffe14d", post="#3a2d5c",
        lv=["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"], red="#ff3355", green="#39ff88",
        board="#150b29", board_text="#ffe14d"),
    # tropical coast in the sun
    "light": dict(
        scene="beach",
        sky=["#1f7fe0", "#4fa8f0", "#9fd6ff", "#e3f5ff"], sun=["#fffbe0", "#ffe066"],
        water=["#1597c0", "#1fb0d6"], foam="#e9fbff",
        ground=["#4fae4a", "#5dbd56"], side=["#ecd29b", "#f4e0b4"], side_w=210,
        road=["#7e7e86", "#88888f"], kerb=["#d7263d", "#ffffff"], dash="#ffffff",
        trunk="#8a5a33", frond=["#2f9e44", "#4cc75e"],
        hud="#ffffff", hud_dim="#f0f8ff", accent="#ffd23f", post="#7a4f2c",
        lv=["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"], red="#d7263d", green="#1a7f37",
        board="#fff6dc", board_text="#c2410c"),
}


def _f(x):
    return f"{x:.4f}".rstrip("0").rstrip(".") if x else "0"


# --------------------------------------------------------------------------- #
#  Motion: track distance D(t) with acceleration and braking                   #
# --------------------------------------------------------------------------- #
class Motion:
    def __init__(self, track_len):
        self.t0 = START_T
        self.vmax = track_len / (RACE_T - ACC_T / 2)
        self.tf = START_T + RACE_T               # crosses the finish line
        self.df = track_len
        self.cycle = START_T + RACE_T + END_T

    def D(self, t):
        if t <= self.t0:
            return 0.0
        a = self.vmax / ACC_T
        if t <= self.t0 + ACC_T:
            return 0.5 * a * (t - self.t0) ** 2
        if t <= self.tf:
            return 0.5 * self.vmax * ACC_T + self.vmax * (t - self.t0 - ACC_T)
        u = min(t - self.tf, BRAKE_T)
        return self.df + self.vmax * u - 0.5 * (self.vmax / BRAKE_T) * u * u

    @property
    def dmax(self):
        return self.D(self.cycle)

    def inv(self, d):
        """Earliest t with D(t) >= d, or None if never reached in this cycle."""
        if d <= 0:
            return 0.0
        if d > self.dmax + 1e-9:
            return None
        lo, hi = self.t0, self.tf + BRAKE_T
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.D(mid) < d:
                lo = mid
            else:
                hi = mid
        return hi


def _object_keyframes(m, d_obj):
    """(t, scale) keyframes for a static world object at track distance d_obj."""
    kf = [(0.0, 1 / max(min(d_obj, Z_FAR), 0.05))]
    for zs in Z_SAMPLES:
        if zs >= d_obj:
            continue
        t = m.inv(d_obj - zs)
        if t is None:
            break
        kf.append((t, 1 / zs))
    if m.dmax < d_obj - Z_NEAR:                  # still ahead at cycle end
        kf.append((m.cycle, 1 / min(d_obj - m.dmax, Z_FAR)))
    return kf


def _anim_scale(kf, cyc):
    kt, vals, last = [], [], -1.0
    for t, s in kf:
        k = 0.0 if not kt else max(t / cyc, last + 1e-4)
        if k > 1:
            break
        kt.append(k)
        vals.append(s)
        last = k
    if kt[-1] < 1:
        kt.append(1.0)
        vals.append(vals[-1])
    return (f'<animateTransform attributeName="transform" type="scale" dur="{cyc:.2f}s" '
            f'repeatCount="indefinite" keyTimes="{";".join(_f(k) for k in kt)}" '
            f'values="{";".join(f"{v:.4f}" for v in vals)}"/>')


def _visibility_anim(changes, cyc):
    kt, vals = ["0"], ["0"]
    for t, v in changes:
        if t <= 0:
            vals[0] = str(int(v))
            continue
        if t >= cyc:
            break
        kt.append(_f(t / cyc))
        vals.append(str(int(v)))
    return (f'<animate attributeName="opacity" dur="{cyc:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{";".join(kt)}" values="{";".join(vals)}"/>')


# --------------------------------------------------------------------------- #
#  Drawing helpers (reference depth z=1, origin at the vanishing point)        #
# --------------------------------------------------------------------------- #
def _band_ground(c, k, width):
    """Ground stripe of one band at reference depth (lighter shades = motion cue)."""
    y0, hgt = CAM_H, CAM_H * 0.09
    edge = ROAD_W + 34 + c["side_w"]
    far = width * 6
    g = []
    if c["scene"] == "beach":
        g.append(f'<rect x="{-far}" y="{y0}" width="{far - edge}" height="{hgt:.1f}" fill="{c["water"][1]}"/>')
        g.append(f'<rect x="{-edge - 16}" y="{y0}" width="16" height="{hgt:.1f}" fill="{c["foam"]}"/>')
    else:
        g.append(f'<rect x="{-far}" y="{y0}" width="{far - edge}" height="{hgt:.1f}" fill="{c["ground"][1]}"/>')
    g.append(f'<rect x="{edge}" y="{y0}" width="{far}" height="{hgt:.1f}" fill="{c["ground"][1]}"/>')
    g.append(f'<rect x="{-edge}" y="{y0}" width="{c["side_w"]}" height="{hgt:.1f}" fill="{c["side"][1]}"/>')
    g.append(f'<rect x="{ROAD_W + 34}" y="{y0}" width="{c["side_w"]}" height="{hgt:.1f}" fill="{c["side"][1]}"/>')
    g.append(f'<rect x="{-ROAD_W}" y="{y0}" width="{2 * ROAD_W}" height="{hgt:.1f}" fill="{c["road"][1]}"/>')
    g.append(f'<rect x="{-ROAD_W - 34}" y="{y0}" width="34" height="{hgt:.1f}" fill="{c["kerb"][0]}"/>')
    g.append(f'<rect x="{ROAD_W}" y="{y0}" width="34" height="{hgt:.1f}" fill="{c["kerb"][0]}"/>')
    for lx in (-80, 80):
        g.append(f'<rect x="{lx - 4}" y="{y0}" width="8" height="{hgt:.1f}" fill="{c["dash"]}"/>')
    return "".join(g)


def _palm(c, x, lean, glow=False):
    """Pixel palm tree standing at (x, CAM_H); lean = +1 leans right, -1 left."""
    y = CAM_H
    g = []
    for i in range(8):                                  # curved trunk
        off = lean * (i * i) * 0.9
        g.append(f'<rect x="{x + off - 7:.1f}" y="{y - (i + 1) * 26}" width="14" height="27" '
                 f'fill="{c["trunk"]}"/>')
        g.append(f'<rect x="{x + off - 7:.1f}" y="{y - (i + 1) * 26}" width="14" height="4" fill="#000" opacity="0.18"/>')
    tx, ty = x + lean * 49 * 0.9, y - 208
    dark, light = c["frond"]
    for ang, ln in ((-160, 95), (-120, 80), (-60, 80), (-20, 95), (-90, 60), (160, 70), (20, 70)):
        import math as _m
        a = _m.radians(ang)
        ex, ey = tx + ln * _m.cos(a), ty + ln * _m.sin(a) + 40
        mx, my = tx + ln * 0.5 * _m.cos(a), ty + ln * 0.5 * _m.sin(a) - 8
        g.append(f'<path d="M{tx:.0f},{ty:.0f} Q{mx:.0f},{my - 14:.0f} {ex:.0f},{ey:.0f} '
                 f'Q{mx:.0f},{my + 8:.0f} {tx:.0f},{ty + 8:.0f} Z" fill="{dark}"/>')
        g.append(f'<path d="M{tx:.0f},{ty:.0f} Q{mx:.0f},{my - 14:.0f} {ex:.0f},{ey:.0f}" fill="none" '
                 f'stroke="{light}" stroke-width="{4 if glow else 3}"/>')
    g.append(f'<circle cx="{tx - 6:.0f}" cy="{ty + 8:.0f}" r="7" fill="#6b3f1d"/>'
             f'<circle cx="{tx + 7:.0f}" cy="{ty + 10:.0f}" r="7" fill="#7d4a22"/>')
    return "".join(g)


VEGAS_WORDS = ["DEPLOY", "SHIP IT", "100%", "MERGE", "PASS", "CI/CD", "CODE", "COMMIT"]


def _neon_sign(c, x, k):
    """Tall neon pylon with a marquee-bulb border and a flickering QA-themed word."""
    y = CAM_H
    col = c["neon"][k % len(c["neon"])]
    col2 = c["neon"][(k + 2) % len(c["neon"])]
    word = VEGAS_WORDS[k % len(VEGAS_WORDS)]
    w = max(150, 34 * len(word))
    top = y - 330
    return (f'<rect x="{x - 9}" y="{top + 120}" width="18" height="{330 - 120}" fill="{c["post"]}"/>'
            f'<rect x="{x - w / 2}" y="{top}" width="{w}" height="120" rx="10" fill="#0b0716" stroke="{col2}" stroke-width="5"/>'
            f'<rect x="{x - w / 2 + 12}" y="{top + 12}" width="{w - 24}" height="96" rx="6" fill="none" stroke="{c["neon"][2]}" '
            f'stroke-width="8" stroke-linecap="round" stroke-dasharray="0 18">'
            f'<animate attributeName="stroke-dashoffset" values="0;18" dur="0.5s" repeatCount="indefinite"/></rect>'
            f'<text x="{x}" y="{top + 82}" font-size="54" font-weight="bold" text-anchor="middle" fill="{col}" '
            f'stroke="{col}" stroke-width="2">{word}'
            f'<animate attributeName="opacity" values="1;1;0.35;1;1;1;0.5;1" dur="{1.7 + (k % 3) * 0.6:.1f}s" '
            f'repeatCount="indefinite" calcMode="discrete"/></text>')


def _parasol(c, x, k):
    y = CAM_H
    cols = ["#ff4d6d", "#ffd23f", "#2ec4b6", "#ff8c42"]
    a, b = cols[k % 4], "#ffffff"
    return (f'<rect x="{x - 3}" y="{y - 120}" width="6" height="120" fill="#f5f5f5"/>'
            f'<path d="M{x - 80},{y - 100} Q{x},{y - 170} {x + 80},{y - 100} Z" fill="{a}"/>'
            f'<path d="M{x - 27},{y - 100} Q{x},{y - 160} {x + 27},{y - 100} Z" fill="{b}"/>'
            f'<rect x="{x - 70}" y="{y - 14}" width="60" height="10" rx="3" fill="{cols[(k + 1) % 4]}"/>')


def _band_props(c, k):
    """Roadside props for one band (drawn outside the ground clip so they rise above the horizon)."""
    g = []
    side_mid = ROAD_W + 34 + c["side_w"] / 2
    if c["scene"] == "beach":
        if k % 2 == 0:
            g.append(_palm(c, -side_mid - 40, -1))
            g.append(_palm(c, side_mid + 30, 1))
        elif k % 4 == 1:
            g.append(_parasol(c, -side_mid + 20, k))
    else:
        if k % 2 == 0:
            g.append(_palm(c, -(ROAD_W + 100), -1, glow=True))
            g.append(_palm(c, ROAD_W + 100, 1, glow=True))
        elif k % 4 == 1:
            g.append(_neon_sign(c, (1 if k % 8 == 1 else -1) * (side_mid + 60), k))
    return "".join(g)


def _block(color):
    w, h = 64, 56
    y = CAM_H - h
    return (f'<rect x="{-w / 2}" y="{y}" width="{w}" height="{h}" rx="6" fill="{color}"/>'
            f'<rect x="{-w / 2 + 6}" y="{y + 6}" width="{w - 12}" height="10" rx="3" fill="#ffffff" opacity="0.5"/>'
            f'<rect x="{-w / 2}" y="{CAM_H - 6}" width="{w}" height="6" fill="#000" opacity="0.25"/>')


def _billboard(c, text, side):
    x = side * (ROAD_W + 230)
    return (f'<rect x="{x - 6}" y="{CAM_H - 150}" width="12" height="150" fill="{c["post"]}"/>'
            f'<rect x="{x - 95}" y="{CAM_H - 250}" width="190" height="110" rx="6" fill="{c["board"]}" '
            f'stroke="{c["board_text"]}" stroke-width="6"/>'
            f'<text x="{x}" y="{CAM_H - 168}" font-size="64" font-weight="bold" text-anchor="middle" '
            f'fill="{c["board_text"]}">{escape(text)}</text>')


def _gate(c):
    g = [f'<rect x="{-ROAD_W - 60}" y="{CAM_H - 300}" width="24" height="300" fill="{c["post"]}"/>',
         f'<rect x="{ROAD_W + 36}" y="{CAM_H - 300}" width="24" height="300" fill="{c["post"]}"/>']
    sq = 30
    n = int((2 * ROAD_W + 120) / sq)
    for i in range(n):
        for j in range(2):
            col = "#ffffff" if (i + j) % 2 == 0 else "#111111"
            g.append(f'<rect x="{-ROAD_W - 60 + i * sq}" y="{CAM_H - 300 + j * sq}" width="{sq}" height="{sq}" fill="{col}"/>')
    return "".join(g)


def _car(flame_anim="", plate="JRDEV"):
    """Rear view of an original mid-engine supercar, centred on x=0, tyres on y=0."""
    g = ['<g>',
         '<defs><linearGradient id="paint" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" stop-color="#ff3b3b"/><stop offset="0.55" stop-color="#d4101e"/>'
         '<stop offset="1" stop-color="#7a0610"/></linearGradient>'
         '<linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" stop-color="#5b6f93"/><stop offset="1" stop-color="#0e1422"/></linearGradient>'
         '<filter id="glow" x="-50%" y="-200%" width="200%" height="500%">'
         '<feGaussianBlur stdDeviation="3"/></filter></defs>',
         # ground shadow
         '<ellipse cx="0" cy="3" rx="102" ry="8" fill="#000" opacity="0.45"/>',
         # fat rear tyres
         '<rect x="-96" y="-30" width="38" height="31" rx="5" fill="#0b0b0e"/>',
         '<rect x="58" y="-30" width="38" height="31" rx="5" fill="#0b0b0e"/>',
         '<rect x="-92" y="-27" width="30" height="3" fill="#2a2a30"/>',
         '<rect x="62" y="-27" width="30" height="3" fill="#2a2a30"/>',
         # main body: wide hips tapering up to a narrow cabin
         '<path d="M-100,-14 L-100,-40 Q-98,-58 -78,-62 L-46,-66 Q-36,-86 -24,-90 L24,-90 '
         'Q36,-86 46,-66 L78,-62 Q98,-58 100,-40 L100,-14 Z" fill="url(#paint)"/>',
         # shoulder highlights
         '<path d="M-92,-50 Q-88,-58 -70,-60 L-48,-63" fill="none" stroke="#ff8a8a" stroke-width="2" opacity="0.7"/>',
         '<path d="M92,-50 Q88,-58 70,-60 L48,-63" fill="none" stroke="#ff8a8a" stroke-width="2" opacity="0.7"/>',
         # cabin glass
         '<path d="M-38,-68 Q-30,-84 -20,-86 L20,-86 Q30,-84 38,-68 Z" fill="url(#glass)"/>',
         '<path d="M-26,-82 L-6,-82 L-14,-72 L-30,-72 Z" fill="#ffffff" opacity="0.18"/>',
         # engine-cover louvres
         *[f'<rect x="-34" y="{-64 + i * 4}" width="68" height="2" fill="#5c0710"/>' for i in range(3)],
         # side intakes
         '<path d="M-100,-44 L-80,-48 L-80,-30 L-100,-28 Z" fill="#14070a"/>',
         '<path d="M100,-44 L80,-48 L80,-30 L100,-28 Z" fill="#14070a"/>',
         # big rear wing on two struts
         '<rect x="-46" y="-80" width="5" height="16" fill="#16161a"/>',
         '<rect x="41" y="-80" width="5" height="16" fill="#16161a"/>',
         '<path d="M-98,-88 L98,-88 L94,-79 L-94,-79 Z" fill="#16161a"/>',
         '<rect x="-96" y="-88" width="192" height="2" fill="#4a4a55"/>',
         '<rect x="-100" y="-92" width="7" height="16" rx="2" fill="#16161a"/>',
         '<rect x="93" y="-92" width="7" height="16" rx="2" fill="#16161a"/>',
         # full-width LED light bar with glow
         '<rect x="-94" y="-55" width="188" height="11" rx="3" fill="#0a0507"/>',
         '<rect x="-88" y="-51" width="176" height="4" rx="2" fill="#ff1f35" filter="url(#glow)"/>',
         '<rect x="-88" y="-51" width="176" height="3" rx="1.5" fill="#ff4d5e"/>',
         '<rect x="-88" y="-51" width="34" height="3" rx="1.5" fill="#ffe0e3"/>',
         '<rect x="54" y="-51" width="34" height="3" rx="1.5" fill="#ffe0e3"/>',
         # rear panel + plate
         '<rect x="-60" y="-41" width="120" height="15" fill="#1a0a0d" opacity="0.5"/>',
         '<rect x="-21" y="-41" width="42" height="12" rx="1" fill="#f2f2f2"/>',
         '<text x="0" y="-31.5" font-size="9" font-weight="bold" text-anchor="middle" fill="#111">' + escape(plate) + '</text>',
         # diffuser with fins
         '<path d="M-84,-14 L84,-14 L76,-2 L-76,-2 Z" fill="#0d0d10"/>',
         *[f'<rect x="{x}" y="-14" width="3" height="12" fill="#2b2b33"/>' for x in (-60, -40, 37, 57)],
         # twin centre exhausts + flames
         '<circle cx="-12" cy="-9" r="6" fill="#3d3d45"/><circle cx="-12" cy="-9" r="3.5" fill="#050505"/>',
         '<circle cx="12" cy="-9" r="6" fill="#3d3d45"/><circle cx="12" cy="-9" r="3.5" fill="#050505"/>',
         f'<g opacity="0">{flame_anim}'
         '<g><animateTransform attributeName="transform" type="scale" dur="0.12s" repeatCount="indefinite" '
         'calcMode="discrete" values="1 1;1 1.35;1 0.85" additive="sum"/>'
         '<ellipse cx="-12" cy="-1" rx="4.5" ry="6" fill="#ff8a1f"/><ellipse cx="-12" cy="-1" rx="2.2" ry="3.5" fill="#fff1a8"/>'
         '<ellipse cx="12" cy="-1" rx="4.5" ry="6" fill="#ff8a1f"/><ellipse cx="12" cy="-1" rx="2.2" ry="3.5" fill="#fff1a8"/>'
         '</g></g>',
         '</g>']
    return "".join(g)


def _scene_sky(c, theme, width, cyc):
    """Everything above the horizon."""
    import random
    rnd = random.Random(7)
    vx = width / 2
    out = [f'<rect width="{width}" height="{HORIZON + 1}" fill="url(#sky-{theme})"/>']
    if c["scene"] == "beach":
        out.append(f'<circle cx="{width * 0.78:.0f}" cy="40" r="38" fill="{c["sun"][1]}" opacity="0.35"/>')
        out.append(f'<circle cx="{width * 0.78:.0f}" cy="40" r="26" fill="url(#sun-{theme})"/>')
        for i, (cx_, cy_, sc) in enumerate([(120, 38, 1.0), (380, 22, 0.7), (640, 50, 0.85), (900, 30, 0.6)]):
            cloud = (f'<g transform="translate({cx_},{cy_}) scale({sc})" fill="#ffffff" opacity="0.92">'
                     '<rect x="-40" y="0" width="80" height="16" rx="8"/><rect x="-22" y="-12" width="40" height="20" rx="10"/>'
                     '<rect x="4" y="-6" width="30" height="16" rx="8"/></g>')
            out.append(f'<g>{cloud}<animateTransform attributeName="transform" type="translate" '
                       f'values="0 0;{-width - 200} 0" dur="{70 + i * 15}s" repeatCount="indefinite"/></g>')
            out.append(f'<g transform="translate({width + 100},0)">{cloud}<animateTransform attributeName="transform" '
                       f'type="translate" values="{width + 100} 0;{-100} 0" dur="{70 + i * 15}s" repeatCount="indefinite"/></g>')
        # sea to the left reaching the horizon, island on the right
        out.append(f'<rect x="0" y="{HORIZON - 4}" width="{vx}" height="5" fill="{c["water"][0]}"/>')
        isl = [(vx + 40, HORIZON), (vx + 120, HORIZON - 16), (vx + 200, HORIZON - 30), (vx + 260, HORIZON - 22),
               (vx + 340, HORIZON - 34), (vx + 430, HORIZON - 14), (width, HORIZON - 10), (width, HORIZON)]
        out.append(f'<polygon points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in isl)}" fill="#3f9a5a"/>')
        out.append(f'<polygon points="{" ".join(f"{x:.0f},{y + 6:.0f}" for x, y in isl[:-2])} {width},{HORIZON} '
                   f'{vx + 40},{HORIZON}" fill="#2f7d47" opacity="0.6"/>')
        # sailboat bobbing on the sea
        out.append(f'<g transform="translate({vx * 0.42:.0f},{HORIZON - 6})"><g>'
                   '<path d="M-14,0 L14,0 L10,5 L-10,5 Z" fill="#ffffff"/><path d="M0,-2 L0,-26 L12,-4 Z" fill="#ffffff"/>'
                   '<path d="M-2,-4 L-2,-20 L-11,-4 Z" fill="#ff4d6d"/>'
                   '<animateTransform attributeName="transform" type="translate" values="0 0;0 -1.5;0 0" dur="2.4s" repeatCount="indefinite"/>'
                   '</g></g>')
        # seagulls
        for gx, gy, d in ((260, 60, 0.9), (290, 52, 1.1), (560, 34, 1.0)):
            out.append(f'<path d="M{gx - 7},{gy} Q{gx - 3},{gy - 5} {gx},{gy} Q{gx + 3},{gy - 5} {gx + 7},{gy}" '
                       f'fill="none" stroke="#2b3a4a" stroke-width="1.6">'
                       f'<animate attributeName="d" dur="{d}s" repeatCount="indefinite" values="'
                       f'M{gx - 7},{gy} Q{gx - 3},{gy - 5} {gx},{gy} Q{gx + 3},{gy - 5} {gx + 7},{gy};'
                       f'M{gx - 7},{gy - 3} Q{gx - 3},{gy + 2} {gx},{gy} Q{gx + 3},{gy + 2} {gx + 7},{gy - 3};'
                       f'M{gx - 7},{gy} Q{gx - 3},{gy - 5} {gx},{gy} Q{gx + 3},{gy - 5} {gx + 7},{gy}"/></path>')
        return out

    # ---- Las Vegas night ---------------------------------------------------------
    for _ in range(70):                                   # stars
        sx, sy = rnd.uniform(0, width), rnd.uniform(4, HORIZON - 50)
        r = rnd.choice((0.7, 0.9, 1.2))
        tw = (f'<animate attributeName="opacity" values="1;0.2;1" dur="{rnd.uniform(1.5, 4):.1f}s" '
              f'begin="{rnd.uniform(0, 3):.1f}s" repeatCount="indefinite"/>' if rnd.random() < 0.35 else "")
        out.append(f'<circle cx="{sx:.0f}" cy="{sy:.0f}" r="{r}" fill="#ffffff" opacity="0.8">{tw}</circle>')
    # searchlights sweeping from behind the skyline
    for bx_, d, col in ((vx - 260, 7, "#7fe8ff"), (vx + 250, 9, "#ffd1f5")):
        out.append(f'<g transform="translate({bx_:.0f},{HORIZON})"><path d="M-4,0 L-46,-260 L46,-260 L4,0 Z" '
                   f'fill="{col}" opacity="0.13"><animateTransform attributeName="transform" type="rotate" '
                   f'values="-28;28;-28" dur="{d}s" repeatCount="indefinite"/></path></g>')
    # horizon city glow
    out.append(f'<rect x="0" y="{HORIZON - 40}" width="{width}" height="40" fill="url(#glow-{theme})"/>')
    # skyline: casino towers with lit windows and neon crowns
    x = 0
    k = 0
    while x < width:
        w_ = rnd.randint(22, 52)
        gap_center = abs(x + w_ / 2 - vx) < 30
        h_ = rnd.randint(18, 40) if gap_center else rnd.randint(26, 92)
        top = HORIZON - h_
        out.append(f'<rect x="{x}" y="{top}" width="{w_}" height="{h_}" fill="#140d2a"/>')
        for wy in range(top + 5, HORIZON - 3, 6):
            for wx in range(x + 4, x + w_ - 3, 6):
                if rnd.random() < 0.38:
                    colw = rnd.choice(("#ffe9a8", "#ffe9a8", "#9ff3ff", "#ffc2f0"))
                    tw = (f'<animate attributeName="opacity" values="1;0;1" dur="{rnd.uniform(2, 6):.1f}s" '
                          f'begin="{rnd.uniform(0, 4):.1f}s" repeatCount="indefinite" calcMode="discrete"/>'
                          if rnd.random() < 0.06 else "")
                    out.append(f'<rect x="{wx}" y="{wy}" width="2" height="2" fill="{colw}" opacity="0.85">{tw}</rect>')
        if rnd.random() < 0.55:
            col = c["neon"][k % len(c["neon"])]
            out.append(f'<rect x="{x}" y="{top}" width="{w_}" height="2" fill="{col}"/>')
            if rnd.random() < 0.5:
                out.append(f'<rect x="{x + w_ / 2 - 1:.0f}" y="{top - 12}" width="2" height="12" fill="{col}"/>'
                           f'<circle cx="{x + w_ / 2:.0f}" cy="{top - 13}" r="2.5" fill="{col}">'
                           f'<animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite"/></circle>')
        x += w_ + rnd.randint(0, 6)
        k += 1
    return out


def _scene_ground_base(c, theme, width, vx):
    """Static ground under the moving bands: perspective wedges from the vanishing point."""
    S = 2.0
    yb = HORIZON + CAM_H * S
    edge = ROAD_W + 34 + c["side_w"]
    far = width * 3
    left_col = c["water"][0] if c["scene"] == "beach" else c["ground"][0]
    out = [f'<polygon points="{vx},{HORIZON} {vx - edge * S:.0f},{yb} {-far},{yb} {-far},{HORIZON}" fill="{left_col}"/>',
           f'<polygon points="{vx},{HORIZON} {vx + edge * S:.0f},{yb} {far},{yb} {far},{HORIZON}" fill="{c["ground"][0]}"/>',
           f'<polygon points="{vx},{HORIZON} {vx - edge * S:.0f},{yb} {vx + edge * S:.0f},{yb}" fill="{c["side"][0]}"/>',
           f'<polygon points="{vx},{HORIZON} {vx - (ROAD_W + 34) * S:.0f},{yb} {vx + (ROAD_W + 34) * S:.0f},{yb}" '
           f'fill="{c["kerb"][1]}"/>',
           f'<polygon points="{vx},{HORIZON} {vx - ROAD_W * S:.0f},{yb} {vx + ROAD_W * S:.0f},{yb}" fill="{c["road"][0]}"/>']
    if c["scene"] == "beach":   # shoreline foam line
        out.append(f'<line x1="{vx}" y1="{HORIZON}" x2="{vx - (edge + 8) * S:.0f}" y2="{yb}" stroke="{c["foam"]}" '
                   f'stroke-width="3" opacity="0.8"/>')
    return out


# --------------------------------------------------------------------------- #
#  Main renderer                                                               #
# --------------------------------------------------------------------------- #
def render_race(theme, stats, width, user, plate="ARCADE"):
    c = PALETTES[theme]
    cal = stats.get("calendar") or {}
    weeks = cal.get("weeks") or []
    total = cal.get("total", 0)
    start = dt.date.fromisoformat(cal["start"]) if cal.get("start") else None
    n_weeks = max(1, len(weeks))
    # one track position per day: active days get room, empty stretches fast-forward
    days_flat = []                       # (date_index, weekday, count, level)
    for w, wk in enumerate(weeks):
        for wd, cnt, lvl in wk:
            days_flat.append((w * 7 + wd, wd, cnt, lvl))
    n_active = sum(1 for d_ in days_flat if d_[2] > 0)
    n_empty = len(days_flat) - n_active
    empty_z = 1.0 if not n_active else max(0.12, min(1.0, 0.5 * DAY_Z * n_active / max(n_empty, 1)))
    pos, acc = {}, DAY_Z
    for idx, wd, cnt, lvl in days_flat:
        acc += DAY_Z if cnt > 0 else empty_z
        pos[idx] = acc
    track = acc + DAY_Z
    m = Motion(track)
    cyc = m.cycle
    vx = width / 2
    sh = 'stroke="#000" stroke-width="0.8" paint-order="stroke"'
    sh_sm = 'stroke="#000" stroke-width="0.35" stroke-opacity="0.6" paint-order="stroke"'

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{H}" viewBox="0 0 {width} {H}" '
           f'font-family="Consolas,\'DejaVu Sans Mono\',monospace">',
           '<defs>',
           f'<linearGradient id="sky-{theme}" x1="0" y1="0" x2="0" y2="1">'
           + "".join(f'<stop offset="{i / 3:.2f}" stop-color="{col}"/>' for i, col in enumerate(c["sky"]))
           + '</linearGradient>',
           f'<linearGradient id="sun-{theme}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c.get("sun", ["#fff", "#fff"])[0]}"/>'
           f'<stop offset="1" stop-color="{c.get("sun", ["#fff", "#fff"])[1]}"/></linearGradient>',
           f'<linearGradient id="glow-{theme}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff2bd6" stop-opacity="0"/>'
           f'<stop offset="1" stop-color="#ff7ad9" stop-opacity="0.45"/></linearGradient>',
           f'<clipPath id="card-{theme}"><rect width="{width}" height="{H}" rx="15"/></clipPath>',
           f'<clipPath id="ground-{theme}"><rect y="{HORIZON}" width="{width}" height="{H - HORIZON}"/></clipPath>',
           '</defs>',
           f'<g clip-path="url(#card-{theme})">']

    # ---- sky / skyline ------------------------------------------------------------
    out += _scene_sky(c, theme, width, cyc)

    # ---- ground: static base + moving stripe bands -----------------------------------
    out.append(f'<g clip-path="url(#ground-{theme})">')
    out += _scene_ground_base(c, theme, width, vx)

    K = int(math.ceil((Z_FAR - Z_NEAR) / BAND_L)) + 1
    loop = K * BAND_L
    zs_band = [z for z in Z_SAMPLES if z < Z_NEAR + loop]
    bands = []
    for k in range(K):
        z0 = Z_NEAR + k * BAND_L
        kf = [(0.0, 1 / z0)]
        p = 0
        while True:
            base = z0 + p * loop
            done = False
            for zs in zs_band:
                if p == 0 and zs >= z0:
                    continue
                t = m.inv(base - zs)
                if t is None:
                    done = True
                    break
                kf.append((t, 1 / zs))
            if done:
                break
            t_w = m.inv(base - Z_NEAR)
            kf.append((t_w + 1e-3, 1 / (Z_NEAR + loop)))   # wrap to the far end
            p += 1
        zend = Z_NEAR + ((z0 - Z_NEAR - m.dmax) % loop)
        kf.append((cyc, 1 / zend))
        bands.append((z0, k, kf))
    for _, k, kf in reversed(bands):
        out.append(f'<g transform="translate({vx},{HORIZON})"><g>{_band_ground(c, k, width)}{_anim_scale(kf, cyc)}</g></g>')
    out.append('</g>')
    for _, k, kf in reversed(bands):          # roadside props rise above the horizon
        props = _band_props(c, k)
        if props:
            out.append(f'<g transform="translate({vx},{HORIZON})"><g>{props}{_anim_scale(kf, cyc)}</g></g>')

    # ---- world objects: month billboards, contribution blocks, finish gate ----------
    objs = []                       # (track distance, svg, hide-at-depth)
    if start:
        last = None
        for idx, *_ in days_flat:
            d = start + dt.timedelta(days=idx)
            if d.month != last:
                if last is not None:
                    side = 1 if len(objs) % 2 == 0 else -1
                    objs.append((pos[idx] + 0.4, _billboard(c, d.strftime("%b").upper(), side), 0.6))
                last = d.month

    collects = []                   # (t, count, lane_x)
    for idx, wd, cnt, lvl in days_flat:
        if cnt <= 0:
            continue
        lane = LANES[(idx * 5 + cnt) % 3]
        d_obj = pos[idx]
        t_hit = m.inv(d_obj - 1.0)
        if t_hit is None:
            continue
        collects.append((t_hit, cnt, lane))
        objs.append((d_obj, f'<g transform="translate({lane},0)">{_block(c["lv"][max(lvl, 1)])}</g>', 1.0))

    objs.append((track + 1.0, _gate(c), 0.6))

    for d_obj, content, hide_at in sorted(objs, key=lambda o: -o[0]):
        kf = _object_keyframes(m, d_obj)
        enter = m.inv(d_obj - Z_FAR) if d_obj > Z_FAR else 0.0
        leave = m.inv(d_obj - hide_at)
        changes = [(0, d_obj <= Z_FAR)]
        if enter:
            changes.append((enter, 1))
        if leave is not None:
            changes.append((leave, 0))
        out.append(f'<g transform="translate({vx},{HORIZON})"><g opacity="0">{_visibility_anim(changes, cyc)}'
                   f'<g>{content}{_anim_scale(kf, cyc)}</g></g></g>')

    # ---- player car: steers into each block's lane ----------------------------------
    steer = [(0.0, 0.0)]
    for t, _, lane in sorted(collects):
        t_start = max(steer[-1][0] + 0.05, t - 0.45)
        if t_start < t:
            steer.append((t_start, steer[-1][1]))
        steer.append((t, lane))
    steer += [(m.tf + 0.6, 0.0), (cyc, 0.0)]
    kt, vals, last = [], [], -1.0
    for t, x in steer:
        k = 0.0 if not kt else max(t / cyc, last + 1e-4)
        if k > 1:
            continue
        kt.append(k)
        vals.append(x)
        last = k
    if kt[-1] < 1:
        kt.append(1.0)
        vals.append(0.0)
    car_y = HORIZON + CAM_H + 22
    out.append(f'<g transform="translate({vx},{car_y})"><g>'
               f'<animateTransform attributeName="transform" type="translate" dur="{cyc:.2f}s" repeatCount="indefinite" '
               f'keyTimes="{";".join(_f(k) for k in kt)}" values="{";".join(f"{v:.0f} 0" for v in vals)}"/>'
               f'<g><animateTransform attributeName="transform" type="translate" dur="0.18s" repeatCount="indefinite" '
               f'calcMode="discrete" values="0 0;0 -1.5"/>'
               f'{_car(_visibility_anim([(START_T - 0.2, 1), (START_T + ACC_T + 0.6, 0), (m.tf - 0.3, 1), (m.tf + 0.4, 0)], cyc), plate)}'
               f'</g></g></g>')

    for t, n, lane in collects:   # "+N" popups
        k1, k2 = t / cyc, min(0.999, (t + 0.6) / cyc)
        x, y = vx + lane, car_y - 100
        out.append(f'<text x="{x:.0f}" y="{y}" font-size="20" font-weight="bold" text-anchor="middle" '
                   f'fill="{c["lv"][4]}" {sh} opacity="0">+{n}'
                   f'<animate attributeName="opacity" dur="{cyc:.2f}s" repeatCount="indefinite" '
                   f'keyTimes="0;{_f(k1)};{_f(k1 + 0.0001)};{_f(k2)};1" values="0;0;1;0;0"/>'
                   f'<animate attributeName="y" dur="{cyc:.2f}s" repeatCount="indefinite" '
                   f'keyTimes="0;{_f(k1)};{_f(k2)};1" values="{y};{y};{y - 30};{y - 30}"/></text>')

    # ---- HUD --------------------------------------------------------------------------
    out.append('<rect x="10" y="10" width="300" height="44" rx="8" fill="#000" opacity="0.45"/>')
    out.append(f'<rect x="{width - 215}" y="10" width="205" height="44" rx="8" fill="#000" opacity="0.45"/>')
    out.append(f'<text x="22" y="30" font-size="16" font-weight="bold" fill="{c["accent"]}" {sh} '
               f'letter-spacing="2">1UP {escape(user.upper())}</text>')
    out.append(f'<text x="22" y="46" font-size="10" fill="{c["hud_dim"]}" {sh_sm} letter-spacing="1">'
               f'CONTRIBUTION GRAND PRIX · LAST 12 MONTHS</text>')

    timeline, acc = [(0.0, 0)], 0
    for t, n, _ in sorted(collects):
        acc += n
        timeline.append((t, acc))
    sx = width - 22 - 6 * 12
    out.append(f'<text x="{sx - 8}" y="30" font-size="16" font-weight="bold" fill="{c["hud_dim"]}" {sh} '
               f'text-anchor="end" letter-spacing="2">SCORE</text>')
    for place in range(6):
        div = 10 ** (5 - place)
        for digit in range(10):
            changes, prev = [], None
            for t, v in timeline:
                vis = (v // div) % 10 == digit
                if vis != prev:
                    changes.append((t, vis))
                    prev = vis
            if any(v for _, v in changes):
                out.append(f'<text x="{sx + place * 12}" y="30" font-size="16" font-weight="bold" fill="{c["hud"]}" '
                           f'{sh}>{digit}{_visibility_anim(changes, cyc)}</text>')
    out.append(f'<text x="{width - 22}" y="46" font-size="10" fill="{c["hud_dim"]}" {sh_sm} text-anchor="end" '
               f'letter-spacing="1">CONTRIBUTIONS COLLECTED</text>')

    # dark backing panels so the bottom HUD reads on bright scenery
    out.append(f'<rect x="10" y="{H - 48}" width="246" height="38" rx="8" fill="#000" opacity="0.45"/>')
    out.append(f'<rect x="{width - 150}" y="{H - 48}" width="140" height="38" rx="8" fill="#000" opacity="0.45"/>')

    # speedometer: follows the real speed curve, wobbles while cruising,
    # and kicks up with a boost every time a contribution block is collected
    hits = [t for t, _, _ in collects]

    def kmh(t):
        dt_ = 1e-3
        v = (m.D(t + dt_) - m.D(max(t - dt_, 0))) / (2 * dt_) / m.vmax
        if v <= 0.002:
            return 0
        wob = 7 * math.sin(t * 1.7) + 4 * math.sin(t * 4.9 + 1.3)
        boost = sum(34 * (1 - (t - h) / 0.9) for h in hits if 0 <= t - h < 0.9)
        return max(0, int(round(v * (288 + wob) + boost * v)))

    sp, t = [], 0.0
    while t < cyc:
        val = kmh(t)
        if not sp or sp[-1][1] != val:
            sp.append((t, val))
        t += 0.12
    for i, (t, val) in enumerate(sp):
        t_end = sp[i + 1][0] if i + 1 < len(sp) else cyc + 1
        out.append(f'<text x="{width - 66}" y="{H - 16}" font-size="24" font-weight="bold" font-style="italic" '
                   f'text-anchor="end" fill="{c["accent"]}" {sh} opacity="0">{val:03d}'
                   f'{_visibility_anim([(t, 1), (t_end, 0)], cyc)}</text>')
    # needle-style bar under the number
    bar_kt, bar_v = [], []
    for t, val in sp:
        bar_kt.append(t / cyc)
        bar_v.append(min(val, 340) / 340 * 118)
    if bar_kt[-1] < 1:
        bar_kt.append(1.0)
        bar_v.append(bar_v[-1])
    out.append(f'<rect x="{width - 140}" y="{H - 13}" width="118" height="3" fill="#000" opacity="0.5"/>')
    out.append(f'<rect x="{width - 140}" y="{H - 13}" width="0" height="3" fill="{c["accent"]}">'
               f'<animate attributeName="width" dur="{cyc:.2f}s" repeatCount="indefinite" calcMode="discrete" '
               f'keyTimes="{";".join(_f(k) for k in bar_kt)}" values="{";".join(f"{v:.0f}" for v in bar_v)}"/></rect>')
    out.append(f'<text x="{width - 22}" y="{H - 16}" font-size="11" font-weight="bold" text-anchor="end" '
               f'fill="{c["hud"]}" {sh}>KM/H</text>')

    # course map with moving marker
    bx, bw, by = 22, 220, H - 22
    out.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="4" fill="#000" opacity="0.45"/>')
    out.append(f'<text x="{bx}" y="{by - 8}" font-size="10" fill="{c["hud"]}" {sh_sm} letter-spacing="1">COURSE</text>')
    if start:
        end_d = start + dt.timedelta(days=max(len(days_flat) - 1, 0))
        out.append(f'<text x="{bx + bw}" y="{by - 8}" font-size="10" text-anchor="end" fill="{c["hud"]}" {sh_sm}>'
                   f'{start.strftime("%b %y").upper()} - {end_d.strftime("%b %y").upper()}</text>')
    # marker follows the calendar date the car is currently driving through
    n_days = max(len(days_flat) - 1, 1)
    mk = [(0.0, 0.0)]
    for idx, *_ in days_flat[::3] + days_flat[-1:]:
        t = m.inv(pos[idx])
        if t is not None and t > mk[-1][0] + 1e-3:
            mk.append((t, idx / n_days))
    mk.append((cyc, 1.0 if m.dmax >= max(pos.values() or [0]) else mk[-1][1]))
    kt, vals, last = [], [], -1.0
    for t, frac in mk:
        k = 0.0 if not kt else max(t / cyc, last + 1e-4)
        if k > 1:
            continue
        kt.append(k)
        vals.append(bx - 3 + bw * frac)
        last = k
    if kt[-1] < 1:
        kt.append(1.0)
        vals.append(vals[-1])
    out.append(f'<rect x="{bx - 3}" y="{by - 4}" width="6" height="12" fill="{c["accent"]}" stroke="#000">'
               f'<animate attributeName="x" dur="{cyc:.2f}s" repeatCount="indefinite" '
               f'keyTimes="{";".join(_f(k) for k in kt)}" values="{";".join(f"{v:.1f}" for v in vals)}"/></rect>')

    # start lights + GO!
    lx = vx - 33
    for i in range(3):
        on = 0.5 + i * 0.7
        out.append(f'<circle cx="{lx + i * 33}" cy="66" r="12" fill="#222" stroke="#000" stroke-width="2" opacity="0">'
                   + _visibility_anim([(0, 1), (START_T + 1.0, 0)], cyc) + '</circle>')
        out.append(f'<circle cx="{lx + i * 33}" cy="66" r="9" fill="{c["red"]}" opacity="0">'
                   + _visibility_anim([(on, 1), (START_T - 0.3, 0)], cyc) + '</circle>')
        out.append(f'<circle cx="{lx + i * 33}" cy="66" r="9" fill="{c["green"]}" opacity="0">'
                   + _visibility_anim([(START_T - 0.3, 1), (START_T + 1.0, 0)], cyc) + '</circle>')
    out.append(f'<text x="{vx}" y="106" font-size="28" font-weight="bold" font-style="italic" text-anchor="middle" '
               f'fill="{c["accent"]}" {sh} opacity="0">GO!'
               + _visibility_anim([(START_T - 0.3, 1), (START_T + 1.0, 0)], cyc) + '</text>')

    # finish banner + yearly total
    blink = [(m.tf + i * 0.45, i % 2 == 0) for i in range(int(END_T / 0.45))]
    out.append(f'<text x="{vx}" y="76" font-size="32" font-weight="bold" font-style="italic" text-anchor="middle" '
               f'fill="{c["accent"]}" {sh} letter-spacing="3" opacity="0">FINISH!{_visibility_anim(blink, cyc)}</text>')
    out.append(f'<text x="{vx}" y="98" font-size="13" font-weight="bold" text-anchor="middle" fill="{c["hud"]}" '
               f'{sh} letter-spacing="1" opacity="0">{total:,} CONTRIBUTIONS IN THE LAST YEAR'
               + _visibility_anim([(m.tf, 1)], cyc) + '</text>')

    out.append("</g></svg>")
    return "\n".join(out)
