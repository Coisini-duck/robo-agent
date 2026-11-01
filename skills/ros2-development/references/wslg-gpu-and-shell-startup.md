# WSLg GPU 直通 & shell 启动文件（2026-10-12 实测）

本机：Windows 11 Home 24H2 · Ryzen 9 8945HX · RTX 5060 Laptop 8151 MiB ·
WSL 2.7.11 · WSLg 1.0.73.2 · Mesa 25.2.8 · Ubuntu-24.04（root）

---

## 坑 1：WSLg 的 OpenGL 可能悄悄退化成 CPU 软渲染

**症状**：rviz2 / Gazebo "能跑"，但很卡；`glxinfo` 显示 OpenGL **4.5**（看着没问题）。

**真正的判据是两个字段，不是版本号**：

```bash
glxinfo -B | grep -E "Device|Accelerated"
```

| 结果 | 含义 |
|---|---|
| `Device: llvmpipe (LLVM …)` + `Accelerated: no` | ❌ **CPU 软渲染**。OpenGL 4.5 版本号是真的，但全是 CPU 算的 |
| `Device: D3D12 (NVIDIA GeForce …)` + `Accelerated: yes` | ✅ GPU 直通 |

**根因**：`/usr/lib/wsl/lib/libd3d12.so` 和 `/usr/lib/x86_64-linux-gnu/dri/d3d12_dri.so` 都在，
GPU 通路是具备的，只是 Mesa 没选中 d3d12。

**修法**（实测有效的是第 3 条）：

| 试过的 | 结果 |
|---|---|
| 默认 | llvmpipe / no |
| `MESA_LOADER_DRIVER_OVERRIDE=d3d12` | llvmpipe / no —— **无效** |
| **`GALLIUM_DRIVER=d3d12`** | **D3D12 (NVIDIA GeForce RTX 5060 Laptop GPU) / yes** ✅ |

⚠️ **别只检查版本号就下结论** —— 我上一轮报告过 "OpenGL 4.5 走 WSLg 成功"，
版本号是真的，但它当时其实是软渲染，因为我没查 `Accelerated` 字段。

**持久化**（见坑 2，放 `/etc/profile.d/` 才有效）：

```bash
printf 'export GALLIUM_DRIVER=d3d12\n' > /etc/profile.d/wslg-gpu.sh
chmod 644 /etc/profile.d/wslg-gpu.sh
```

撤销：删掉该文件即可；单次回退 `GALLIUM_DRIVER=llvmpipe glxinfo -B`。

---

## 改完值多少？实测数字（2026-10-13，RTX 5060 Laptop）

**glmark2 完整套件（19 个场景，唯一变量 = `GALLIUM_DRIVER`，640×480 off-screen）**：

| 渲染器 | glmark2 Score |
|---|---|
| `llvmpipe`（CPU 软渲染） | **508** |
| `d3d12`（GPU 直通） | **1852** |
| **提升** | **3.65×** |

最悬殊的场景：`terrain` **12.0 → 641.0 FPS（53×）**、`refract` **36 → 1326 FPS（37×）**、
`shadow` 239 → 1942（8.1×）、`bump high-poly` 262 → 2133（8.1×）。最弱的 `ideas` 也有 1.2×。

**rviz2 实跑（各起 30 秒，读 `ps -o pcpu`）**：

| 驱动 | rviz2 自身 CPU | 备注 |
|---|---|---|
| `llvmpipe` | **76.6 %** | 起得来，但**吃掉 3/4 个核**，笔记本上就是风扇狂转 + 掉电 |
| `d3d12` | **11.5 %** | 正常渲染，CPU 降到 **1/6.7** |

**操作要点**：`glmark2` 的 `-b <场景>` 参数会被忽略（两边都跑完整套件）—— 好处是两组天然可比，
别为此去"修正"，直接用总分。用 `--off-screen` 免开窗口；完整套件在 llvmpipe 上要 **5 分钟以上**，
必须放后台跑（`execute_code` 有 300 s 硬上限，会被杀，且**被杀时 Linux 侧子进程会活下来**，
用 `pgrep -a glmark2` 查、按**精确 PID** 收尾）。

⚠️ 这类基准测的是 **GL 吞吐**，不等于仿真性能 —— Gazebo 的物理步进是 CPU 算的。
GPU 直通救的是渲染（rviz2 可视化、Gazebo 场景显示），不是物理。

---

## 清理进程：绝不用宽泛子串（我踩了两次）

在 WSL 里跑完 GUI/仿真进程后收尾，**不要**写这种：

```bash
# ❌ 会匹配到脚本自身 —— bash 会把 comm 设成脚本名（gz_bridge_test.sh 含 "gz"）
ps -eo pid=,comm= | grep -iE "gz|ruby|gazebo|ros2"
```

上面这行让我**把正在运行的脚本自己杀了**（输出中途变成 `Terminated`，后续检查全没跑）。
同一个坑在更早的 ROS 项目里也出现过（裸 `square_driver` 匹配到脚本命令行，exit 15）。

**安全写法 —— 按可执行文件名精确锚定，或只杀本次启动的 PID：**

```bash
# ✅ 1) 精确锚定可执行名（comm 不会是你的脚本名）
ps -eo pid=,comm= | grep -E "^ *[0-9]+ (ruby|gz|gz-sim|gz-sim-server|gz-sim-gui|gazebo)$"

# ✅ 2) 最稳：启动时就记下 PID，收尾只杀这些
gz sim -s -r -v 2 "$WORLD" > log 2>&1 &
SPID=$!
...
kill "$SPID"
```

**另外**：`wsl.exe ... bash -lc "..."` 里用 `$VAR` 做验证是不可靠的（MSYS 传参时展开时机不对）——
`echo $GALLIUM_DRIVER` 几次都显示空，但 `env | grep -i gallium` 有值、`glxinfo` 也确实是 GPU。
**验证一律用 `command -v` / `env | grep` / `ps`，不要用 `echo $VAR`。**

## 装 Gazebo（ROS 2 Jazzy）:包名不是 `gz-harmonic`

`apt install gz-harmonic` → **`E: Unable to locate package`**。ROS 2 把 Gazebo 打包成 **vendor 包**，
只需一条命令，会自动拉 192 个依赖（143 MB 下载 / 575 MB 磁盘）：

```bash
apt-get install -y ros-jazzy-ros-gz
```

装完得到 **Gazebo Harmonic（`gz-sim 8.15.0`）** + 16 个 `gz_*_vendor` + 6 个 `ros_gz*` 包。
`gz` 可执行文件在 `/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz` —— **需要 source ROS 才在 PATH**
（本机靠 `/etc/profile.d/ros2-jazzy.sh` 自动生效，见坑 2）。

**验证不能只看"没报错"，要拿实时统计：**

```bash
gz sim -s -r -v 2 /opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds/empty.sdf &
sleep 14
gz topic -l | head                       # 应看到 /world/empty/stats 等
gz topic -e -t /world/empty/stats -n 2   # ★ 关键证据
```

实测（empty 世界）：`iterations 13556 → 13647`、**`real_time_factor 0.9987 → 0.9997`**、`step_size 1 ms`。
RTF ≈ 1.0 才说明物理引擎真的在按实时步进；**光"跑满 20 秒没报错"什么都证明不了**（我第一版日志是空的）。

**ROS↔Gazebo 桥接**（这才是 ros_gz 的用途）：

```bash
ros2 run ros_gz_bridge parameter_bridge /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock &
ros2 topic echo /clock --once            # clock: sec: 23, nanosec: 173000000
```

⚠️ 直接用 `ros2 launch ros_gz_sim gz_sim.launch.py` 在 24 秒内**看不到** `/clock`——桥接节点还没把话题挂出来。
要确定性地证明桥接，就**直接跑 `parameter_bridge`**（上面这样），别靠 launch 时序。

**Gazebo GUI 的 CPU 对比（空世界，本机 RTX 5060）**：`llvmpipe` 进程树 **340 %** → `d3d12` **190 %**（1.79×）。
比 rviz2 的 6.7× 弱得多，因为**空世界渲染负载极低，对 GPU 直通不利**；重场景差距会拉大。
且 **Gazebo 的物理是 CPU 算的，GPU 直通只救渲染**。

## 坑 2：`/root/.bashrc` 在这台 WSL 上**不会被加载**（`ros2` 因此一直不可用）

**实测矩阵**（`wsl.exe -d Ubuntu-24.04 -u root -- bash <flag> '…'`）：

| 调用方式 | 加载 `/etc/profile.d/` | 加载 `~/.bashrc` |
|---|---|---|
| `bash -c`（非登录非交互） | ❌ | ❌ |
| `bash -lc`（登录非交互） | ✅ | ❌ |
| `wsl.exe -- <cmd>`（默认调用） | ❌ | ❌ |

**后果**：之前把 `source /opt/ros/jazzy/setup.bash` 写进 `/root/.bashrc`（第 102 行），
新终端里 `ros2` 是 `NOTFOUND`、`import rclpy` 报 `ModuleNotFoundError` —— **那行从来没生效过**。
（`/root/.profile` 里确实有 `if [ "$BASH" ]; then . ~/.bashrc; fi`，但实测没被触发。）

**正确落点**：

```bash
# ROS 2 —— 放 /etc/profile.d/ 才有效
printf 'source /opt/ros/jazzy/setup.bash\n' > /etc/profile.d/ros2-jazzy.sh
chmod 644 /etc/profile.d/ros2-jazzy.sh

# 交互式 shell 兜底
grep -q GALLIUM_DRIVER /etc/bash.bashrc || echo 'export GALLIUM_DRIVER=d3d12' >> /etc/bash.bashrc

# 部分启动路径会读 /etc/environment（注意格式：无 export 关键字）
echo GALLIUM_DRIVER=d3d12 >> /etc/environment
```

**验证**（必须用登录 shell，且不要用 `echo $VAR` —— 经 MSYS 传参时 `$` 展开不可靠，用 `env | grep`）：

```bash
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc 'command -v ros2 || echo NOTFOUND'
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc 'env | grep -i gallium || echo NOT-SET'
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc 'python3 -c "import rclpy; print(1)"'
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc 'glxinfo -B | grep -E "Device|Accelerated"'
```

**教条**：往 WSL 里写任何"开机自动生效"的东西，**必须实测哪种 shell 调用会加载它**，
不要因为文件"存在且有那行"就认为它生效了。验证要用 `command -v` / `env|grep`，不要用 `echo $VAR`。

---

## 附：查 WSL 相关状态

```bash
wsl.exe --version                      # WSL / 内核 / WSLg / Direct3D 版本
wsl.exe --list -v                      # 发行版（经 MSYS 输出是 UTF-16，乱码属正常）
cat /mnt/wslg/versions.txt             # WSLg 内部组件版本
ls /usr/lib/wsl/lib/                   # GPU 直通库（libcuda / libd3d12 / libdxcore）
nvidia-smi                             # CUDA 侧是否通（与 GL 侧是两回事！）
```
⚠️ **`nvidia-smi` 通 ≠ OpenGL 加速通**。CUDA 走 `/usr/lib/wsl/lib/libcuda.so`，
OpenGL 走 Mesa 的 d3d12 gallium 驱动，两条路独立，必须分别验证。
