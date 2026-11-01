# Action-chunk bridge: low-rate policy → high-rate controller

Applies whenever a learned policy (VLA, diffusion policy, remote planner) emits
an *action chunk* far slower than the controller wants commands — typically
model at 3–10 Hz, servo loop at 100–1000 Hz. Putting the model straight onto the
actuator topics is the mistake this layer prevents.

## Why the layer exists (say this in an interview, it is the whole point)

- Drivers/joints drop enablement if commands stop arriving, so the bridge must
  **keep publishing at the control rate** even when the model is dead or slow.
- The bridge must **not extrapolate** a stale chunk: extrapolating a policy
  output is how robots run away. Hold the last command and warn instead.
- Model output arrives in bursts and is not clock-aligned with the control loop,
  so frames must be **interpolated**, otherwise every chunk boundary is a step.

## Message schema (rosidl has no nested arrays)

```
std_msgs/Header header
int32 dof
int32 n_steps
float64 dt
float64[] positions      # n_steps * dof, flattened
```

Receiver: validate `len(positions) == n_steps * dof` and **drop** otherwise;
slice `positions[i*dof:(i+1)*dof]`. A short chunk yields empty frames silently.

## Nodes

| node | role | rate |
|---|---|---|
| policy (real model, or `fake_policy` stand-in) | emits chunk covering the next `n_steps*dt` seconds; advance an internal clock by `n_steps*dt` so consecutive chunks tile without gaps | `1/(n_steps*dt)` e.g. 10 Hz |
| bridge | consumes chunk, emits single-step command | `control_rate` e.g. 100 Hz |

Keep the producer swappable: the fake producer is what lets the link be verified
before any model download, and swapping in the real policy must touch only that
one node.

## Bridge rules (all four, in this order per tick)

1. **Cursor interpolation** — keep a float frame index, advance by
   `control_dt / chunk_dt`, lerp between `frames[i]` and `frames[i+1]`, clamp the
   cursor to the last frame. Reset the cursor to 0 when a new chunk lands.
2. **Position clamp** — `±position_limit` per joint.
3. **Rate limit** — at most `max_delta_per_tick` per joint per tick, applied to
   the *published* value, not the target, so a jump is spread over ticks.
4. **Watchdog** — if `now - last_chunk > chunk_timeout`, publish the last command
   unchanged, log once per outage (not per tick), and count holds.

Plus **e-stop**: `True` → publish zeros immediately and stay latched; only an
explicit `False` releases it. Zeroing on e-stop and holding on timeout are two
different behaviours — implement both, test them separately.

Parameters worth exposing: `control_rate`, `chunk_timeout` (≈3× chunk period),
`position_limit`, `max_delta_per_tick`, `dof` (used before the first chunk).

## Verification gate (each line is an assertion, not a vibe)

```
ros2 topic hz /vla/action_chunk      # producer rate        ~10 Hz
ros2 topic hz /joint_targets         # bridge rate          ~100 Hz
ratio = bridge_hz / chunk_hz         # must be 8–12
pub /estop {data: true}  → echo /joint_targets --once → every component |v| < 1e-9
pub /estop {data: false} → output resumes
SIGINT only the producer → sleep > chunk_timeout → ros2 topic hz /joint_targets
   must still be ≈ control_rate, AND the log must contain the watchdog line
```

Calibration values from a verified run (design 10 Hz / 100 Hz): chunk **9.998 Hz**,
control **99.995 Hz**, ratio **10.0**, after killing the producer control stayed
**100.015 Hz** with holds incrementing.

Two traps this gate exists to catch:

- **Starting the bridge alone proves nothing about the watchdog.** With no chunk
  ever received, the node sits in its "no data yet" branch; the timeout branch is
  never entered and the watchdog count stays 0 while the code is correct. Kill the
  producer *after* data has flowed.
- **Rate alone does not prove the chunk is used.** Also sample one `/joint_targets`
  message and confirm the values move and are plausibly in the chunk's range.

## Model-side reality check before wiring a real policy

Measure the card before choosing the model: a 7–7.5B VLA needs ~16 GB VRAM for
inference, so an 8 GB laptop GPU cannot host it; 450M-class policies (SmolVLA)
and 3–3.6B policies (pi0.5) are the realistic targets at 8 GB, and 3B policies
that target humanoids want 16 GB+. Treat the inference node as an ordinary
producer with a stubbed fallback so the bridge and its assertions stay testable
while the model is still downloading.
