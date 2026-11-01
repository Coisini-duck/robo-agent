---
name: ros2-development
description: "Use when installing, building, or verifying ROS 2."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, windows]
metadata:
  hermes:
    tags: [ROS2, robotics, WSL, colcon, embedded, micro-ros, verification]
    related_skills: [windows-desktop-app-ops, headless-browser-verification]
triggers:
  - install ROS 2
  - 装 ROS
  - ros2 not found
  - colcon build fails
  - NO_PUBKEY ROS
  - ROS 2 Jazzy
  - verify a ROS node
  - ros2 launch won't run
  - micro-ROS / STM32
  - 具身智能 / 机械臂 URDF
---

# ROS 2 Development

Installing ROS 2, building a workspace, and — the part that actually matters —
**proving the nodes run**. This skill exists because the expensive failure in
this class is treating a green build (or a passing syntax check) as a working
system.

## When to use

- Installing ROS 2, especially on WSL from a China network
- `colcon build` / `source install/setup.bash` problems
- Verifying a node, launch file, URDF, or topic stream really works
- micro-ROS (MCU ↔ ROS 2 graph) work

## 0. Version pairing is not a preference, it is a lock

A ROS 2 distro is built against **one** Ubuntu release. Ubuntu 24.04 →
**Jazzy** (EOL 2029-05). Read the codename, never assume it:

```bash
. /etc/os-release && echo "$VERSION_ID $UBUNTU_CODENAME"   # 24.04 noble
```

If it isn't what the apt repo line assumes, **abort**. Never "fix" a
distro/codename mismatch by editing the repo line to a guess.

## 1. Install — two pitfalls that both look like something else

Run `scripts/install_ros2_jazzy.sh` rather than retyping the block. From
Windows/WSL, copy it out of the CRLF world first:

```bash
wsl -d <distro> -- bash -lc "tr -d '\r' < /mnt/c/.../install_ros2_jazzy.sh > /root/i.sh && bash /root/i.sh"
```

| Symptom | Real cause | Fix |
|---|---|---|
| `gpg: keyserver receive failed: Server indicated a failure` | **HKP port 11371 is blocked.** The keyserver's *web page* returning HTTP 200 proves nothing — that's port 443. | Fetch the key over **HTTPS(443)**: `https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x<40-hex-fingerprint>` → `gpg --dearmor` |
| `NO_PUBKEY <id>` **even though** `gpg --list-keys` shows that exact fingerprint in your keyring | `gpg --dearmor` writes the keyring **`-rw-------` root-only**, and **apt verifies signatures as the unprivileged `_apt` user**, which then cannot read the file | `sudo chmod 0644 /usr/share/keyrings/<name>.gpg` |

That second one is the trap worth memorising: the evidence ("the key IS in the
keyring") actively contradicts the error message, so it reads as an apt bug.
It is a file-permission bug. Sanity check after either fix:

```bash
apt-cache policy ros-jazzy-desktop    # MUST print a Candidate:
```

Never route around a signature failure with `trusted=yes` / `--force`. Fix the
keyring. Detail and verified transcript: `references/wsl-ubuntu2404-cn-install.md`.

## 2. Build loop

```bash
mkdir -p ~/ros2_ws/src && cp -r <packages>/* ~/ros2_ws/src/
cd ~/ros2_ws && colcon build && source install/setup.bash
ros2 pkg list | grep <pkg>        # registered?
ros2 pkg executables <pkg>        # entry points exist?
ls $ROS_WS/install/<pkg>/share/<pkg>/launch/
```

Acceptable build evidence = per-package `Finished <<<` lines + a
`Summary: N packages finished` line + exit 0. Nothing less.

`ros2 --version` is **not a valid flag** on Jazzy (it prints argparse usage).
Use `printenv ROS_DISTRO` or `ls /opt/ros/`.

## 3. Verification — a build is not a run

**Syntax/static checks prove nothing about behaviour.** `ast.parse`, XML
well-formedness and `check_urdf` all pass on code that loops forever. Launch it
and read the log.

```bash
timeout -k 5 30 ros2 launch <pkg> <file>.launch.py > /tmp/run.log 2>&1 &
sleep 8
ros2 node list
ros2 topic list
ros2 topic hz <topic>            # configured rate != measured rate
ros2 topic echo <topic> --once
wait; tail -40 /tmp/run.log
```

- **`ros2 node list` showing `/rviz2` is not evidence that RViz shows anything.**
  A launch that starts `rviz2` with **no `-d` config** opens the default layout:
  `Fixed Frame: map`, no `RobotModel` display. If the URDF root link is
  `base_link`, RViz reports `Global Status: Error — Fixed Frame [map] does not
  exist` and renders an empty grid, while every node and topic looks healthy.
  Fix: ship an `.rviz` config in the package (Fixed Frame = URDF root link,
  RobotModel reading `/robot_description` with `Transient Local` durability) and
  pass it as `arguments=['-d', os.path.join(pkg_share, 'rviz', 'x.rviz')]`;
  for `ament_python`, `rviz/*` must be in `setup.py` `data_files`. Acceptable
  evidence is a screenshot showing **`Global Status: Ok` + the model**, not a
  node list.
- Prove a GUI launch with a **window-targeted** capture: `computer_use`
  `list_windows` (assert the window title/path exists) then
  `capture(pid=…, window_id=…)`. A full-screen grab can show only the agent's own
  foreground window while the demo window sits behind it — that false negative
  reads exactly like "the launch opened nothing".
- **Bound every launch with `timeout`** so nothing lingers past the test.
- `ros2 topic hz` is the highest-value single check: it turns "I set 10 Hz" into
  a measured number (worked case: configured 10 Hz → measured **9.998 Hz**).
  That gap is exactly the kind of concrete detail worth reporting and worth
  quoting back in an interview.
- Clean up by **listing exact PIDs, then killing those PIDs**. Never
  `pkill -f ros2` / `Stop-Process -Name python` — these are shared machines and
  broad name matches have killed unrelated work.
- **Send SIGINT before SIGTERM.** `kill -INT <pid>`, wait 1 s, then `-TERM` only
  for survivors. A node killed straight with SIGTERM dumps a multi-line
  `rclpy.executors.ExternalShutdownException` traceback into the saved log, which
  reads like a crash; on SIGINT the same node ends on its normal INFO lines, so a
  passing test stops looking broken to whoever reads the log next.
- Killing only the wrapper (`timeout`, `ros2 run`, `ros2 launch`) leaves its node
  children alive: collect `pgrep -P <wid>` and kill that exact list, then re-check
  that the process/topic is actually gone before reporting cleanup.
- **To assert a watchdog/hold path, kill the upstream — do not merely start the
  downstream node alone.** A consumer that has never received a message never
  reaches its timeout branch, so "start node → measure rate" silently reports the
  watchdog as untested (seen: watchdog log count 0 while the code was correct).
  Working sequence: launch producer + consumer, measure rates, SIGINT **only the
  producer**, wait longer than the timeout, then re-measure the consumer's output
  rate (must stay at the control rate) **and** grep the log for the watchdog line.
- **一个断言只有在“可复现的输入 + 正确的观察窗口”上才能用。** 两个真实假失败：
  （1）看门狗断言整份日志搜「看门狗触发」，但 bridge 启动即计时、模型冷启动 ~11 s
  没 chunk —— 这段触发是**正确行为**，被当成了缺陷。改为只查稳定阶段新增行。
  （2）跟踪误差在 0.005–0.16 之间随机跳：`predict_action_chunk` 内部 `torch.randn`
  采样流匹配噪声，每次动作不同。推理前 `torch.manual_seed(1234)` 才能当断言。
  另： `ros2 topic echo --once` 偶尔会在前面插 `A message was lost!!!` / `total count: 1`，
  裸正则会把那些 `1` 解成关节角（曾因此把空数据判成 PASS）—— 只取第一个 `[...]` 内的数值，
  条数不足直接 FAIL。
- **Gazebo 里“碰不住”几乎总是接口问题，不是模型问题。** 位置命令接口是运动学写入（实测命令 1.2 rad → 实际 **1.2000**，有柱/无柱完全一致），接触只有走动力学路径才存在：`joint_trajectory_controller` + PID（推荐先试，接触表现为跟踪误差突增）或 effort 接口。实验设计、初值/重力/零重力副本、`contacts` 话题与 FK 诊断见 `references/gazebo-sim-ros2-control.md` §7。
- **按参数生成不同 URDF 时：**`robot_description` 在 launch 解析阶段就生成，用不了 `LaunchConfiguration`，改走环境变量（`VLA_CONTROL_MODE=effort ros2 launch ...`）；xacro 表达式里的 `$(arg ...)` 必须加引号 —— `${'$(arg mode)' == 'effort'}`，否则报 `name 'position' is not defined`。
- **`gz model --list` 是确认“模型到底在不在世界里”的最快手段**：“碰不到”不能归咎于模型未加载。
- **别用订阅端计数断言生产者速率。** `ros2 topic hz` 和 `topic echo | grep -c` 会因 QoS 深度 10、
  管道跟不上而丢消息：同一轮里 `topic hz` 报 0.374 Hz，而节点日志写的是 `device=cuda:0`、
  每次推理 0.231–0.306 s（正常）。**数字要从生产者自己那里拿**：节点日志里的
  `chunk #N | X s` 排序取中位数，才是可断言的指标；topic 计数只当参考信息打印。
- **`pgrep -f 'a|b'` 会匹配到执行它的 shell 自己。** 清理断言里常见这种假失败：
  `pgrep -f 'smolvla_policy.py|ros2_control_node'` 的调用者命令行里就含这两个字符串，
  于是“残留计数”永远 ≥1（或 ⩾2）。用括号技巧：`pgrep -f 'smolvla_policy[.]py|ros2_control[_]node'`。
  另：带 TensorRT 会话的进程拆卸慢（kill 后秒级仍在），残留检查要**轮询最多 15 s** 而不是看一眼。
- **Poll for readiness; a fixed `sleep N` is both too slow and intermittently wrong.**
  Spawners and `controller_manager` activate when they activate: loop the state query
  (`ros2 service call /controller_manager/list_controllers controller_manager_msgs/srv/ListControllers`)
  for up to ~20 s and break on the expected state. A fixed 14 s check reported
  "controllers not active" on a run where the second controller came up at ~16 s — and
  the same script passed when run standalone, which reads like flakiness rather than a
  race.
- **Assert payload shape, not only rate.** A stream can sit at exactly the right
  frequency while carrying the wrong width. A 2-value command into a 6-interface
  controller makes `controller_manager` log `command size (2) does not match number of
  interfaces (6)` and **deactivate the controller**; from then on `/joint_states` stays
  zero and the tracking error equals the clamp value, so downstream checks "pass" for
  the wrong reason. Pin the width in the assertion (message field, or count the echoed
  entries) whenever a width is contractual.
- **Sample N messages and reduce with awk for numeric assertions.** This turns "it
  follows" into a measured number without writing an rclpy harness:
  `for i in $(seq 6); do timeout 3 ros2 topic echo <topic> --once --field <field>; done |
  grep -oE '-?[0-9]+\.[0-9]+' | awk '{v=$1<0?-$1:$1; if(v>m)m=v; s+=v; n++} END{printf "%.4f %.4f", s/n, m}'`
  gives mean and peak for a threshold. **Never `grep -c` the output of a
  `ros2 service call`**: the whole response is one line, so it counts lines (always 1)
  instead of objects — use `grep -o '<pattern>' | wc -l`.
- `scripts/verify_ros2_workspace.sh` runs the build + registration + a
  bounded-run recipe + PID-safe cleanup.

Worked example with real logs, including the bug only running exposed:
`references/ros2-first-run-case.md`.

## 4. Bugs this class keeps producing

- **`ros2 run` 报 “No executable found” / launch 报 “libexec directory does not exist”：`ament_python` 包缺 `setup.cfg`。**
  没有它，setuptools 把 console_scripts 装到 `install/<pkg>/bin/`，而 ROS 2 只查 `install/<pkg>/lib/<pkg>/`。
  构建是绿的，`ros2 pkg executables <pkg>` 却是空的。最小修法（每包一份，两行）：
  ```
  [develop]
  script_dir=$base/lib/<pkg>
  [install]
  install_scripts=$base/lib/<pkg>
  ```
  加完必须 `rm -rf build/<pkg> install/<pkg>` 再 build——旧的 install 日志会让 colcon 复用错布局。

- **A state machine that never terminates.** A counter that only increments
  makes its own guard true forever: `self.leg += 1; if self.leg >= 4:
  self.finish()` fires `finish()` on *every* subsequent tick. `finish()` that
  only logs does not stop the timer. Fix with a `done` flag checked at the top
  of the callback, or keep the timer handle and `timer.cancel()`.
- **Naming that over-claims.** A package described as a "differential-drive
  base" that actually publishes to `/turtle1/cmd_vel` is a **turtlesim demo**.
  The first interview question ("what chassis? wheelbase? URDF?") collapses it.
  Describe simulations as simulations.
- **`.msg` files in an `ament_python` package do nothing.** Custom interfaces
  require an `ament_cmake` package with `rosidl_generate_interfaces`.
- **`float64[][]` does not exist in `.msg`.** rosidl has no nested arrays, so a
  chunk of waypoints/actions must be one flat `float64[] positions` plus
  `int32 n_steps` / `int32 dof` (and `float64 dt`), sliced as
  `positions[i*dof:(i+1)*dof]` on the receiver. Validate
  `len(positions) == n_steps * dof` on arrival and drop the message otherwise —
  a mis-sized chunk does not raise in slicing code, it silently yields short or
  empty frames.
- **QoS mismatch silently drops data** — a `reliable` publisher with a
  `best_effort` subscriber receives nothing, with **no error**. Verify with
  `ros2 topic hz`, never by assumption.
- **A README's expected output is not evidence.** Verify the printed value
  yourself; in the worked case the documented error figure did not match
  reality at all.

## 5. micro-ROS (MCU → ROS 2 graph)

The strongest differentiator when the user already has firmware experience: an
STM32 publishes/subscribes into the ROS 2 graph through a micro-ROS **Agent**
over serial/UDP. Notes:

- `ros-jazzy-micro-ros-agent` is **not** in apt; build it from source or use the
  official Docker image. Budget real time for this step.
- `ros-jazzy-micro-ros-msgs` *is* packaged, which is why the missing agent is
  easy to miss until it fails.
- Highest-value framing: attach micro-ROS to a **real control task** already
  underway (e.g. an ADRC loop on the MCU publishing its measured variable) so
  the outcome is a project rather than a connectivity demo.

## 6. Developing on WSL

**The workspace path is a build dependency, not a preference.**
`rosidl_generate_interfaces` splits on non-ASCII path components, so a workspace
sitting in a Chinese-named folder fails with an error that names a *truncated*
path — which reads like a missing file, not an encoding problem:

```
CMake Error at .../rosidl_cmake/cmake/rosidl_generate_interfaces.cmake:234 (list):
  list index: 1 out of range (-1, 0)
CMake Error at .../rosidl_generator_type_description_...:68 (message):
  Target dependency '/mnt/c/.../workspace/ROS2' does not exist
```

→ Build on WSL's own ext4 at a **pure-ASCII path** (`~/ros2_ws`, `/root/ros2_ws`).
A Windows-side tree for editing is fine: `tar --exclude=build --exclude=install
--exclude=log` the sources over and build there. Measured on the same tree:
`/mnt/c/.../ROS2项目` → 1 of 4 packages failed; `/root/ros2_ws` → **4/4 finished in
13 s**. `LANG=C.UTF-8` does not save you — the path is the problem, not the locale.
`/mnt/c` is also ~10× slower than ext4 for the build loop, so this rule pays
twice.

- **Driving WSL from the Windows-side shell (MSYS/git-bash): `$VAR` and `$(...)`
  inside a `wsl.exe -- bash -c "..."` one-liner get eaten before WSL sees them.**
  A `for` loop collapses to an empty variable and `command -v` silently reports
  every tool as missing. Write the probe as an ASCII `.sh` in scratch and pass
  paths as **argv**:
  `wsl.exe -d <distro> -u root -- bash /mnt/c/.../probe.sh "/mnt/c/.../<项目>"`,
  reading `$1` inside the script. Same reason the install script is shipped as a
  file rather than inlined.
- `bash script.sh` is a **non-login** shell: `.bashrc` is not read, so ROS is not
  sourced and `ros2` "does not exist" even though `/opt/ros/<distro>` is installed.
  Source `/opt/ros/<distro>/setup.bash` at the top of every probe script, or use
  `bash -lc`.
- **An ML venv can still `import rclpy` — but only with the ROS env sourced.**
  `python3 -m venv --system-site-packages` makes `/usr/lib/python3/dist-packages`
  visible, yet `rclpy` itself lives under
  `/opt/ros/<distro>/lib/python3.12/site-packages`, which only joins `PYTHONPATH`
  after `. /opt/ros/<distro>/setup.bash`. Symptom: `ModuleNotFoundError: rclpy`
  inside the venv while `ros2` works two lines earlier. Source ROS **before**
  invoking the venv interpreter, and do not `pip install rclpy` — the distro's
  apt build is the one that matches the installed middleware.
- **Never install a Linux NVIDIA driver inside WSL.** `nvidia-smi` working in the
  distro already proves the Windows driver is passthrough-ing the GPU; adding a
  distro driver overwrites `/usr/lib/wsl/lib` and breaks it. CUDA itself is only
  needed for `nvcc` work — PyTorch wheels and cuDNN do not require it.
- WSLg covers turtlesim / rviz2 / `joint_state_publisher_gui`; check with
  `[ -d /mnt/wslg ]` and `echo $DISPLAY`.
- Gazebo's GL path may fall back to software rendering on WSL: prefer
  **headless Gazebo + rviz2**, or `LIBGL_ALWAYS_SOFTWARE=1`. Don't burn a
  session fighting graphics — the lesson is the data flow.
- Write install/verify `.sh` from Windows with a `tr -d '\r'` pass; a CRLF
  script fails at the shebang or mid-line with confusing errors.
- **WSL 的墙上时钟会跳，别用 `time.time()` 量耗时。** 一次基准测试里同一段代码算出
  **−597 ms**（负数），原因是运行期间时钟回跳了约 0.8 s；GPU 推理、engine 构建这类
  几十秒到几分钟的测量都会被它污染。一律用 `time.perf_counter()`（单调时钟），
  报数时把“首次/构建”和“稳态”分开列。
- Don't use `set -u` in a script that sources `/opt/ros/*/setup.bash`; the ROS
  setup scripts reference unset variables and abort.
- **Appending the overlay to `.bashrc` is not enough for automation.** Ubuntu's
  `.bashrc` early-returns on non-interactive shells, so `bash -lc` never reaches
  your appended lines; and if a `.bash_profile` exists it **shadows `.profile`**
  (which is what normally sources `.bashrc`). Symptom: `ROS_DISTRO` is set but
  `ros2 pkg list` shows none of your packages, and `command -v rw` is empty.
  Fix: make `.bash_profile` pull in both —
  `[ -f ~/.bashrc ] && . ~/.bashrc` then `[ -f ~/.profile ] && . ~/.profile` —
  and ship the build as a **real script** (`/usr/local/bin/rw`) rather than a
  shell function, because a function never exists in a non-interactive shell.
  Keep the function too if you want `rw` to re-source the overlay after a build;
  a script cannot modify its parent shell.

## Reporting style for this user

Chinese, terse, **table-first and evidence-first**: every claim carries a
measured number, a byte count, or a pasted log line. Keep "compiled", "ran" and
"verified" strictly separate — never let one imply the next — and say plainly
what was **not** done. When a folder is re-homed, **move (archive), don't
delete**, and state that it's reversible.

- **永远不要根据对话长度推断当前时间**（不说“已经凌晨 1:30 了，建议明天做”这种话）。
  一次长会话里凭感觉报“01:30”，实际是隔天早上 08:33 —— 用户当场纠正。
  要谈时间、要建议“该不该开工”，先 `date`，拿实测的钟点说话。
- **用户说“记一下”时，记事实，不要升级成默认约定。** “把 VLA 的东西整合到一个文件夹”
  是位置事实，不等于“以后新产出都放这里”——后者是我自己加的。记完回一句
  “我只记了位置，没把它当规则”，并让其不相关的事依旧走原路径。

## Files

- `scripts/install_ros2_jazzy.sh` — Ubuntu 24.04 install with the two fixes
  baked in (HTTPS key fetch + `chmod 0644`), Tsinghua mirror, codename guard,
  verification, shell auto-source. Verified 2026-10-12.
- `scripts/verify_ros2_workspace.sh` — stage packages → `colcon build` →
  confirm registration → bounded-run recipe → PID-safe cleanup.
- `references/wsl-ubuntu2404-cn-install.md` — the two pitfalls with verbatim
  error text, mirror-reachability measurements, and the verified package
  version.
- `references/action-chunk-bridge.md` — low-rate model output → high-rate
  controller: interpolation / clamp / rate-limit / watchdog / e-stop design,
  node interface, and the assertions that gate it in `verify.sh`.
- `references/vla-bridge-and-smolvla.md` — action chunk → 100 Hz 桥接 + 本地 SmolVLA 推理：五条坑
  （预处理链/bf16 vs fp32/图像布局/HF Xet 401/镜像限流）、`chunk_timeout` 必须大于 chunk 时长的铁则、实测数字。
- `references/onnx-export-smolvla.md` — SmolVLA 导 ONNX：必须 `dynamo=True`（trace 路线在 transformers 5.x 必崩）、
  noise 提成图输入、ORT CUDA EP 需手动补 `LD_LIBRARY_PATH`；ORT 211 ms vs torch 250–390 ms 实测表。
- `references/ros2-first-run-case.md` — three small packages taken from
  "never executed" to "built and ran", with the real logs, the measured topic
  rate, the `check_urdf` tree, and the infinite-loop bug.
- `references/gazebo-sim-ros2-control.md` — Gazebo Sim 8 + `gz_ros2_control` 接入：
  URDF 三件套与圆柱惯性公式、`use_sim` 参数切换硬件插件、headless launch 骨架、
  以及「指令 2.0 → 实际 1.5000」这条**唯一能证明有物理**的断言。
