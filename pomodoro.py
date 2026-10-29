from machine import Pin, I2C, PWM
import neopixel
import time
import math
import struct
import veml6040

# Globals
DARK_MAX = 1100
AXES = (2, 0, 1)
SIGNS = (1, 1, -1)

SHAKE_G = 0.8
TILT_MIN = 0.2
TILT_MAX = 0.7
OFF_PHONE_MS = 2000
MINUTE_MS = 60000

COLORS = {"set": (0, 0, 50), "armed": (30, 30, 30), "focus": (50, 0, 0), "done": (0, 50, 0), "break": (0, 30, 0)}
BEEP = ((1500, 60), (2000, 90))
DONE = ((1568, 120), (1319, 120), (2093, 300))
SAD = ((392, 250), (330, 250), (262, 450))

focus_min = 25
break_min = 5
count = 0
state = "armed"
end_time = 0
on_phone = False
last_seen = 0
peaks = []
shaking = False
flipped = False
flip_since = 0
tilt_start = 0
last_step = 0


# Functions
def degree2servo(angle):
    angle = max(0, min(180, angle))
    ms_pulse = angle / 90 + 0.5
    return int(ms_pulse / 20 * 65535)


def needle(minutes):
    dial.duty_u16(degree2servo(minutes * (9 if flipped else 3)))


def show():
    needle(break_min if flipped else focus_min)


def tune(notes):
    for f, ms in notes:
        buzzer.freq(f)
        buzzer.duty_u16(20000)
        time.sleep_ms(ms)
    buzzer.duty_u16(0)


def read_accel():
    v = struct.unpack("<hhh", i2c2.readfrom_mem(0x19, 0x28 | 0x80, 6))
    return [SIGNS[i] * v[AXES[i]] / 16000 for i in range(3)]


def check_shake(x, y, z, now):
    global peaks, shaking
    if abs(math.sqrt(x * x + y * y + z * z) - 1) > SHAKE_G:
        peaks.append(now)
    peaks = [p for p in peaks if time.ticks_diff(now, p) < 500]
    if len(peaks) >= 5:
        shaking = True
    elif shaking and not peaks:
        shaking = False
        return True
    return False


def check_flip(z, now):
    global flipped, flip_since
    want = True if z < -0.5 else False if z > 0.5 else flipped
    if want == flipped:
        flip_since = now
        return False
    if time.ticks_diff(now, flip_since) >= 800:
        flipped = want
        return True
    return False


def check_phone(now):
    global on_phone, last_seen
    dark = sensor.read_white() < DARK_MAX
    if dark:
        last_seen = now
        on_phone = True
    elif time.ticks_diff(now, last_seen) > OFF_PHONE_MS:
        on_phone = False
    return dark


def go(new, now):
    global state, end_time, count
    state = new
    lights[0] = COLORS[new]
    if new in ("set", "armed"):
        show()
    elif new == "focus":
        end_time = time.ticks_add(now, focus_min * MINUTE_MS)
    elif new == "done":
        count += 1
        needle(0)
        tune(DONE)
        return
    elif new == "break":
        end_time = time.ticks_add(now, (15 if count % 4 == 0 else break_min) * MINUTE_MS)
    tune(BEEP)
    print("state: %s  focus %d  break %d  count %d" % (state, focus_min, break_min, count))


def adjust(x, now):
    global focus_min, break_min, tilt_start, last_step
    t = -x if flipped else x
    if abs(t) < TILT_MIN or abs(t) > TILT_MAX:
        tilt_start = now
        return
    if time.ticks_diff(now, tilt_start) < 500 or time.ticks_diff(now, last_step) < 300:
        return
    last_step = now
    d = 1 if t > 0 else -1
    if flipped:
        break_min = max(1, min(20, break_min + d))
        needle(break_min)
    else:
        focus_min = max(5, min(60, focus_min + d))
        needle(focus_min)


def loop(now):
    global count
    x, y, z = read_accel()
    shake = check_shake(x, y, z, now)
    flip = check_flip(z, now)
    dark = check_phone(now)
    lights[1] = (0, 30, 0) if dark else (0, 0, 0)
    if flip and state in ("set", "armed"):
        show()

    if state == "set":
        if shake:
            go("armed", now)
        elif not peaks:
            adjust(x, now)
    elif shake and not dark:
        count = 0
        go("set", now)
    elif state == "armed" and on_phone and not flipped:
        go("focus", now)
    elif state == "focus":
        left = time.ticks_diff(end_time, now)
        if not on_phone:
            print("interrupted with %d min left" % (left // MINUTE_MS))
            tune(SAD)
            go("armed", now)
        elif left <= 0:
            go("done", now)
        else:
            needle(left / MINUTE_MS)
    elif state == "done" and flip and flipped:
        go("break", now)
    elif state == "break":
        left = time.ticks_diff(end_time, now)
        if left <= 0 or (flip and not flipped):
            if count % 4 == 0:
                count = 0
            go("armed", now)
        else:
            needle(left / MINUTE_MS)


# Setup
i2c = I2C(0, sda=Pin(21), scl=Pin(22), freq=400000)
i2c2 = I2C(1, sda=Pin(33), scl=Pin(32), freq=400000)
sensor = veml6040.VEML6040(i2c)
sensor.set_integration_time(veml6040.IT_160MS)
i2c2.writeto_mem(0x19, 0x20, b"\x57")
i2c2.writeto_mem(0x19, 0x23, b"\x88")

dial = PWM(Pin(4), freq=50)
buzzer = PWM(Pin(23), freq=1000, duty_u16=0)
lights = neopixel.NeoPixel(Pin(15), 2)
go("armed", time.ticks_ms())

# While Loop
while True:
    loop(time.ticks_ms())
    lights.write()
    time.sleep_ms(20)