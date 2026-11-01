#!/usr/bin/env python3
"""LoRA / QLoRA 显存与参数量速算 —— 从 HF 上游 config.json 实读，不猜。

用法:
    python lora_sizing.py                                  # 默认对比 0.5B ~ 32B
    python lora_sizing.py Qwen/Qwen2.5-1.5B-Instruct       # 指定任意 HF repo
    python lora_sizing.py --gpu-mib 8151                   # 附"本机显卡能不能跑"判定
    python lora_sizing.py --gpu-mib 8151 --adam-bits 8     # 按 8-bit Adam 估（省一半）

要点（都是踩过的坑）:
  * 参数量必须从真实 config.json 算，别凭记忆写 hidden_size —— 抄错一个数，结论全错。
  * 微调显存分两块，别混为一谈:
      (a) **参数 + 梯度 + 优化器状态** —— 可以精确算: N × (2 + 2 + adam_bits/8 × 2) 字节
          （fp16 权重 2 + fp16 梯度 2 + Adam m,v）
      (b) **激活值** —— 取决于 batch × seq_len × 层数，**不是参数量乘以某个魔数**。
          本脚本只允许用 --act-gib 显式给一个假设值（默认 2 GiB），并在输出里写清楚。
  * QLoRA 4-bit 基座 ≈ 0.55 B/参数。
  * LoRA 可训练参数 = Σ_targets r·(in+out)，通常只占总参数的 0.02%~1%。
  * 中国网络: hf-mirror.com + urllib（本机 curl 对模型 CDN 返回 0 字节，见 SKILL.md）。
"""
import argparse
import json
import sys
import urllib.request

MIRROR = "https://hf-mirror.com"

DEFAULT_REPOS = [
    "Qwen/Qwen2.5-0.5B-Instruct",
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen2.5-14B-Instruct",
    "Qwen/Qwen2.5-32B-Instruct",
]

PROJ_SHAPES = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")

GIB = 2 ** 30
MIB = 2 ** 20


def fetch_config(repo: str) -> dict:
    """从镜像拉 config.json。先试 hf-mirror，失败回退 huggingface.co。"""
    last = None
    for base in (MIRROR, "https://huggingface.co"):
        url = f"{base}/{repo}/resolve/main/config.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001 - 回退到下一个源
            last = exc
    raise RuntimeError(f"拉不到 {repo} 的 config.json: {last}")


def analyze(cfg: dict) -> dict:
    """按 Qwen/Llama 系 dense decoder 结构算每层与总参数量。"""
    h = cfg["hidden_size"]
    layers = cfg["num_hidden_layers"]
    n_heads = cfg["num_attention_heads"]
    n_kv = cfg.get("num_key_value_heads", n_heads)  # GQA
    inter = cfg["intermediate_size"]
    vocab = cfg["vocab_size"]
    kv = (h // n_heads) * n_kv  # k/v 投影的输出维度

    attn = h * h + h * kv * 2 + h * h  # q_proj + k_proj + v_proj + o_proj
    mlp = 3 * h * inter  # gate + up + down
    per_layer = attn + mlp
    total = per_layer * layers + vocab * h  # 词嵌入（一般 weight tying，不另加 lm_head）
    return {
        "h": h, "layers": layers, "n_heads": n_heads, "n_kv": n_kv, "kv": kv,
        "inter": inter, "vocab": vocab,
        "attn": attn, "mlp": mlp, "per_layer": per_layer, "total": total,
    }


def lora_trainable(a: dict, rank: int, targets=("q_proj", "v_proj")) -> int:
    """Σ r·(in+out)，每个目标矩阵新增 A(r×in) 与 B(out×r)。"""
    h, kv, inter, layers = a["h"], a["kv"], a["inter"], a["layers"]
    shapes = {
        "q_proj": (h, h), "k_proj": (h, kv), "v_proj": (h, kv), "o_proj": (h, h),
        "gate_proj": (h, inter), "up_proj": (h, inter), "down_proj": (inter, h),
    }
    bad = set(targets) - set(PROJ_SHAPES)
    if bad:
        raise ValueError(f"未知目标模块: {bad}")
    per_layer = sum(rank * (i + o) for t, (i, o) in shapes.items() if t in targets)
    return per_layer * layers


def gib(bytes_: float) -> float:
    return bytes_ / GIB


def report(repo: str, ranks=(8, 16, 32), gpu_mib: int | None = None,
           adam_bits: int = 32, act_gib: float = 2.0) -> dict:
    a = analyze(fetch_config(repo))
    total = a["total"]
    bytes_per_param = 2 + 2 + (adam_bits / 8) * 2  # fp16 W + fp16 G + Adam m,v
    state_bytes = total * bytes_per_param
    qlora_bytes = total * 0.55

    print(f"\n{'=' * 78}")
    print(f"{repo}")
    print(f"  hidden={a['h']}  layers={a['layers']}  q_heads={a['n_heads']}  "
          f"kv_heads={a['n_kv']} (kv_dim={a['kv']})  inter={a['inter']}  vocab={a['vocab']}")
    print(f"  每层 attn={a['attn'] / 1e6:.3f}M  mlp={a['mlp'] / 1e6:.3f}M")
    print(f"  总参数 {total / 1e6:.1f} M   ({gib(total * 2):.2f} GiB @fp16)")
    print(f"  参数+梯度+优化器 (Adam {adam_bits}-bit): {gib(state_bytes):.2f} GiB "
          f"[{bytes_per_param:.0f} B/参数  ← 精确值]")
    print(f"  QLoRA 4-bit 基座: {gib(qlora_bytes):.2f} GiB")

    for rank in ranks:
        qv = lora_trainable(a, rank, ("q_proj", "v_proj"))
        allp = lora_trainable(a, rank, PROJ_SHAPES)
        print(f"  LoRA r={rank:<2d}  q,v: {qv / 1e6:7.3f} M ({qv / total * 100:5.3f}%)  "
              f"适配器 {qv * 2 / MIB:7.2f} MiB  |   "
              f"全 7 矩阵: {allp / 1e6:7.3f} M ({allp / total * 100:5.3f}%)  "
              f"适配器 {allp * 2 / MIB:7.2f} MiB")

    if gpu_mib is not None:
        cap = gpu_mib / 1024
        budget = cap * 0.9  # 留 10% 给 CUDA context / 碎片
        need_full = gib(state_bytes + act_gib * GIB)
        adapter_gib = gib(lora_trainable(a, 16, PROJ_SHAPES) * 2)
        need_qlora = gib(qlora_bytes + adapter_gib * GIB + act_gib * GIB)
        print(f"  --- 判定 @ 本机 {gpu_mib} MiB ({cap:.2f} GiB)，可用预算 {budget:.2f} GiB ---")
        print(f"      假设: 优化器 Adam {adam_bits}-bit，激活预留 {act_gib:.1f} GiB "
              f"（激活真实值取决于 batch×seq，此处是假设不是测量）")
        for label, need in (("全参微调", need_full), ("LoRA+4bit 基座", need_qlora)):
            mark = "✅ 放得下" if need <= budget else "❌ 放不下"
            print(f"      {label:<16s} {mark}   需 {need:6.2f} GiB"
                  f"  (余量 {budget - need:+.2f} GiB)")
    return {"repo": repo, "total_m": total / 1e6,
            "state_gib": gib(state_bytes), "qlora_gib": gib(qlora_bytes)}


def main() -> int:
    ap = argparse.ArgumentParser(description="LoRA/QLoRA 显存与参数量速算")
    ap.add_argument("repos", nargs="*", default=None, help="HF repo id（默认对比 0.5B~32B）")
    ap.add_argument("--ranks", default="8,16,32", help="LoRA rank 列表，默认 8,16,32")
    ap.add_argument("--gpu-mib", type=int, default=None, help="本机显存 MiB，附判定")
    ap.add_argument("--adam-bits", type=int, default=32, choices=(8, 16, 32),
                    help="优化器状态位宽，默认 32；8 = bitsandbytes 8-bit Adam")
    ap.add_argument("--act-gib", type=float, default=2.0,
                    help="激活值预留 GiB（显式假设，默认 2.0）")
    args = ap.parse_args()

    ranks = tuple(int(x) for x in args.ranks.split(",") if x.strip())
    repos = args.repos or DEFAULT_REPOS
    out = []
    for repo in repos:
        try:
            out.append(report(repo, ranks=ranks, gpu_mib=args.gpu_mib,
                              adam_bits=args.adam_bits, act_gib=args.act_gib))
        except Exception as exc:  # noqa: BLE001
            print(f"\n[跳过] {repo}: {exc}", file=sys.stderr)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
