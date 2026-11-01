# VLA 桥接层 + SmolVLA 本地推理（2026-10-27 实测跑通）

本机：WSL Ubuntu 24.04 + RTX 5060 Laptop 8 GB（sm_120）。目标是在**没有机器人、没有相机**的前提下，
把"VLA 出动作块"这条链路跑通并可回归验证。

## 架构

```
smolvla_policy.py  --/vla/action_chunk 2 Hz-->  vla_bridge  --/joint_targets 100 Hz-->  控制器/仿真
   (venv + torch)                                  (colcon 包, 纯 rclpy)
```

- 消息：`sensor_interfaces/msg/ActionChunk`（`dof / n_steps / dt / float64[] positions` 扁平化——rosidl 不支持嵌套数组）
- 桥的职责：插值 / 限幅 / 限速 / 看门狗 / 急停

## 铁则：`chunk_timeout` 必须大于一个 chunk 的时长

SmolVLA 一次出 **50 步 × 33.3 ms = 1.67 s** 的轨迹。桥的默认 `chunk_timeout=0.3 s` 会在 0.3 s 后
就判定"上游挂了"开始保持，**白白丢掉 1.37 s 的有效预测**。实测对比：

| chunk_timeout | 现象 |
|---|---|
| 0.3 s（默认） | `holds` 一路涨到 1539，日志刷「看门狗触发」 |
| 2.0 s | `holds=0`，控制 100.007 Hz，chunk 2.036 Hz |

## lerobot / SmolVLA 的五个坑（按踩到的顺序）

1. **模型不能直接加载到裸 dict**：`predict_action_chunk` 需要 tokenized 语言 + 归一化后的状态，否则
   `KeyError: 'observation.language.tokens'`。必须走
   `make_smolvla_pre_post_processors(config, None)`（checkpoint 里 `policy_preprocessor.json` 那 6 步：
   rename → to_batch → new_line → tokenizer → device → normalizer）。
2. **dtype 不能一刀切**：视觉编码器权重是 **bf16**，`state_proj` 是 **fp32**。
   图像 `(b,c,h,w)` bf16、状态 `(1, dof)` fp32，否则报
   `mat1 and mat2 must have the same dtype, but got BFloat16 and Float`。
3. **图像布局要自己改**：预处理链不动图像，传给模型前必须 `HWC→CHW` 再 `unsqueeze(0)`，否则
   `ValueError: (b,c,h,w) expected, but got torch.Size([256, 256, 3])`。
4. **镜像下载 401**：HF 新存储 Xet（`cas-server.xethub.hf.co`）对镜像返回 401 →
   `export HF_HUB_DISABLE_XET=1` 走普通 HTTPS。
5. **加载时会卡 90 s**：`hf-mirror` 对 `chat_template.jinja` 之类的 HEAD 请求限流，日志出现
   `Rate limited. Waiting 91.0s`。缓存齐了之后一律 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。

## 接 ros2_control：没机器人也能验控制链路（2026-10-27 跑通）

用 `mock_components/GenericSystem` 当硬件，**不需要 Gazebo、不需要真机**：

```
ros2 launch vla_control control.launch.py        # rsp + controller_manager + jsb + forward_position_controller
bridge --ros-args -p dof:=6 -p fixed_dof:=6 \
       -r /joint_targets:=/forward_position_controller/commands
```

需要 apt 装：`ros-jazzy-ros2-control`(4.48.1) + `ros-jazzy-ros2-controllers`(4.42.1)。
插件名：`mock_components/GenericSystem`（在 `hardware_interface` 包里，不在名叫 mock 的包）、
控制器 `forward_command_controller/ForwardCommandController`（`interface_name: position`）。

**几个真实的坑：**

1. **命令维度不匹配会"静默"搞死控制器**：`command size (2) does not match number of interfaces (6)`
   → controller_manager 直接 `Deactivating controllers ... as their update resulted in an error!`，
   之后 `/joint_states` 永远是 0，跟踪误差恒等于限幅值（看起来像“限幅正常、就是不跟随”）。
   修法：桥加 `fixed_dof` 参数补齐/截断到控制器接口数。
2. **计数与断言写法见 SKILL.md §3**（`grep -c` 数行不数个数、就绪要轮询、速率对了还要验宽度）。
   本节只保留 ros2_control 专属的坑。
3. xacro 里不要用字符串拼接生成 parent link（`link${idx-1 or 'base_link'}` → `linkbase_link`），
   把 parent 当宏参数传。

**实测（verify 第 8 节）**：控制器全 active；`/joint_states` 99.989 Hz；
限幅穿透（策略要 0.8 rad，执行器最大 **0.300 rad**）；**跟踪误差 ≤ 0.0223 rad**。

注意：`mock_components` **不做限幅**，它只镜像命令——所以这条验的是“桥的钳位落到了执行器”，
真硬件才会在驱动层再钳一次。

## 全栈：真模型 → 桥 → 控制器（2026-10-27 跑通）

```
smolvla_policy.py --chunk 2 Hz--> vla_bridge --100 Hz--> forward_position_controller --> mock 硬件
                                                            └── /joint_states --> /vla/tracking_error
```

实测（verify 第 9 节）：控制器 2 个 active；chunk **2.018 Hz**；`/joint_states` **99.996 Hz**；
执行器最大 **1.500 rad**（模型输出可达 1.6，被桥 `position_limit` 削平）；
**跟踪误差 均值 0.0047 / 峰值 0.0336 rad**。

关键点：SmolVLA 的 action 是**绝对值关节位置**（不是增量），所以可以直接当 position 命令喂控制器；
但必须 `fixed_dof:=6`（模型 6 维 = 控制器接口数），且 `position_limit` 要对齐 URDF 的 limit。

## 环境搭建（本机实测）

```bash
python3 -m venv --system-site-packages /root/venvs/vla      # 必须 --system-site-packages
/root/venvs/vla/bin/pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple
/root/venvs/vla/bin/pip install 'lerobot[smolvla]' huggingface_hub -i <tuna>
/root/venvs/vla/bin/pip install 'numpy>=2.0,<2.3' 'scipy>=1.15'   # 见下条
```

- **`rclpy` 只有在 source 过 ROS 后可见**：`source /opt/ros/jazzy/setup.bash` 再跑 venv 的 python，
  `--system-site-packages` 才有用（rclpy 在 `/opt/ros/.../site-packages`，靠 PYTHONPATH）。
- **numpy/scipy ABI**：venv 会看见系统的 scipy（按 numpy 1.x 编译），报
  `numpy.dtype size changed, expected 96 ... got 88`。在 venv 里装 numpy<2.3 + scipy>=1.15 覆盖它。
- venv 里 setuptools 会被升到 84，系统 `colcon-core` 要求 <80 —— **不影响**（colcon 用系统 python3），
  但如果哪天真怪，先想到这条。

## 实测数字（RTX 5060 Laptop 8 GB）

| 项 | 值 |
|---|---|
| 模型 | `lerobot/smolvla_base`（apache-2.0，底座 SmolVLM2-500M-Video-Instruct） |
| 权重 | 865 MB（含 model.safetensors 906,712,520 B） |
| 动作 | `action` shape [6]，`chunk_size=50`，`n_action_steps=50` |
| 观测 | `observation.state[6]` + `camera1/2/3 [3,256,256]`，`n_obs_steps=1` |
| 推理 | 首次 11.1 s（编译），热态 **0.25–0.39 s** → 2 Hz 稳 |
| 显存 | **0.90 GB** |
| 端到端 | chunk 1.98 Hz → 桥 99.99 Hz，`/joint_targets` 6 维 |

## Gazebo 里“有物理”不等于“能验碰撞”

接入 `gz_ros2_control` 后，URDF 的关节限位会生效（那是关节约束），但**接触/碰撞靠位置接口永远验不出来**：

实测：世界里 x=±0.35 各立一根 0.1×0.1×0.6 m 柱子，命令 `joint1=±0.9 rad`，
实际精确到 **±0.9000**（无柱对照组同样 0.9000）—— 柱子完全没起作用。

根因：`forward_position_controller` 对内走 `SetPosition`，**运动学写入**，不经过力学求解器，
所以接触不产生反力。

要做真碰撞验证，必须换动力学接口：

| 做法 | 需要改什么 |
|---|---|
| effort | URDF 加 `<command_interface name="effort"/>`，用 `effort_controllers/*` + 自写 PD，或 JTC 带 PID gains |
| velocity | 速度闭环，接触表现为跟不上 |
| JointTrajectoryController | 带 PID，接触 → 跟踪误差上升（最接近真机） |

铁则：**物理验证前先问“这个控制接口是运动学写入还是动力学驱动”**。
用运动学接口测碰撞，会得出“仿真没问题”的错误结论。

## 回归验证

`/root/ros2_ws/verify.sh` 第 7–9 节（缺模型时自动 SKIP）：SmolVLA chunk 1–3 Hz、桥 >90 Hz、6 维、
正常速率下**不许**出现看门狗、控制器全 active、限幅穿透、跟踪误差 ≤0.12 rad、全栈串起来跑、进程清理。
全套 **31 项 PASS**。
