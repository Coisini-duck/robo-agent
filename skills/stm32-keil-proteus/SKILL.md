---
name: stm32-keil-proteus
description: STM32 in Keil + Proteus with no hardware.
version: 1.0.0
author: INA + Hermes
license: MIT
metadata:
  hermes:
    tags: [stm32, keil, mdk, proteus, embedded, stm32f103, no-hardware, simulation]
    related_skills: [windows-desktop-app-ops]
---

# STM32 开发（Keil MDK + Proteus，无硬件路线）

## When to Use / 何时用

- 用户要做 STM32 项目但**没有开发板/调试器**
- 要装 **Keil 器件包（DFP）**、命令行编译、生成 .hex
- 要在 **Proteus 里仿真 STM32 + OLED + 传感器**
- 要判断某台机器上嵌入式工具链到底齐不齐

## 本机环境（2026-10-12 实测，勿凭记忆）

| 组件 | 路径 |
|---|---|
| Keil MDK v5（ARMCC V5.06u7 + ARMCLANG6） | `E:\QianRuShi\Keil_v5\UV4\UV4.exe` |
| Keil Pack 根（TOOLS.INI `RTEPATH`） | `E:\QianRuShi\Keil_v5\Arm\Packs` ← **注意拼写是 `Arm\Packs`** |
| Keil C51 | `E:\keil\C51` |
| ST-LINK Utility + `ST-LINK_CLI.exe` | `C:\Program Files (x86)\STMicroelectronics\STM32 ST-LINK Utility\` |
| J-Link V6.30d | `C:\Program Files (x86)\SEGGER\JLink_V630d\` |
| **Proteus 8** | `E:\QianRuShi\Proteus8\`（库 `DATA\LIBRARY\`、模型 `DATA\MODELS\`） |
| 江协科技**43 课时源码**（已解压） | `E:\QianRuShi\STM32学习\程序源码\{STM32Project-有注释版, 无注释版}\` |
| 模块资料（14 个模块，已解压） | `E:\QianRuShi\STM32学习\模块资料\` |
| 原始资料 zip（1.9 GB） | `E:\QianRuShi\资料文件\MDK相关\` |

**Keil 授权**：`TOOLS.INI` 里 `TOOL_VARIANT=mdk_std` → 无 32 KB 代码上限。

## 步骤 1：清点（别猜）

```bash
for t in arm-none-eabi-gcc openocd STM32_Programmer_CLI; do command -v $t || echo "$t 未装"; done
ls "/e/QianRuShi/Keil_v5/ARM/PACK/.Download/"     # 看装了哪些包
ls -d "/c/Users/INA/STM32Cube/Repository"          # CubeMX 固件包仓库
find /e /d -maxdepth 5 \( -iname "*.uvprojx" -o -iname "*.ioc" \) 2>/dev/null | head
powershell -NoProfile -Command 'Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match "COM[0-9]" -or $_.Name -match "ST-?Link|CH340|CP210" } | Select-Object -ExpandProperty Name'
```
⚠️ **COM 口陷阱**：`BTHENUM\{00001101-...}` 开头的 COM 口是**蓝牙串口**，不是 USB-TTL。
看到 4 个 COM 口不等于有调试器 —— 必须看 DeviceID。

## 步骤 2：装 Keil 器件包（DFP）

**不需要 GUI、不需要 Pack Installer** —— 从 keil.com 下 .pack 直接解到 Pack 根：

```bash
# 直接探测版本（2.4.3/2.4.2 可能是 404，2.4.1 存在）
# https://www.keil.com/pack/Keil.STM32F1xx_DFP.<ver>.pack     (~48 MB)
# https://www.keil.com/pack/Keil.STM32F4xx_DFP.2.17.1.pack    (~290 MB)
```
```python
import zipfile, os
pack = r"...\Keil.STM32F1xx_DFP.2.4.1.pack"
dest = r"E:\QianRuShi\Keil_v5\ARM\PACK\Keil\STM32F1xx_DFP\2.4.1"   # 层级必须对!
os.makedirs(dest, exist_ok=True)
with zipfile.ZipFile(pack) as z:
    z.extractall(dest)
```
**层级铁律**：`<Pack根>\<Vendor>\<PackName>\<Version>\`，且 `*.pdsc` 必须在版本目录根部。
装完验证：pdsc 里 `<Dname="STM32F103C8"` 存在、`Device/`、`SVD/`、`Flash/` 都在。

⚠️ **两个"看着不一致其实一致"的假警报**（别浪费时间）：
1. `TOOLS.INI` 写 `Arm\Packs`，实际目录可能显示 `ARM\PACK` —— **Windows 路径大小写不敏感，同一个目录**。
2. 工程里 `<PackID>...DFP.2.2.0</PackID>` 但你装了 2.4.1 —— **实测 0 Error 0 Warning，MDK 自动用已装的更新版**。

⚠️ **下载慢**：keil.com 从中国实测只有 **0.32 MiB/s**（48 MB 花了 148 秒）。用 Python urllib，别用 curl（本机 curl 返回 0 字节）。

## 步骤 3：命令行编译（唯一的"真的编译过"证据）

```bash
"E:/QianRuShi/Keil_v5/UV4/UV4.exe" -b "E:/path/to/Project.uvprojx" -j0 -o "E:/build.log"
```
- 退出码：0 = 无错无警；1 = 有警；2+ = 有错
- 日志是 **GBK** 编码，用 `open(log,'rb').read().decode('gbk','ignore')` 读
- 中文路径没问题（实测 `4-1 OLED显示屏` 可编译）
- 本地基准：江科大 4-1 OLED 例程 → **Code=2160 RO-data=1772 ZI-data=1632，4 秒，0 Error 0 Warning**

## 步骤 4：生成 .hex（Proteus 必需）

江科大例程**默认不开 hex 输出**，只出 `.axf`。两条路：

**(a) 打开工程开关**（一次改好，以后 F7 都出 hex）—— 按字节替换，别动编码：
```python
raw = open(prj, "rb").read()
open(prj, "wb").write(raw.replace(b"<CreateHexFile>0</CreateHexFile>",
                                  b"<CreateHexFile>1</CreateHexFile>"))
```
然后重新 `UV4 -b` → 日志出现 `FromELF: creating hex file...`

**(b) 事后转换**：`fromelf.exe --i32 Project.axf --output Project.hex`
（在 `E:\QianRuShi\Keil_v5\ARM\ARMCC\bin\fromelf.exe`）

**hex 校验**：末行必须是 `:00000001FF`；首行 `:020000040800F2` 是 **type-04 扩展地址记录**，把高 16 位设为 `0x0800` → 基址 `0x08000000`。
⚠️ **解析地址时必须处理 type-04**，否则会误报"起始地址不是 0x08000000"（我踩过）。

## 步骤 5：Proteus 仿真

**本机 Proteus 8 已有的模型（实测）**：

| 器件 | 库文件 | 说明 |
|---|---|---|
| STM32F103C8T6 | `CM3_STM32.LIB` + **`BluePill.LIB`**（模型 `cm3_stm32.dll`） | Cortex-M3 |
| STM32F4 | `CM4_STM32.LIB`（`cm4_stm32.dll`） | Cortex-M4 |
| **SSD1306 / OLED** | `DISPLAY.LIB` | I2C OLED |
| **DS18B20** | `MAXIM.LIB` | 单总线温度 |
| NTC 热敏 | `NTC.LIB` | |
| 官方样例 | `DATA\SAMPLES\VSM for Cortex M3` 等 | |

```bash
# 查模型是否存在（比开 GUI 找快）
grep -ril "DS18B20" "E:/QianRuShi/Proteus8/DATA/LIBRARY/"
grep -ril "SSD1306" "E:/QianRuShi/Proteus8/DATA/LIBRARY/"
ls "E:/QianRuShi/Proteus8/DATA/LIBRARY/" | grep -iE 'stm32|cm3|cm4'
```

**流程**：Proteus 放 MCU → 双击 → `Program File` 选 `Objects\Project.hex` → 运行。
⚠️ 选 **`.hex`**，不是 `.axf`。

**江科大例程真实引脚（从源码读出，别背）**：
- `4-1 OLED显示屏`：SCL=**PB8**、SDA=**PB9**，**软件 I2C**（`GPIO_Mode_Out_OD` 翻转模拟），**不是硬件 I2C1**
- `7-1 AD单通道`：ADC1_IN0 = **PA0**

⚠️ **Proteus 的 OLED 模型有时不完美**（点不亮/错位）。卡住超过 1 小时就退一步：用字符 LCD 或串口终端（`9-1 串口发送`）验证，**目标是验证逻辑，不是点亮某块屏**。

## 步骤 6：解压中文 zip（GBK 文件名）

江科大/正点原子的教学 zip **没设 UTF-8 标志**，Python 默认按 cp437 读 → 全是乱码。
```python
with zipfile.ZipFile(src, metadata_encoding="gbk") as z:   # Python 3.11+
    z.extractall(out)
```
解出来的顶层往往和输出目录同名 → 会**多套一层**，记得拍平。
验证：`os.listdir()` 打印出来应该是 `2-1 STM32工程模板`、`4-1 OLED显示屏` 这种。

## 江协科技 43 课时 → 温控项目阶梯映射

| 阶梯 | 现成课时 |
|---|---|
| 1 读温度+显示 | `2-1 STM32工程模板` `1-3 Delay` **`7-1 AD单通道`** **`1-4 OLED驱动函数模块`** **`4-1 OLED显示屏`** `3-4 按键控制LED` |
| 2 PWM控执行器 | **`6-1 定时器定时中断`** **`6-3 PWM驱动LED呼吸灯`** **`6-5 PWM驱动直流电机`** |
| 3 阈值开关控温 | 拼 `7-1` + `6-3` + `3-4` |
| 4 PID恒温 | `6-1 定时器定时中断` = PID 骨架 |
| 调 PID 必备 | **`9-1`~`9-4 串口`** ← 不看响应曲线就是盲调 |

**这套资料没有 DS18B20 例子**（全库搜 `18B20` = 0 命中），温度传感器只有 `5-热敏电阻传感器`（NTC + ADC）。
DS18B20 单总线是**微秒级时序**（480 µs 复位、15/45/60 µs 时隙）→ `HAL_Delay()` 会完全失败；
**读回恒定 85.0℃** = 上电默认值 = 通信没成功。

## 相关技能

- `windows-desktop-app-ops` —— Windows 应用/端口/进程排查
- `hermes-cron-jobs` —— 如果要挂定期检查
