# Worked case: three ROS 2 packages, from "never executed" to "built and ran"

2026-10-12. Three small `ament_python` packages (`square_driver`,
`sensor_publisher`, `arm_description`) that had been **AI-authored and never
run**. The only prior validation was static: `ast.parse` on the Python files,
XML well-formedness, and URDF structure. All of it passed.

**That is the whole point of this case: every static check passed on code that
contained a live logic bug.**

## Build — clean

```
Starting >>> arm_description
Starting >>> sensor_publisher
Starting >>> square_driver
Finished <<< sensor_publisher [2.14s]
Finished <<< square_driver    [2.14s]
Finished <<< arm_description  [2.21s]

Summary: 3 packages finished [2.44s]
>>> colcon exit = 0
```

All three registered with `ros2 pkg list`; launch files present under
`install/<pkg>/share/<pkg>/launch/`.

## `sensor_publisher` — fully headless, everything verified

Nodes `/sensor_publisher` + `/sensor_monitor`; topics `/sensor/temperature`
and `/sensor/voltage`.

```
$ ros2 topic hz /sensor/temperature
average rate: 9.998                      <-- configured 10 Hz
    min: 0.100s max: 0.101s std dev: 0.00025s window: 11
$ ros2 topic echo /sensor/temperature --once
data: 31.872100830078125
```

The threshold alarm genuinely fired on the scripted step change:

```
[INFO] 温度 原始 26.68 ｜ 滑窗均值 26.84 ｜ 电压 原始 12.00 ｜ ... ｜ 共 98 帧
[INFO] 温度 原始 34.32 ｜ 滑窗均值 34.54 ｜ 电压 原始 11.78 ｜ ... ｜ 共 118 帧
[WARN] ⚠️ 温度连续 20 帧超过 30.0 ℃（滑窗均值 34.54 ℃）—— 疑似负载升高
```

Two quotable facts from this: **configured ≠ measured rate** (10 → 9.998), and
the sliding-window + N-consecutive-frames alarm trade-off (noise suppression
vs lag).

> Prefer **headless packages as the first smoke test** whenever a workspace
> mixes GUI and non-GUI nodes — they verify the graph without involving WSLg,
> Gazebo, or rendering.

## `square_driver` — the bug that only running exposed

turtlesim opened fine (WSLg), the state machine ran, and then:

```
已走完第 1 条边
已走完第 2 条边
已走完第 3 条边
正方形完成 -> 回到起点误差 5.369 m (起点 5.54,5.54 终到 9.02,9.64)
正方形完成 -> 回到起点误差 3.242 m ...
正方形完成 -> 回到起点误差 0.875 m ...
已走完第 12 条边                       <-- it was supposed to stop at 4
```

### Root cause

```python
self.phase = 'forward'
self.leg += 1
if self.leg >= 4:
    self.finish()          # finish() only logs; it stops nothing
```

`self.leg` only ever increases, so from the 4th leg onward the guard
`self.leg >= 4` is **true on every tick** — `finish()` re-fires forever and the
timer keeps driving. The code even printed
`按 Ctrl+C 退出（turtlesim 仍在运行）`, i.e. the author knew it never stopped
but never wrote a termination condition.

### Fix

```python
def __init__(self):
    ...
    self.done = False

def tick(self):
    if self.done or self.pose is None:
        return
    ...

def finish(self):
    self.done = True                 # <-- the missing line
    self.pub.publish(Twist())
    ...
```

(Equivalent: keep the `create_timer` return value and call `timer.cancel()`.)

### Second-order finding

The README documented the run as producing
`✅ 正方形完成。回到起点误差 0.042 m`. **That is not what the code does.** The
observed values were 0.875–5.369 m because the error is recomputed mid-loop,
over and over. A README's "expected output" is a claim, not evidence.

## `arm_description` — structurally sound

```
$ check_urdf arm.urdf
robot name is: simple_arm
---------- Successfully Parsed XML ---------------
root Link: base_link has 1 child(ren)
    child(1):  link1
        child(1):  link2
            child(1):  link3
                child(1):  tool0
```

5 links / 4 joints, each link carrying `visual` + `collision` + `inertial`
(the missing-`inertial` mistake is absent here).

## Naming over-claim (worth checking in any portfolio)

`README.md` described package 01 as a **"differential-drive base driving a
square"**, but the code publishes to `/turtle1/cmd_vel` and subscribes to
`/turtle1/pose` from `turtlesim.msg`. It is a **turtlesim demo**, not a
chassis. Anyone asking "what chassis / wheelbase / URDF?" gets nothing. Either
rename it honestly or build a real differential-drive URDF.

Package 02's sensor signal is `random.gauss`, not real ADC data — fine for
demoing a filtering algorithm, but it must be described as simulated.

## Carry-forward rule

Before calling anything in this class "verified", you need, per package:

1. a build line with a nonzero `Finished <<<`,
2. a `ros2 pkg list` / `executables` hit,
3. **an actual bounded launch whose log you read**, and
4. a measured value (topic rate, echo payload, `check_urdf` tree).

Compiled ≠ ran ≠ verified. Say which one you have.
