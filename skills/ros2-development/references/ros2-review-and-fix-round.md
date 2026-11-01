# Review → fix round: what a ROS 2 package review keeps finding

2026-10-12, second pass over the same three packages as
`ros2-first-run-case.md`, after they had been built and run once. Thirteen
issues were found and fixed, each re-verified by running the code again.

Two lessons generalise beyond this workspace:

- **A green build, a passing `check_urdf`, and a passing syntax check all
  coexist with code that cannot work.** Every item below was invisible until
  something was executed and its output read.
- **"It runs" is not "it is correct."** The first pass established *runs*; this
  pass established *behaves*. Keep the two claims separate when reporting.

---

## 1. A declared dependency is not an installed dependency

`package.xml` already contained
`<depend>joint_state_publisher_gui</depend>`, yet:

```
$ ros2 launch arm_description display.launch.py
[ERROR] [launch]: Caught exception in launch:
"package 'joint_state_publisher_gui' not found, searching:
 ['/root/ros2_ws/install/square_driver', '.../sensor_publisher',
  '.../arm_description', '/opt/ros/jazzy']"
```

`colcon build` succeeded; nothing installs `<depend>` entries. The launch file
died at parse time, so **this package could not be started by anyone,
including its author.**

Fix:

```bash
sudo apt install -y ros-jazzy-joint-state-publisher-gui
# or, generally, for a whole workspace:
rosdep install --from-paths src -y --ignore-src -r
```

After the install: `/joint_state_publisher_gui`, `/robot_state_publisher` and
`/rviz2` all came up, `/tf` at 9.995 Hz, `/joint_states` carrying
`[joint1, joint2, joint3]`, rviz2 reporting `OpenGl version: 4.5 (GLSL 4.5)`
through WSLg, and no error lines in the launch log.

**Rule:** when a package has never been run, treat every `<depend>` as possibly
uninstalled. `rosdep install` belongs in setup, not in the aftermath.

---

## 2. Parameter callbacks observe the OLD value

This one was introduced *by the fix itself* and then caught by reading the log.

Symptom — set 28, the node reports 30; set 30, it reports 28:

```
参数更新: temperature_warn_c=28.0 | 生效中 窗口=10 阈值=30.0℃ 连续=3
参数更新: temperature_warn_c=30.0 | 生效中 窗口=10 阈值=28.0℃ 连续=3
```

Cause: `add_on_set_parameters_callback` runs **before** the value is committed.
`get_parameter()` inside the callback returns the previous value, so a node that
re-reads its parameters there runs exactly one setting behind — which looks
like a silently ignored `ros2 param set`.

Fix — apply from the incoming list, never by re-reading:

```python
def on_set_parameters(self, params):
    ov = {p.name: p.value for p in params}          # the NEW values
    def merged(n): return ov[n] if n in ov else self.get_parameter(n).value
    if float(merged('temperature_warn_c')) <= 0.0:
        return SetParametersResult(successful=False, reason='必须 > 0')
    self.apply_params(overrides=ov)
    return SetParametersResult(successful=True)

def apply_params(self, overrides=None):
    ov = overrides or {}
    def val(n): return ov[n] if n in ov else self.get_parameter(n).value
    self.warn = float(val('temperature_warn_c'))
    # ... and rebuild anything sized from a parameter, e.g. a deque(maxlen=window)
```

`merged()`/`val()` also make multi-parameter changes atomic: validating
`step_end_s` against a *stale* `step_start_s` is the same bug in another guise.

Verified after the fix:

```
参数更新: temperature_warn_c=20.0 | 生效中 窗口=10 阈值=20.0℃ 连续=3   ← new value
$ ros2 param set /sensor_monitor window_size 0
Setting parameter failed: window_size / consecutive_frames 必须 >= 1
$ ros2 param get /sensor_monitor window_size → Integer value is: 10   ← rejected, unchanged
```

And the new threshold took effect within **0.2 s** (alarm fired at
`...714.367` after the set at `...714.1`).

---

## 3. Capturing `ros2` CLI output to a file: set `PYTHONUNBUFFERED=1`

```
PYTHONUNBUFFERED=1 timeout 42 ros2 topic echo /sensor/alarm > /root/alarm.log 2>&1 &
```

Without it, Python block-buffers when stdout is not a tty, so the file stays
**empty for the entire run** and the natural conclusion is "the topic published
nothing." That false negative was reached twice in one session before the real
cause was found. Either set the env var, or read the log only after the writer
has been reaped.

With the env var, one run captured the full transition in order:

```
1:data: true
3:data: false
```

---

## 4. Cleaning up: match full paths, never the bare package name

The verification script was named `fix_verify_square_driver.sh`, and its
cleanup step was

```bash
ps -eo pid,args | grep -E "turtlesim_node|square_driver|pose_monitor"
```

The script's **own command line contains `square_driver`**, so it matched
itself, killed itself, and exited 15 with truncated output and processes left
behind. Match on paths that cannot appear in the caller:

```bash
PAT='/opt/ros/jazzy/lib/turtlesim/turtlesim_node|install/square_driver/lib/square_driver'
PIDS=$(ps -eo pid,args | grep -E "$PAT" | grep -v grep | awk '{print $1}')
for p in $PIDS; do echo "  kill $p <- $(ps -p $p -o args= | cut -c1-58)"; kill "$p"; done
```

Print each PID before killing it. This is the same rule as "never `pkill -f`"
— simply one step closer to home, where the collateral damage is your own run.

Note also that `ros2 launch` **does** reap its children on SIGTERM, so a
`timeout`-bounded launch usually leaves nothing behind; the leftovers here came
from killing processes individually.

---

## 5. Dead code: a state whose exit branch can never fire

`sensor_monitor` had an alarm-clear branch:

```python
elif self.over == 0 and self.alarmed:
    self.get_logger().info('温度已回落至阈值以下，告警解除')
    self.alarmed = False
```

A 30-second run produced **`告警解除` exactly 0 times.** The publisher's step
change only ever went *up* (lowest observed temperature 30.71 °C against a
30 °C threshold), so `self.over` never returned to 0 and the branch was
unreachable. The code looked correct, read correctly, and had never executed.

**Detection:** `grep -c <branch-message> <run.log>` over a run long enough to
exercise both directions. A count of 0 on a branch that should plausibly have
fired is a finding, not a pass.

**Fix:** make the stimulus two-directional — parameters `step_start_s` /
`step_end_s`, adding heat only inside the window:

```python
in_step = self.step_start <= elapsed < self.step_end
if in_step:
    temp += self.delta
```

Re-verified: 1 alarm, 1 clear, 9.8 s apart.

### Related: alarm latency hidden by where the check lives

The same node judged the threshold inside a **2-second report timer** rather
than the data callback, so `consecutive_frames = 3` (0.3 s of data) still
produced a **2.0 s** delay (step at frame 100 → first warning at frame 120).
Moving the judgement into the data callback changed the log from
`连续 20 帧超过` to `连续 3 帧超过` — the reported count now equals the
configured threshold, which is itself the evidence that the check moved.

**Generalisation:** a threshold check placed on a display/printing schedule
inherits that schedule's latency. Judge on data arrival; print on a timer.

---

## 6. Readings that cannot be aligned

`/sensor/temperature` and `/sensor/voltage` were both `std_msgs/Float32` — no
header, no stamp. Two separate `publish()` calls, and a subscriber with no way
to tell which two readings belong to the same instant. Any cross-quantity
computation (power = U·I) or multi-sensor fusion needs the stamp.

The package even shipped the correct message, unused and unbuildable:

```
msg/SensorReading.msg
  std_msgs/Header header   # 时间戳 + frame_id（多传感器对齐时必需）
```

Fix — a proper interface package:

```
04_sensor_interfaces/            # ament_cmake (NOT ament_python)
  package.xml                    # rosidl_default_generators, member_of_group
  CMakeLists.txt                 # rosidl_generate_interfaces(... DEPENDENCIES std_msgs)
  msg/SensorReading.msg
```

```cmake
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/SensorReading.msg"
  DEPENDENCIES std_msgs)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
```

Rules that follow:

- `.msg` files **must** live in an `ament_cmake` package; in an `ament_python`
  package they are dead files (see SKILL.md §4).
- `colcon build` orders the interface package before its consumers
  automatically once `<depend>sensor_interfaces</depend>` is declared.
- **Keep the two plain `Float32` topics as well.** `rqt_plot` can plot them
  with zero setup; the stamped message is for computation. Publishing both is
  the pragmatic choice, not redundancy.

Verified: `ros2 interface show sensor_interfaces/msg/SensorReading` resolves,
and `/sensor/reading` echoes `header.stamp`, `frame_id: sensor_link`,
`temperature_c`, `voltage_v`, `current_a`.

---

## 7. QoS: sensor streams are `best_effort` on **both** ends

```python
SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
```

RELIEABLE is for control commands; sensor streams should drop rather than
retransmit. The failure mode is the important part: a `best_effort` publisher
with a `reliable` subscriber delivers **nothing, and reports no error**. Set
the same profile on both sides and confirm with
`ros2 topic info <topic> -v | grep Reliability`.

---

## 8. URDF: things `check_urdf` passes and a simulator will not

`check_urdf` verifies the XML tree and the parent/child chain. It says nothing
about physics, and nothing about whether the numbers are right.

| Issue | Symptom / detection | Fix |
|---|---|---|
| **Inertia on the root link** | `[kdl_parser] The root link <x> has an inertia specified in the URDF, but KDL does not support a root link with an inertia.` (only printed at runtime — `check_urdf` is silent) | Drop `<inertial>` from the fixed root, or add an empty `base_footprint` link as the root and hang the real base under it. Verified: warning gone. |
| **Hand-guessed inertia tensors** | Compare the file against the formula; deviations up to **1.57×** high and **0.54×** low were found | Compute them. Cylinder along Z: `Ixx = Iyy = m(3r² + h²)/12`, `Izz = m·r²/2`. Box `a×b×c`: `Ixx = m(b²+c²)/12`, `Iyy = m(a²+c²)/12`, `Izz = m(a²+b²)/12` |
| **Base yaw joint as `revolute` with limits ±π** | Cannot rotate a full turn | Use `type="continuous"`. A continuous joint still requires `<limit effort=".." velocity=".."/>` — only the position bounds are omitted |
| **A link with `<visual>` only** | Passes `check_urdf`; fails in any physics engine | Add `<collision>` **and** `<inertial>` to every link. The end-effector/flange link is the one people forget |
| **`<origin>` mismatch between `visual`, `collision`, `inertial`** | Silent | They should agree unless the centre of mass genuinely differs from the geometric centre |

Verification recipe — cheap and decisive:

```bash
# 1. tree
check_urdf $WS/src/<pkg>/urdf/<model>.urdf

# 2. does the parser still complain? (catches the root-inertia class)
timeout 8 ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p robot_description:="$(cat <model>.urdf)" > /tmp/rsp.log 2>&1
grep -i 'warn\|error' /tmp/rsp.log || echo "clean"

# 3. does the full display stack come up?
timeout 40 ros2 launch <pkg> display.launch.py &
sleep 16; ros2 node list; ros2 topic hz /tf
```

Step 2 is the one to remember: **`robot_state_publisher` alone surfaces URDF
complaints that `check_urdf` does not report at all.**

Also worth knowing at this stage: `xacro` and `graphviz` (`dot`, for
`tf2_tools view_frames`) are separate packages — confirm with
`command -v xacro dot` before planning a lesson that depends on them.

---

## 9. Do not inline a complex script into `wsl.exe`

Passing a multi-line script as
`wsl.exe -d <distro> -- bash -lc '...'` mangles it: embedded double quotes and
`awk "{print \$1}"` were stripped, `$VAR` assignments arrived empty, and the
result was `cp: cannot stat '/01_square_driver'` plus a 180 s timeout.

Reliable pattern — write the script to an **ASCII-only** path on the Windows
side, then hand the file to WSL:

```bash
wsl.exe -d <distro> -- bash -lc \
  "tr -d '\r' < '/mnt/c/Users/<u>/AppData/Local/hermes/scripts/<name>.sh' > /root/<name>.sh && bash /root/<name>.sh"
```

Keep the script's own filename out of any string it greps for (see §4), and
avoid `set -u` when it sources `/opt/ros/*/setup.bash`.
