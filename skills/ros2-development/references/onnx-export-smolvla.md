# SmolVLA → ONNX（torch 2.11 + transformers 5.x + lerobot 0.6.1）

目标：把已经能跑的 PyTorch 策略变成可脱离 Python 部署的 ONNX 工件，并测出三种后端的真实延迟。
实测环境：WSL Ubuntu 24.04、RTX 5060 Laptop 8 GB（sm_120）、torch 2.11.0+cu130、onnx 1.23.2、onnxruntime-gpu 1.31.1。

## 结论（2026-10-27 实测，单帧 fp32）

| 路线 | 结果 | 稳态 |
|---|---|---|
| torch CUDA | 基线 | 250–390 ms |
| torch CPU | 基线 | ~2700 ms |
| ONNX + ORT CUDA EP | ✅ | **211 ms** |
| ONNX + ORT CPU EP | ✅ | 856 ms |
| ONNX + ORT TensorRT EP | ✅（TRT 10.16 配 ORT 1.31） | **80 ms**(fp32) / **76 ms**(fp16) |

数值等价：`max|diff| = 1.341e-06`；图 12 MB + 外置权重 `.onnx.data` 1.6 GB = **合计 1.6 GB**（fp32），IR=10/opset 18，导出耗时 428 s。

**工件迁移必须带两个文件。** onnx 对 >1 GB 的权重会自动外置成同目录 `<name>.onnx.data`；只拷 `.onnx` 时 ORT 装载才报错。核对：`ls -lh <dir>` 里应有成对的 `.onnx` 与 `.onnx.data`。

## 铁则一：必须用 `dynamo=True`

`torch.onnx.export(..., dynamo=False)`（传统 torch.jit.trace 路线）在 transformers 5.x 上必崩：

```
modeling_smolvlm.py:357 → create_bidirectional_mask → eager_mask → sdpa_mask
masking_utils.py:492  q_length, q_offset = q_length.shape[0], q_length[0].to(device)
IndexError: tuple index out of range
```

把每个子模块 config 的 `_attn_implementation` 与 `_attn_implementation_internal` 都设成 `eager` **也救不回来** —— 掩码工具本身把 python int 当张量用，与 trace 不兼容。别在这条路上耗时间。

`dynamo=True` 走 `torch.export.export(..., strict=False)`，能处理 python 标量控制流，四个阶段全绿。依赖 `onnxscript`（缺了报 `ModuleNotFoundError: onnxscript`，`pip install onnxscript` 即解）。

## 铁则二：把随机噪声提成图输入

SmolVLA 的流匹配采样内部用 `randn` 造初始噪声，直接导出会让图不确定。`_get_action_chunk(batch, noise)` **已经暴露 noise 参数**，把它作为第 7 个输入传入即可：

```python
noise = torch.zeros((1, chunk_size, max_action_dim))   # 图输入，确定性
out = policy._get_action_chunk(batch, noise)
```

包装成 `torch.nn.Module` 后 export；`chunk_size=50`、`max_action_dim=32`（不是 6 —— 动作在内部被 pad 到 32 维）。

## 铁则三：onnxruntime-gpu 的 CUDA 库要手动进 `LD_LIBRARY_PATH`

裸装 onnxruntime-gpu 后 CUDA EP 装载失败并**静默回退到 CPU**：

```
Failed to load library .../libonnxruntime_providers_cuda.so
libcublasLt.so.13: cannot open shared object file
```

torch 的 cu13 轮子把库放在 venv 的 `site-packages/nvidia/*/lib`，不在默认搜索路径：

```bash
NV=/root/venvs/vla/lib/python3.12/site-packages/nvidia
export LD_LIBRARY_PATH="$(ls -d $NV/*/lib | tr '\n' ':')$LD_LIBRARY_PATH"
```

补上后 `CUDAExecutionProvider` 正常装载。**首次推理 7972 ms 是 kernel 自动调优，稳态 211 ms** —— 测延迟必须把首次与稳态分开报，否则会得出"ONNX 更慢"的错误结论。

TensorRT EP 需要的是 CUDA 13 对应的 **TRT 10**（不是 TRT 11，且它会静默回退）—— 详见下文「TensorRT EP」一节。

## 导出脚本骨架

```python
class Wrap(torch.nn.Module):
    def __init__(self, p): super().__init__(); self.p = p
    def forward(self, im1, im2, im3, st, tk, mk, nz):
        return self.p._get_action_chunk({
            'observation.images.camera1': im1,
            'observation.images.camera2': im2,
            'observation.images.camera3': im3,
            'observation.state': st,
            'observation.language.tokens': tk,
            'observation.language.attention_mask': mk,
        }, nz)

torch.onnx.export(Wrap(policy).eval(), args, out,
                  input_names=['img1','img2','img3','state','tokens','mask','noise'],
                  output_names=['actions'], opset_version=18, dynamo=True)
```

形状固定：`img (1,3,256,256)` ×3、`state (1,6)`、`tokens (1,48) int64`、`mask (1,48) bool`、`noise (1,50,32)` → `actions (1,50,6)`。**换分辨率、换 batch 都要重导**（无动态轴）。

## fp16：在本模型上不值得做（已实测，2026-10-27）

体积能从 1566 MB 减到 789–816 MB，但**数值全程崩**，且**几乎不加速**：

| 版本 | 做法 | 结果 |
|---|---|---|
| v1–v3 | `onnxruntime.transformers.float16` + 屏蔽 LayerNorm/Softmax | 能跑，但相对误差 **111%**；延迟 283→271 ms（**1.04×**）|
| v4–v5 | 扩大黑名单（Pow/Sqrt/Reciprocal/ReduceMean）+ 修节点重名 | 转换器自身 bug：Cast/张量重名，产不出可加载模型 |
| v6 | `onnxconverter-common` | checker OK，ORT 拒载（`_to_copy_3` 类型不匹配）|

三条铁则式结论：

1. **先看归一化是怎么写的。** 这个模型的 361 层归一化是**算子级展开**的
   （`Pow 373 / Sqrt 361 / Reciprocal 361 / ReduceMean 361`），不是 `LayerNormalization`
   —— 屏蔽 LayerNorm 是无效动作。fp16 上限 65504，`x²` 一超就溢出，整条 RMSNorm 链崩。
   判断方法：转换前先 `Counter(n.op_type for n in graph.node)` 统计一遍。
2. **节点数决定一切，不是 dtype。** 图有 11,640 个节点（Mul 2414 / Transpose 1722 / MatMul 1570），
   单卡笔记本上 kernel launch 开销主导 —— fp16 只降算力、**不降节点数**，所以只有 1.04×。
   想要真加速必须**融合**（TensorRT / torch.compile），不是改精度。
3. **两个官方转换器都会坏图**：ORT 版会产出非拓扑序、重名 Cast；
   onnxconverter-common 版能过 checker 但 ORT 拒载。别再花时间反复试。

验证 fp16 是否“真可用”的最低门槛：`max|diff| < 1e-2`（本模型实测 1.33，即废）。

## TensorRT EP：大版本必须配对，且会静默回退

onnxruntime-gpu 的 TRT EP 是**针对某个 TensorRT 大版本编译的动态库**。实测 ortre 1.31.1 需要 `libnvinfer.so.10`，
装 TRT 11.4（`tensorrt-cu13`）会报：

```
Failed to load library .../libonnxruntime_providers_tensorrt.so
  with error: libnvinfer.so.10: cannot open shared object file
Falling back to ['CUDAExecutionProvider', 'CPUExecutionProvider'] and retrying.
```

**危险在于它会静默回退**：session 照常建、推理照常出结果，只比纯 CUDA 快 1.09×（噪声），
很容易写成“TRT 已加速”。三个必查证据：

1. `session.get_providers()` 首位必须是 `TensorrtExecutionProvider`；
2. `trt_engine_cache_path` 里应有 `.engine` 文件（没建 engine = 没跑 TRT）；
3. 与 CUDA 基线的 `max|diff|` **恰好 = 0.000e+00** → 说明跑的是同一条 CUDA 路径。

正确做法：`pip install tensorrt-cu13==10.16.1.11`（配 CUDA 13 的 TRT 10），
并把 `tensorrt_libs` 加进 `LD_LIBRARY_PATH`（与 CUDA 库同一坑）。

### 装对之后的实测（同一张 5060、同一份 fp32 ONNX）

| 后端 | engine 构建 | 首次 | 稳态 | 相对 CUDA | max\|diff\| |
|---|---|---|---|---|---|
| ORT CUDA | — | 880 ms | 203–264 ms | 1.00× | 基线 |
| TRT fp32 | **~150 s** | 153–163 ms | **80–106 ms** | **2.5×** | 1.1–1.3e-03 |
| TRT fp16 | **~138 s** | 156 ms | **76 ms** | **3.4×** | 1.45e-03 |

三条可以直接拿去用的结论：

1. **层融合才是加速来源。** 同一张图 11,640 节点，ORT 重写 fp16 只快 4%，TRT 快 2.5–3.4× —— 
   差别在于 TRT 把节点熔成几十个 kernel，而不是把 tensor 换成半精度。
2. **同一个 fp16，走 TRT 可用、走 ORT 图重写就崩。** TRT 自己管精度（敏感层保留 fp32），
   所以 1.45e-03 的误差完全可用；这说明“fp16 不行”是转换器的结论，不是 fp16 的结论。
3. **engine 缓存必须用 provider options 传参**（根因已查清，2026-10-28）。
   把 `trt_engine_cache_enable` 写进 `SessionOptions.add_session_config_entry` **不生效也不报错**：
   每轮重建 150 s、缓存目录永远 0 MB。正确写法：

   ```python
   trt = {'trt_engine_cache_enable': True, 'trt_engine_cache_path': CACHE,
          'trt_engine_cache_prefix': 'v3_fp32', 'trt_builder_optimization_level': 3}
   sess = ort.InferenceSession(model, providers=[('TensorrtExecutionProvider', trt),
                                                 'CUDAExecutionProvider', 'CPUExecutionProvider'])
   ```

   修好后实测：首次装载 **171.7 s** → 缓存 **1518 MB**（`..._sm120.engine`）→ 二次装载 **14.7 s**（11.7×）。
   带外置权重的图先 `onnx.save(onnx.load(p), merged)` 合并成单文件，缓存更可靠。
   engine 绑定 **GPU 架构（sm120）+ TRT 版本 + 图结构**，换卡/升 TRT/改 shape 都得重建。

4. **计时用 `time.perf_counter()`。** WSL 时钟会跳，用 `time.time()` 曾算出
   **CUDA 基线 −597 ms**、加速比 −5.65× 这种负值；单调时钟才不会骗人。

## 接进 ROS 节点：加一个 backend 开关，再做一次数值自检

`smolvla_policy.py` 用 `backend` 参数（环境变量 `SMOLVLA_BACKEND`）切 torch / onnx，
预处理链（`make_smolvla_pre_post_processors`）两边共用 —— 这是保证“换后端不换语义”的关键。

节点启动时必须做**一次性对齐自检**：同一批次分别过 torch 与 onnx，打 `max|diff|`。
实测 **9.091e-03**（torch 侧 bf16、ONNX fp32，量级合理），超过 1e-2 就该报错而不是继续跑。

全栈实测（同一套控制器与桥）：

| 后端 | 单次推理 | chunk 频率 | 跟踪误差均值 |
|---|---|---|---|
| torch | 0.25–0.39 s | 1.90–2.02 Hz | 0.0116 rad |
| ONNX+TRT | **0.072–0.154 s** | **7.97–8.01 Hz** | **0.0007 rad** |

注意：误差变小**不是模型变准**，而是块更密（8 Hz 下每块只推进 1/8 s），桥的限速滞后来不及累积。
提频率只需 `-p chunk_rate:=8.0`，但 `chunk_timeout` 要跟着缩小（本仓用 1.0 s）。

## 对部署的含义

211 ms / 次 → 4.7 Hz；而一块 chunk 覆盖 50×1/30 = 1.67 s，**2 Hz 上游刷新就够**，余量充足。
上 TRT fp16 后是 76 ms（13 Hz），单帧延迟已经不是瓶颈了 —— 真正的部署瓶颈变成了
“engine 要不要每次重建”和“控制环能不能吃下更快的块”。工件 1.6 GB（fp32）交 C++ onnxruntime 即可脱离 Python。
