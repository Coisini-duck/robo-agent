# Gazebo Sim 8 + ros2_control（无界面也能验物理）

用途：给已有的 ros2_control 机械臂加第三种后端，让 **URDF 限位、碰撞、重力**真正生效。
`mock_components/GenericSystem` 只镜像命令（发 2.0 就回 2.0），证明不了机器人侧的任何约束 ——
所以“限幅生效”这类断言只有接了仿真或真机才有意义。

## 0. 依赖与验证

```bash
apt-get install -y ros-jazzy-ros-gz-sim ros-jazzy-gz-ros2-control
```

`gz` 可执行在 `/opt/ros/<distro>/opt/gz_tools_vendor/bin/gz`，**只有 source 之后才在 PATH 上**：

```bash
command -v gz                      # 未 source 的 shell 里查不到 → 会误判成“没装”
source /opt/ros/jazzy/setup.bash
gz sim --versions                  # 应打印 8.x
```

检查安装是否完整，用 `dpkg-query -W` 看这一组：`gz-tools-vendor`、`gz-sim-vendor`、`ros-gz-sim`、
`gz-ros2-control`、`ros-gz-bridge`。

## 1. URDF：每个 link 都要三件套

`<visual>` 只能给人看；缺 `<collision>` 不会碰任何东西，缺 `<inertial>` 会抖动或直接飞走。

实体圆柱的惯性张量：`Izz = ½·m·r²`，`Ixx = Iyy = m·(3r² + h²)/12`。

底座要**加宽加重**（例：r=0.10 m、h=0.05 m、m=5 kg），否则臂在重力下会连座一起倒。
关节加 `<dynamics damping="0.05"/>` 抑制数值抖动。

## 2. 硬件插件用 xacro 参数切换，保住原来的 mock 路径

```xml
<xacro:arg name="use_sim" default="false"/>
<ros2_control name="ArmSystem" type="system">
  <hardware>
    <xacro:if value="$(arg use_sim)"><plugin>gz_ros2_control/GazeboSimSystem</plugin></xacro:if>
    <xacro:unless value="$(arg use_sim)"><plugin>mock_components/GenericSystem</plugin></xacro:unless>
  </hardware>
  <!-- 接口定义两种模式保持一致 -->
</ros2_control>

<xacro:if value="$(arg use_sim)">
  <gazebo>
    <plugin filename="gz_ros2_control-system"
            name="gz_ros2_control::GazeboSimROS2ControlPlugin">
      <parameters>$(find <pkg>)/config/controllers.yaml</parameters>
    </plugin>
  </gazebo>
  <gazebo reference="base_link"><mu1>1.0</mu1><mu2>1.0</mu2></gazebo>
</xacro:if>
```

**`$(find <pkg>)` 要求先 source 工作空间的 install。** 没 source 时 xacro 抛
`PackageNotFoundError`，输出是个**空文件**，于是 `check_urdf` 报
`XML_ERROR_EMPTY_DOCUMENT` —— 看着像 XML 损坏，实际是包路径没解析。先 source 再判。

## 3. world.sdf 最小要素

- `<physics type="dartsim"><max_step_size>0.001</max_step_size>`；
- 插件：`gz-sim-physics-system`、`gz-sim-user-commands-system`（没它 `ros_gz_sim create` 无法生成模型）、
  `gz-sim-scene-broadcaster-system`；
- 地面 `static` 平面 + `mu=1.0` 摩擦；一个 `static` 障碍箱（供碰撞测试）；
- 校验：`gz sdf -k world.sdf` 必须输出 `Valid.`

## 4. launch：不要另起 `ros2_control_node`

gz 插件在**自己进程内**起 controller_manager，再起一个 `ros2_control_node` 会抢 `/controller_manager`。
launch 只需要：

1. `IncludeLaunchDescription(ros_gz_sim/gz_sim.launch.py)`，`gz_args='-r -s -v 2 <world>'`（headless，WSL 首选）；
   带界面就去掉 `-s`。两种模式各一个 include，用 `IfCondition`/`UnlessCondition` 挂；
2. `ros_gz_bridge parameter_bridge '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock'`；
3. `robot_state_publisher`（`use_sim_time=True`）；
4. `ros_gz_sim create -topic /robot_description -name <model>`；
5. 两个 `controller_manager spawner`（同样 `use_sim_time=True`）。

**`use_sim_time` 必须给 rsp 和 spawner**，否则控制器按墙钟跑，和仿真时钟打架，频率看着对、跟随会漂。

## 5. 断言：只有一条能证明“真有物理”

| 断言 | 实测（6 轴臂、100 Hz 控制） |
|---|---|
| 控制器 active | 2（jsb + forward_position_controller） |
| `/joint_states`（仿真时钟） | 99.998 Hz |
| 跟随误差（指令 0.3 rad） | 4.35e-11 rad |
| **URDF 限位：指令 2.0 rad → 实际** | **1.5000 rad** |

前三条只说明链路通（`forward_position_controller` 直接把关节设到目标时，误差会是 1e-11 量级）。
**限位那条才证明约束存在** —— mock 后端会把 2.0 原样回报，仿真后端才钳到 URDF 的 ±1.5。
写验收标准时把这条单列，别混在“跟随精度”里。

## 6. 清理

gz 派生多个子进程（server、physics、controller plugin）。用 `timeout` 包住整次 launch，
结束后复查 `pgrep -f 'gz sim|GazeboSimROS2ControlPlugin'` 为 0，再报“已清理”。

## 7. 接触 / 碰撞验证：位置接口测不出来，必须换动力学路径

### 7.1 核心事实（已实测，两世界对照）

`gz_ros2_control` 的 **position 命令接口是运动学写入**（直接 SetPosition），接触不产生任何反力。
证据：命令 joint1 = **1.2 rad**（该角度下末端 (x≈0.55, z≈0.41) 已深入柱子体积 x∈[0.20,0.50]、z∈[0,0.80]），
柱世界与空世界都精确到达 **1.2000**，两次可复现。

所以：**想用“被挡住”来证明碰撞，位置接口永远做不到**。要么换控制器，要么换命令接口。

### 7.2 两条动力学路线

| 路线 | 改什么 | 接触的表现 | 本机状态 |
|---|---|---|---|
| `joint_trajectory_controller` + PID | 只换控制器，不动硬件接口 | 跟踪误差突增 | **未验证**，推荐先试（最省事） |
| effort 接口 | URDF 加 `<command_interface name="effort"/>`，controllers.yaml 加 `effort_controllers/JointGroupEffortController`（`ros-jazzy-effort-controllers` 已打包），launch 里 **别同时起位置控制器** | 角度停在接触点、不再增长 | 接口可用，但本机仍未得出可信 A/B（见 7.3–7.5） |

### 7.3 接口共存的钉死效应

同一 URDF 同时声明 `position` 与 `effort` 时，gz_ros2_control **会一直保持 position 命令**（没收到指令就是 0）：
纯重力测试里 6 个关节 6 秒一丝不动，看着像“不稳定平衡”，其实是被钉住。
做动力学实验要用只声明 effort 的变体：

- xacro 加 `control_mode` 参数，`effort` 分支只写 `<command_interface name="effort"/>`；
- **`robot_description` 在 launch 解析时就生成，用不了 `LaunchConfiguration`**，改走环境变量：
  `VLA_CONTROL_MODE=effort ros2 launch <pkg> gz.launch.py`；
- xacro 表达式里的 `$(arg)` **必须加引号**：`${'$(arg mode)' == 'effort'}`；
  写成 `${$(arg mode) == 'effort'}` 会被当成变量名，报 `name 'position' is not defined`。
- 验证两模式：`xacro ... control_mode:=effort | grep -c 'command_interface name="effort"'` 应为 6，
  position 为 0；反向同理。

### 7.4 初值必须可控（否则 A/B 必假）

- **不加控制器直接施力矩**：等待启动的 30 s 里重力已经把臂甩到地面又弹回来，等指令到达时早不在初始姿态。
  实测序列 1.3837 → 0.6353 就是这样产生的（先砸地、再弹回）。
- **0 位往往是不稳定平衡点**：纯重力下关节停在 `0.000` 连续 6 秒，不代表“重力没生效”，而是正好在谷底。
- 正确做法：先由一个控制器把臂稳在已知姿态，再切动力学模式；或像 7.5 那样先消掉重力。

### 7.5 力矩量级与零重力副本

0 位重力力矩约 **2 N·m**（6 段 0.12 m 连杆、总长约 0.71 m 的臂），而实验用力矩只有 0.03–0.4 N·m：
同一个正力矩，柱世界往 **正** 转、空世界往 **负** 转 —— 主导运动的是重力加扰动，不是力矩。

做法：复制 world 并把 `<gravity>0 0 -9.81</gravity>` 改成 `0 0 0`（`vla_world_ng.sdf` / `vla_world_clear_ng.sdf`），
再用 0.05 N·m 慢速驱动；此时 0→1.5 rad 约 2.8 s，曲线平滑可读。
**零重力副本要写进源码包的 `worlds/`**，`--symlink-install` 只对已有文件建链，新建在 `install/` 下的文件会在重建时消失。

### 7.6 诊断手段（按性价比排）

1. **`gz model --list`** —— 一秒钟确认模型真在世界里（`ground_plane / obstacle_pillar_* / <arm>`）。
   “碰不到”不能归咎于模型未加载。
2. **正运动学算末端位置**：从 URDF 读 joint origin 与连杆长度，算出某角度下末端 (x, z)，
   再跟柱体包围盒比对 —— 比“停住了就是被挡住”可靠得多（实测 0.635 rad → (0.386, 0.583)，正处柱内）。
3. **`/world/<name>/contacts`**：只有 world 的 `<plugin>` 里加载了 `gz-sim-contact-system`
   **且该插件已安装**时才有消息。查证顺序 `gz topic -l | grep contact` → 看 world 的 plugin 列表 →
   `ls /usr/lib/*/gz-sim-*/plugins/`。**话题不存在 ≠ 没有碰撞**。
4. **采样要密**：effort 从 0 起 0.8 s 就到 1.4 rad，`ros2 topic echo --once` 每 0.8 s 一次会把停住点漏掉。
   用 100 Hz 订阅、10 Hz 打印的小脚本（`rclpy` + `spin_once(timeout_sec=0.01)`）连续记录。

### 7.7 结论的写法

没跑出可信结论时，把“已排除什么”写清楚，而不是含糊其辞：本例排除了
模型未加载（`gz model --list`）、接口打架（去掉 position 后结果不变）、重力干扰（零重力下同样穿过）。
剩下未验证的方向是物理引擎的碰撞参数，应当作下一步而不是已克服的障碍。
