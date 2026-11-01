---
name: local-llm-windows-gpu
description: Run local LLMs on a Windows NVIDIA box.
version: 1.0.0
author: robo-agent contributors
license: MIT
metadata:
  hermes:
    tags: [ollama, gguf, quantization, lora, qlora, blackwell, sm_120, china-mirror, vram]
    related_skills: [llama-cpp, huggingface-hub]
---

# 本地大模型（Windows + NVIDIA 单卡）

## When to Use / 何时用

- 想在本机跑本地模型（ollama / llama.cpp / GGUF / 微调）
- 要下模型权重（**中国网络 → 必走镜像，见下**）
- 要对比量化等级 / 测吞吐 / 测显存
- 要判断"这块显卡能不能跑 LoRA / 微调 / 某个推理框架"
- 遇到 `no kernel image is available for execution on the device`（Blackwell）

## 反面提醒（先读，能省一天）

对**非 AI 专业的学生用户**，本地模型 **90% 是教具、10% 是离线兜底，不是生产力工具**。
先问一句"这跟你的优先级排第几"，再动手。真实价值只有两条：
1. **可微调**（LoRA / QLoRA）——"我能改造一个模型"
2. **搞懂推理本身**（token、prefill/decode、量化、显存）——"我懂 AI 为什么慢"

隐私 / 省钱 / 替代云端助手 / 会议转写 / 自动写报告 —— 对个人用户**基本都不成立**，别拿这些当理由。
**"我跑过 ollama"不是项目，是使用记录。** 不要让它进简历的"项目经历"。

**别把 0.5B 接进要用它干活的工具。** 本机的 `qwen05-*` / `qwen2.5:0.5b` 是**测吞吐的教具**：
接进任何"润色 / 翻译 / 改写"类应用（如 WindowSill 的本地供应商、编辑器插件），输出通顺但空洞，
用户会以为工具坏了。（2026-10 实测三个任务：提取行动项 → **原样照抄**；改 30 字通知 → 只加"通知："前缀；
中译英 → 留着"实训楼/实训 building"没译。速度 370–420 tok/s、100% GPU，**瓶颈不是速度**。）要用就先 `ollama pull qwen3:8b`（Q4 约 5 GB，8 GB 显存全上卡）；
**4B 是底线，8B 才是中文可用线**，1.5B 以下只适合分类/抽取这类窄任务。

## 步骤 1：先量硬件，别猜

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
ollama --version ; ollama ps ; ollama list
du -sh "$LOCALAPPDATA/hermes/models/gguf" 2>/dev/null
```

判据：
- **`compute_cap` 是硬约束**。Blackwell（RTX 50 系） = **sm_120 / compute_cap 12.0**。
  → `pip install torch` **必须选 cu128 或更新的 wheel**；CUDA 需 12.8+。
  装错报错：`no kernel image is available for execution on the device`（不是"显卡坏了"）。
- 显存 8 GB 档 → 7~8B **Q4 全上显卡**流畅；14B 部分卸载；32B dense 别想。
- **vLLM / LMDeploy / TGI 在小显存上跑不了**（起配 16~24 GB），别装。

## 步骤 2：下模型 —— 镜像 + Python，别用 curl / ollama pull

**实测数字（本机，2026-10）：**

| 方式 | 速度 | 7B Q4（4.7 GB） |
|---|---|---|
| `ollama pull` | **613 KB/s** | 约 2.1 小时 |
| `hf-mirror.com` / **ModelScope** + **Python urllib** | **5.5 ~ 9.24 MB/s** | 约 8.5 分钟 |
| **`curl`** | **0 字节** | 永远下不完 |

**两个已证实的大坑：**
1. **本机 `curl` 坏**（对可达的模型 CDN 返回 0 字节：HTTP 200/206 但无数据；Steam++/Watt Toolkit 在做 TLS MITM，且 curl 需 `--ssl-no-revoke`）。
   → **别用 curl 下模型**。用 Python `urllib`。
   → **失败时先怀疑 curl，不要归因于"被墙"** —— 这个误判会浪费一整轮排查。
2. `hf-mirror.com` 现在**只做 API 层**，文件会 **302 到境外 CDN**；`ModelScope` 跳 `cdn-lfs-cn-1.modelscope.cn`（国内 CDN）。
   两个用 Python 都实测 5.5~9.24 MB/s，都行。

```python
# 断点续传下载 GGUF（可复用：%LOCALAPPDATA%\hermes\scripts\gguf_tool.py）
import urllib.request
url = "https://hf-mirror.com/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
dst = r"%LOCALAPPDATA%\hermes\models\gguf\qwen2.5-0.5b-instruct-q4_k_m.gguf"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
    while chunk := r.read(1 << 20):
        f.write(chunk)
```

## 步骤 3：导入 ollama（绕过 registry）

```
# Modelfile
FROM ./qwen2.5-0.5b-instruct-q4_k_m.gguf
```
```bash
ollama create mymodel:q4km -f Modelfile
```

## 步骤 4：接第三方客户端前 —— Qwen3 的思考坑（必读）

`qwen3:8b` 拉下来**默认是思考模式**：本机实测一次 40 字中文改写 = **30.9 s / 433 tok**（真正答案只有 17 tok）。
第三方客户端（WindowSill、编辑器插件…）不会传 `think:false`；把 `/no_think` 写进提示词**无效**（实测仍 397 tok）；
走 OpenAI 兼容端点 `/v1/chat/completions` 也关不掉（384 tok / 9.8–16.3 s）。

**解法：派生一个强制不思考的模型**（共享 blob，不额外占磁盘）。模型 template 里有两处 `.IsThinkSet` 分支：

1. user 消息段：`{{- if and $.IsThinkSet (eq $i $lastUserIdx) }}…{{- end }}` 整段换成
   `{{- if eq $i $lastUserIdx }}{{ " " }}/no_think{{- end }}`
2. 生成提示段：把 `{{ if and $.IsThinkSet (not $.Think) -}} … {{ end -}}` 这对包裹删掉，
   只留 `<think>\n\n</think>\n\n`

```
FROM qwen3:8b
TEMPLATE """<改好的模板>"""
PARAMETER temperature 0.3
PARAMETER num_ctx 8192
```
```bash
ollama create qwen3-8b-fast -f "C:/Users/<u>/.../Modelfile"
```

实测：**2.5–3.2 s / 17–56 tok**，`thinking` 字段为空，`100% GPU`（8.2k ctx 占 6.2 GB），质量未损（保留 82%/94% 等数字、不加戏）。

**两个 Windows 坑**：`ollama create -f /c/Users/...` 报 `no Modelfile or safetensors files found`（原生程序不认 MSYS 路径，要 `C:/` 正斜杠）；
改模板时**删 `if` 必须连配对的 `{{ end -}}` 一起删**，否则 `template error: unexpected {{end}}`。

## 步骤 5：确认它真的在客户端里跑起来了

把模型接进第三方客户端（WindowSill、编辑器插件之类）后，**四条都要过**，少一条就是“看着能用、其实没接上”：

1. **端点 ≠ 有模型。** 客户端里填 `http://localhost:11434` 只是指路，模型必须在本地已存在（`ollama list` 能看到），
   否则下拉列表里只有旧的、拿它测出来的结论全是错的。
2. **跑完回头查 `ollama ps`。** 只有目标模型出现在表里且 `100% GPU` 才算真跑；前面看到的“成功结果”可能来自上一次的旧默认模型。
3. **不知道客户端走哪条 API，就把两条都测**：`/api/chat`（结构化 messages）和 `/api/generate`（裸 prompt）行为不同，
   `/v1/chat/completions` 对 `think` 参数的处理又是另一套。派生模型后两条都要验（本机实测两条都是 2.5–3.2 s）。
4. **不要用一次调用成功就断言“这个功能免费/无限制”。** 授权闸可能在下一次操作或某个入口才弹；
   先读厂商 pricing/对比页，再用**两个不同入口各跑一次**复现。本机踩过：先用 Ollama 跑出结果 → 当场判定“本地免费可用”→
   下次一点就弹 WindowSill+ 升级框。**一次成功只证明这一次没拦，不证明不受限。**

**客户端 UI 字段也别猜**：WinUI/MSIX 应用的扩展装在
`%LOCALAPPDATA%\Packages\<包名>\LocalState\Plugins\<插件id>\lib\<tfm>\<命名空间>\Settings\*.xaml`（常经 junction 落在别的盘），
直接读 `<TextBox>` / `<ComboBox>` / `<CheckBox>` 的绑定和 `x:Uid` 就知道对话框有几个字段、叫什么；
.xaml 里拿不到人类可读标题时，用结构（字段类型/先后顺序）+ 官方介绍文案交叉印证，再向用户表述。

## 步骤 6：测吞吐 —— 走 HTTP API，**不要解析 `--verbose` 文本**
`ollama run --verbose` 的输出里 **`eval rate:` 会匹配到 `prompt eval rate:` 里面**。
用正则抓 `eval rate:` 会拿到同一个数两次 → 表格两列数字相同、还可能得出"q8 比 q4 快"这种物理上不可能的结果。
**血泪教训：先用文本解析出的对比表是错的，整张作废。**

正确做法 —— 读结构化纳秒字段：

```python
import json, urllib.request
def gen(model, prompt, n=256):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"num_predict": n}, "keep_alive": "0s"}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return {"load_ns": d["load_duration"], "prefill_ns": d["prompt_eval_duration"],
            "n_prefill": d["prompt_eval_count"], "decode_ns": d["eval_duration"],
            "n_decode": d["eval_count"],
            "tok_s": d["eval_count"] / (d["eval_duration"] / 1e9)}
```

可复用实现：`%LOCALAPPDATA%\hermes\scripts\bench_api.py`（`--runs N`）。

## 步骤 7：测显存 —— 用 `ollama ps` 的 SIZE 列

**`nvidia-smi` 差值法对 <1 GB 的模型不可靠。** 实测空载读数在 **2881 → 1710 → 1704 → 1139 MiB** 之间乱跳（桌面/浏览器波动），
算出过 **-4 MB** 的增量。只有 1.1 GB 的 fp16 超出了噪声（增量 1183 MB ✓）。

→ **用 `ollama ps` 的 SIZE 列**（ollama 自己记账的每模型占用），或关掉别的吃显存程序再测。

## 实测基准（Qwen2.5-0.5B，RTX 5060 Laptop 8 GB，2026-10）

| 模型 | 量化 | 体积 | 生成 | prefill(热) | 冷加载 |
|---|---|---|---|---|---|
| `qwen05-q4km` | **Q4_K_M** | **481 MB** | **332 tok/s** | 21142 tok/s | 1.31 s |
| `qwen05-q8` | Q8_0 | 615 MB | 292 tok/s | 8849 tok/s | 1.32 s |
| `qwen05-fp16` | F16 | 1.1 GB | 200 tok/s | 9821 tok/s | 1.32 s |

- **Q4_K_M 比 F16 快 1.66×，体积 1/2.6**；三者全部 `100% GPU`。
- **冷启动陷阱**：第一次跑 **22.49 s**（Blackwell sm_120 的 CUDA kernel **首次 JIT 编译**，一次性），
  编完之后冷加载只要 **1.3 s**。**不知道这件事的人第一次跑完就以为"本地模型太慢"，然后放弃。**
  测速前先跑一次热身，别把 JIT 计入冷启动。

## LoRA / QLoRA 显存与参数量速算

公式（`scripts/lora_sizing.py` 可直接跑，从 HF 上游 config.json 实读）：

- 总参数 `N = L·(h² + 2·h·kv + h² + 3·h·inter) + V·h`，其中 `kv = (h/num_attention_heads)·num_key_value_heads`
- LoRA 可训练参数 `= Σ_targets r·(in + out)`（每个目标矩阵加 A(r×in) + B(out×r)）
- 全参微调显存 ≈ `N × 12 B`（fp16 权重 2 + fp16 梯度 2 + Adam fp32 m/v 8），**再加激活/碎片，实际 ×2 以上**
- QLoRA 4-bit 基座 ≈ `N × 0.55 B`

实测（从上游 config.json 实算）：

| 模型 | 总参数 | 全参微调 | LoRA r=8 (q,v) | 适配器文件 | QLoRA 4-bit 基座 |
|---|---|---|---|---|---|
| Qwen2.5-0.5B | 494 M | 5.5 GB | 0.541 M (**0.109%**) | **1.03 MB** | 0.25 GB |
| Qwen2.5-7B | 7070 M | **79 GB** | 2.523 M (**0.036%**) | **4.81 MB** | **3.62 GB** |

**结论：7B 全参微调要 79 GB（单卡 8 GB 不可能）；同一模型 QLoRA 4-bit 基座只要 3.62 GB → 8 GB 单卡放得下。**
这就是 LoRA/QLoRA 的存在理由：**冻结原权重，只训一个万分之一量级的旁路补丁。**

**别搞混两件事：**
- **练 LoRA** 需要的是 GPU + PyTorch/peft —— **不需要手机、不需要树莓派**
- **端侧部署**（llama.cpp 跑在 ARM/手机上）才需要手机/树莓派 —— 是另一件事

## LoRA 能做什么 / 不能做什么

- **能**改：口吻、格式、术语习惯、固定任务的输出规范（"学怎么说"）
- **不能**注入新知识（那是 RAG 的活，"学说什么"）。用几百条数据训不出模型不知道的事实。
- 质量**取决于数据集**，不取决于 LoRA 超参。**没有数据集 = 没有 LoRA。**
- 常用栈：`peft` + `transformers` + `trl`(SFTTrainer) + `bitsandbytes`(4-bit) + `datasets`

## 已在 sm_120 上跑通的 QLoRA 全流程（2026-10-15 实测）

**版本组合（全部实测可用，Windows + RTX 5060 Laptop）**

| 组件 | 版本 | 备注 |
|---|---|---|
| torch | **2.14.1+cu130** | `get_arch_list()` 含 sm_120 ✓；win wheel **1990.6 MB**，下载 12 分 46 秒 |
| transformers | 5.19.0 | ⚠️ 大版本 API 变更，见下 |
| peft | 0.21.2 | |
| bitsandbytes | **0.50.2** | 官方 win 轮子 `py3-none-win_amd64`（39.1 MB）✓，不需要 triton |
| accelerate / datasets / safetensors | 1.15.0 / 5.1.0 / 0.8.0 | |

```bash
python -m venv E:/LoRA-venv
E:/LoRA-venv/Scripts/python.exe -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
E:/LoRA-venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu130
E:/LoRA-venv/Scripts/python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    transformers peft accelerate bitsandbytes datasets safetensors
```

**0.5B 实测数字**：4-bit nf4 加载 7.2 s / 基座占显存 **436 MiB**（峰值 478）；
LoRA r=8 + 全 7 个线性层 → 可训练 **4,399,104 / 498,431,872 = 0.8826%**，适配器 **29 MB**；
24 条 × 3 epochs（batch1 × accum8）= **9 个优化步 / 36.27 s**。

**transformers 5.x 会直接报错的改名**：`warmup_ratio` → **`warmup_steps`**；
`evaluation_strategy` → `eval_strategy`。
**别猜 API，内省**：`inspect.signature(TrainingArguments.__init__).parameters`。

**两条血泪教训（比上面的命令重要）**

1. **评分函数必须在训练之前验证过它能区分好坏。** 我最初拿「结论前置」当指标 —— 三组 6/6 全过，
   毫无区分度，等于没测，训完才发现。有区分度的是：**平均字数 / 术语命中 / 幻觉数字 / 退化条数 / 泛化正确性**。
2. **数据量不足时，LoRA 会让幻觉"更可信"。** 24 条数据训完，模型编出
   「专利号 `ZL 2019 3 074852.1`，授权公告日 2020年1月1日」；原始模型至少只编明显空话。
   **形式类微调 = 把幻觉包装成确凿事实**，拿去做答辩会当场穿帮。
   同时输出被压短 2.3 倍并出现"没有。"这种空退化 + 数值复读（`99.9999…`）。
3. 版本号**不能用字符串排序**（`"2.9.1" > "2.14.1"` 字典序成立）→ 用 `packaging.version.parse`。

## 相关技能

- `llama-cpp` —— llama.cpp + GGUF 本地推理细节
- `huggingface-hub` —— `hf` CLI 搜/下/传模型
