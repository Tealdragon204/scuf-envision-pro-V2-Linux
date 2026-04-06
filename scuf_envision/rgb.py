"""
RGB animation engine for the SCUF Envision Pro V2.

Phase 12 extension: 12 animation modes ported from OpenLinkHub's Go implementation.
All frame functions produce 27-byte planar buffers: R[0-8] G[9-17] B[18-26].
"""

import math
import random
import threading
import time
import logging

from .constants import RGB_NUM_LEDS, RGB_FRAME_SIZE

log = logging.getLogger(__name__)

FRAME_INTERVAL = 0.040  # 40ms = 25 fps, matching OLH's animation loop


# ── colour helpers ────────────────────────────────────────────────────────────

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
    """h in 0-1, s/v in 0-1 → (r, g, b) each 0-255."""
    if s == 0:
        c = v * 255
        return c, c, c
    h6 = h * 6
    i = int(h6) % 6
    f = h6 - int(h6)
    p, q, t = v*(1-s), v*(1-s*f), v*(1-s*(1-f))
    rgb = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i]
    return rgb[0]*255, rgb[1]*255, rgb[2]*255


def _hue_to_rgb(h: float) -> tuple[float, float, float]:
    """h in 0-1 → (r, g, b) 0-255 via 5-segment linear wheel (OLH style)."""
    h = h % 1.0
    if h < 1/6:   return 255, h * 6 * 255, 0
    if h < 2/6:   return (2/6 - h) * 6 * 255, 255, 0
    if h < 3/6:   return 0, 255, (h - 2/6) * 6 * 255
    if h < 4/6:   return 0, (4/6 - h) * 6 * 255, 255
    if h < 5/6:   return (h - 4/6) * 6 * 255, 0, 255
    return 255, 0, (1 - h) * 6 * 255


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _frame(rv: list, gv: list, bv: list) -> bytes:
    """Assemble planar 27-byte RGB buffer from per-LED component lists."""
    return bytes(max(0, min(255, int(x))) for x in rv + gv + bv)


# ── pastel palette — 20 entries verbatim from OLH ────────────────────────────

_PASTEL = [
    (244,253,255),(194,240,255),(163,230,255),(109,213,237),(73,197,229),
    (66,179,217),(109,168,219),(130,155,219),(144,148,220),(153,148,218),
    (175,146,209),(193,148,198),(211,148,186),(227,148,175),(241,148,165),
    (253,148,156),(255,144,142),(255,138,121),(255,131,94),(255,121,49),
]


# ── frame functions ───────────────────────────────────────────────────────────
# All share signature fn(t, **params) → bytes(27).
# Unused params are absorbed by **_ so callers can always pass the full param dict.

def _frame_off(**_) -> bytes:
    return bytes(RGB_FRAME_SIZE)


def _frame_static(r, g, b, brightness, **_) -> bytes:
    s = brightness / 100
    return _frame([int(r*s)]*9, [int(g*s)]*9, [int(b*s)]*9)


def _frame_rainbow(t, speed, brightness, **_) -> bytes:
    s = brightness / 100
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        pos = ((i / RGB_NUM_LEDS) + t * 4 / max(speed, 0.1)) % 1.0
        r, g, b = _hue_to_rgb(pos)
        rv.append(r*s); gv.append(g*s); bv.append(b*s)
    return _frame(rv, gv, bv)


def _frame_pastelrainbow(t, speed, brightness, **_) -> bytes:
    s = brightness / 100
    m = len(_PASTEL)
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        pos = ((i / RGB_NUM_LEDS) + t * 4 / max(speed, 0.1)) % 1.0
        idx = pos * m
        lo = int(idx) % m
        hi = (lo + 1) % m
        f = idx - int(idx)
        r = _PASTEL[lo][0] + (_PASTEL[hi][0] - _PASTEL[lo][0]) * f
        g = _PASTEL[lo][1] + (_PASTEL[hi][1] - _PASTEL[lo][1]) * f
        b = _PASTEL[lo][2] + (_PASTEL[hi][2] - _PASTEL[lo][2]) * f
        rv.append(r*s); gv.append(g*s); bv.append(b*s)
    return _frame(rv, gv, bv)


def _frame_watercolor(t, speed, brightness, **_) -> bytes:
    # HSV with low saturation gives the watercolor wash effect (OLH: s=0.4)
    s = brightness / 100
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        pos = ((i / RGB_NUM_LEDS) + t / max(speed, 0.1)) % 1.0
        r, g, b = _hsv_to_rgb(pos, 0.4, 1.0)
        rv.append(r*s); gv.append(g*s); bv.append(b*s)
    return _frame(rv, gv, bv)


def _frame_rotator(t, speed, brightness, **_) -> bytes:
    # All LEDs same hue, hue rotates over time
    s = brightness / 100
    r, g, b = _hue_to_rgb((t / max(speed, 0.1)) % 1.0)
    return _frame([r*s]*9, [g*s]*9, [b*s]*9)


def _frame_colorpulse(t, r, g, b, r2, g2, b2, speed, brightness, **_) -> bytes:
    # Ping-pong lerp between color and color2
    s = brightness / 100
    cycle = t / max(speed, 0.1)
    p = cycle % 1.0
    if int(cycle) % 2:
        p = 1 - p
    rv = _lerp(r, r2, p) * s
    gv = _lerp(g, g2, p) * s
    bv = _lerp(b, b2, p) * s
    return _frame([rv]*9, [gv]*9, [bv]*9)


def _frame_colorshift(t, r, g, b, r2, g2, b2, speed, brightness, **_) -> bytes:
    # Alternate direction on each full cycle (OLH colorshift behaviour)
    s = brightness / 100
    cycle = t / max(speed, 0.1)
    p = cycle % 1.0
    if int(cycle) % 2:
        p = 1 - p
    rv = _lerp(r, r2, p) * s
    gv = _lerp(g, g2, p) * s
    bv = _lerp(b, b2, p) * s
    return _frame([rv]*9, [gv]*9, [bv]*9)


def _frame_wave(t, r, g, b, speed, brightness, **_) -> bytes:
    # Sinusoidal intensity modulation sweeping across the LED array
    s = brightness / 100
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        intensity = (math.sin(i / RGB_NUM_LEDS * math.pi * 2 - t * 4 / max(speed, 0.1)) + 1) / 2
        rv.append(r * intensity * s)
        gv.append(g * intensity * s)
        bv.append(b * intensity * s)
    return _frame(rv, gv, bv)


_storm_state = [False] * RGB_NUM_LEDS


def _frame_storm(r, g, b, r2, g2, b2, brightness, **_) -> bytes:
    # Each LED randomly flips between two colors with low probability per frame
    s = brightness / 100
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        if random.random() < 0.001:
            _storm_state[i] = not _storm_state[i]
        cr, cg, cb = (r2, g2, b2) if _storm_state[i] else (r, g, b)
        rv.append(cr*s); gv.append(cg*s); bv.append(cb*s)
    return _frame(rv, gv, bv)


def _frame_flickering(t, r, g, b, r2, g2, b2, speed, brightness, **_) -> bytes:
    # Gradient across LEDs with random blackout (candle effect)
    s = brightness / 100
    rv, gv, bv = [], [], []
    for i in range(RGB_NUM_LEDS):
        f = i / max(RGB_NUM_LEDS - 1, 1)
        cr = _lerp(r, r2, f)
        cg = _lerp(g, g2, f)
        cb = _lerp(b, b2, f)
        if random.randint(0, max(1, int(RGB_NUM_LEDS * max(speed, 0.1)))) == 1:
            cr = cg = cb = 0
        rv.append(cr*s); gv.append(cg*s); bv.append(cb*s)
    return _frame(rv, gv, bv)


def _read_cpu_temp() -> float:
    """Read CPU temp in °C from the first readable sysfs thermal zone."""
    import glob
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(path) as f:
                return int(f.read()) / 1000.0
        except OSError:
            pass
    return 0.0


def _frame_cpu_temperature(brightness, min_temp=40.0, max_temp=90.0, **_) -> bytes:
    # Blue (cold) → red (hot), matching OLH temperature mode
    temp = _read_cpu_temp()
    norm = max(0.0, min(1.0, (temp - min_temp) / max(max_temp - min_temp, 1.0)))
    r, g, b = _hsv_to_rgb((1 - norm) * 0.667, 1.0, 1.0)  # hue 0.667 = blue
    s = brightness / 100
    return _frame([r*s]*9, [g*s]*9, [b*s]*9)


# ── dispatch table ────────────────────────────────────────────────────────────

_DISPATCH = {
    'off':             _frame_off,
    'static':          _frame_static,
    'rainbow':         _frame_rainbow,
    'pastelrainbow':   _frame_pastelrainbow,
    'watercolor':      _frame_watercolor,
    'rotator':         _frame_rotator,
    'colorpulse':      _frame_colorpulse,
    'colorshift':      _frame_colorshift,
    'wave':            _frame_wave,
    'storm':           _frame_storm,
    'flickering':      _frame_flickering,
    'cpu-temperature': _frame_cpu_temperature,
}

RGB_MODES: list[str] = list(_DISPATCH)


# ── animator ──────────────────────────────────────────────────────────────────

class RGBAnimator:
    """Drives one RGB animation mode in a daemon thread.

    For static/off, writes a single frame then blocks until stopped.
    For animated modes, writes at 40ms intervals (25 fps) matching OLH's loop.
    """

    _STATIC_MODES = frozenset({'static', 'off'})

    def __init__(self, controller, mode: str, **params):
        self._ctrl = controller
        self._mode = mode if mode in _DISPATCH else 'static'
        if self._mode != mode:
            log.warning("Unknown RGB mode %r, falling back to static", mode)
        self._params = params
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"rgb-{self._mode}"
        )
        self._thread.start()
        log.info("RGB animator started: mode=%s", self._mode)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self):
        fn = _DISPATCH[self._mode]
        t0 = time.monotonic()
        while not self._stop.is_set():
            try:
                frame = fn(t=time.monotonic() - t0, **self._params)
                self._ctrl.write_frame(frame)
            except Exception as e:
                log.debug("RGB frame error [%s]: %s", self._mode, e)
            if self._mode in self._STATIC_MODES:
                self._stop.wait()   # write once, then idle until stopped
            else:
                self._stop.wait(FRAME_INTERVAL)
