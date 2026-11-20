r"""The view smoothing of NDC_Basic (README 4.4, D117) as plain Python: the Blueprint function SmoothView does the
same arithmetic in the same order, so this file is the reference to check it against and to try other numbers.

    python Tools/view_smoothing.py        prints how the defaults treat a jump, a stop and a steady walk

Each frame NDC_Basic computes the tracked head from the Live Link frame (cm, tracking space) and passes it
through SmoothView(Target, DeltaTime, Current); Rig goes where it returns.

1. Jumps. What one frame brings beyond MaxSpeed x DeltaTime is not head movement (the tracker catching up
   after standing, a wrong measurement, another person becoming the main one, tracking found again). That
   part goes into an offset, so the corrected target has no step; the offset then shrinks to zero within
   about 3 x JumpTime, never faster than MaxSpeed: the view glides there instead of jumping.
2. Speed of the corrected target: a slow estimate (over 1.2 x SmoothTime) and a quick one (over 0.03 s). The
   quick one only limits the slow one, by the square of their ratio: when the head slows down, the view does
   not run past where it stops.
3. The view follows the corrected target moved ahead by speed x (SmoothTime + LeadTime), critically damped: no
   overshoot of its own. It would lag SmoothTime behind a steadily moving head; the move ahead makes that up.

Settings (Blueprint variables of NDC_Basic, category View Smoothing; nDisplay nodes also take them from the
command line, README 4.4): SmoothTime 0.10 s, LeadTime 0.02 s, MaxSpeed 300 cm/s, JumpTime 0.08 s.
"""
import math

DEFAULTS = dict(smooth_time=0.10, lead_time=0.02, max_speed=300.0, jump_time=0.08)


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _mul(a, s):
    return [x * s for x in a]


def _len(a):
    return math.sqrt(sum(x * x for x in a))


class ViewFilter:
    def __init__(self, **settings):
        values = dict(DEFAULTS)
        values.update(settings)
        self.smooth_time, self.lead_time = values["smooth_time"], values["lead_time"]
        self.max_speed, self.jump_time = values["max_speed"], values["jump_time"]
        self.valid = False

    def __call__(self, target, dt, current=None):
        """Where Rig goes for the tracked head `target` after a frame of dt seconds. `current`: where Rig is,
        used at the first call only (the view glides from there)."""
        target = [float(x) for x in target]
        if not self.valid:
            start = list(target) if current is None else [float(x) for x in current]
            self.valid = True
            self.last_target, self.last_corrected, self.pos = list(start), list(start), list(start)
            self.offset, self.vel_slow, self.vel_fast, self.vel = [0.0] * 3, [0.0] * 3, [0.0] * 3, [0.0] * 3
        dt = min(max(dt, 0.001), 0.1)
        smooth = min(max(self.smooth_time, 0.01), 1.0)
        max_step = self.max_speed * dt
        # 1. jumps
        step = _sub(target, self.last_target)
        self.last_target = list(target)
        length = _len(step)
        if length > max_step:
            self.offset = _sub(self.offset, _mul(step, 1.0 - max_step / length))
        length = _len(self.offset)
        if length > 0.000001:
            shrink = min(length * (1.0 - math.exp(-dt / max(self.jump_time, 0.01))), max_step)
            self.offset = _mul(self.offset, 1.0 - shrink / length)
        corrected = _add(target, self.offset)
        # 2. speed
        raw = _mul(_sub(corrected, self.last_corrected), 1.0 / dt)
        self.last_corrected = list(corrected)
        self.vel_slow = _add(self.vel_slow, _mul(_sub(raw, self.vel_slow), 1.0 - math.exp(-dt / (smooth * 1.2))))
        self.vel_fast = _add(self.vel_fast, _mul(_sub(raw, self.vel_fast), 1.0 - math.exp(-dt / 0.03)))
        ratio = min(1.0, _len(self.vel_fast) / max(_len(self.vel_slow), 0.000001))
        # 3. follow
        goal = _add(corrected, _mul(self.vel_slow, (ratio * ratio) * (smooth + self.lead_time)))
        w = 2.0 / smooth
        d = _sub(self.pos, goal)
        c = _add(self.vel, _mul(d, w))
        e = math.exp(-(w * dt))
        self.pos = _add(goal, _mul(_add(d, _mul(c, dt)), e))
        self.vel = _mul(_sub(self.vel, _mul(c, w * dt)), e)
        return list(self.pos)


def _demo():
    fps = 60
    view = ViewFilter()
    head = [100.0, 0.0, 160.0]
    view(head, 1 / fps)
    # a jump of 100 cm to the side
    head[1] = 100.0
    largest, frames, seen = 0.0, 0, head[1] - 100.0
    while True:
        new = view(head, 1 / fps)[1]
        largest, seen, frames = max(largest, new - seen), new, frames + 1
        if abs(new - head[1]) < 1.0 and frames > 3:
            break
    print(f"jump of 100 cm: the view arrives after {frames / fps:.2f} s, moving at most {largest * fps:.0f} cm/s "
          f"({largest:.1f} cm in a frame at {fps} fps; without smoothing 100 cm in one frame)")
    # a steady walk at 100 cm/s for 3 s, then a stop within 0.3 s
    view = ViewFilter()
    t, x, ahead, past = 0.0, 0.0, [], 0.0
    view([x, 0.0, 160.0], 1 / fps)
    while t < 5.0:
        t += 1 / fps
        speed = 100.0 if t < 3.0 else max(0.0, 100.0 * (1 - (t - 3.0) / 0.3))
        x += speed / fps
        out = view([x, 0.0, 160.0], 1 / fps)[0]
        if 2.5 < t < 3.0:
            ahead.append(out - x)
        if t > 3.3:
            past = max(past, out - x)
    print(f"walking steadily at 100 cm/s: the view is {sum(ahead) / len(ahead):.2f} cm ahead of the tracked head "
          f"(LeadTime plus half a frame); after a stop within 0.3 s it is at most {past:.2f} cm past it and comes back")


if __name__ == "__main__":
    _demo()
