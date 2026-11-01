# Reality-check: common LoRA tutorials vs THIS machine

The user brings Chinese LoRA/fine-tuning tutorials (公众号 infographics, 博客长图).
Most are **correct on the theory and wrong for this box**. Audit them against this
checklist instead of re-deriving it each time.

## Source reviewed 2026-10-15

「微调与部署大语言模型：开发人员指南 — 从需求分析到API调用全流程实践」,
Bojun's Blog © 2025 (公众号「赋能个人创作者」). 822×6990 px infographic, 6 sections.

### Correct — credit it, use it as revision material

| Claim in the article | Verdict |
|---|---|
| LoRA = Microsoft Research, 2021, low-rank adaptation | ✅ |
| `h = W0x + ΔWx ≈ W0x + BAx`; A∈R^{d×r}, B∈R^{r×k} | ✅ |
| Trainable params `d·r + r·k` instead of `d·k` | ✅ |
| W0 frozen, only A/B trained | ✅ |
| Merge `W = W0 + BA` ⇒ **no extra inference latency** | ✅ |
| Second use: keep one base + swap adapters per task | ✅ |
| Original paper applies it to Self-Attention weights | ✅ |
| Frameworks: LLaMA-Factory / HF Trainer / DeepSpeed | ✅ |
| **Admits its own demo overfits**: tiny dataset + aggressive params ⇒ the model only repeats one pattern and **loses general ability** | ✅ — the single most valuable line in it |

### Wrong or absent — do NOT follow these parts

| Gap | Why it matters HERE |
|---|---|
| **No QLoRA anywhere** | The whole "cheap GPU" story is missing. 4-bit base + LoRA is the only way an 8 GB card trains 7B. The article jumps straight to renting a GPU. |
| **Assumes you rent a card** (AutoDL, 4090 instance) | Unnecessary spend. Measured on this box: Qwen2.5-7B QLoRA ≈ **5.70 GiB**, card has **8151 MiB** → fits, locally, free. |
| **Hyperparameters listed by NAME only, no values** | `r`, `alpha`, `lr` are exactly the three numbers that decide whether the run works. Naming them is not teaching them. |
| **RLHF presented as core tech** | Noise for a beginner. SFT + LoRA is the whole game at this stage. |
| **Base/model mismatch** | Trains chit-chat ("神奇海螺") into `deepseek-coder-1.3b-instruct` — a **code** model. Domain mismatch is itself a cause of bad output, independent of data size. Also the text says 1.3b in one place and "1.5B 蒸馏版" in another, so you can download the wrong model. |
| **"Must merge before deploying"** | Overstated and self-contradictory (it had just praised adapter swapping). Merge is the *easiest* path, not the only one: vLLM `--enable-lora --lora-modules`, or PEFT loading an adapter, both work unmerged. |
| **"Python 3.10, higher may be incompatible"** | Stale. LLaMA-Factory supports 3.11/3.12 now. |
| **No hardware footgun warning** | On Blackwell (compute_cap 12.0 / sm_120, RTX 5060 Laptop) `pip install torch` **must** be a cu128+ wheel or it will not run. No tutorial mentions this. |

## The numbers the tutorials always omit — supply these instead

LoRA-SFT defaults that actually work (LLaMA-Factory-flavoured):

| Param | Value | Note |
|---|---|---|
| `lora_rank` (r) | 8–16 | 8 is the usual start |
| `lora_alpha` | 16–32 | convention `alpha = 2r`; alpha/r is the real scaling |
| `learning_rate` | 1e-4 – 2e-4 | **~10× higher than full fine-tuning**; 1e-5 basically trains nothing |
| `num_train_epochs` | 2–3 | more ⇒ memorisation on small data |
| `cutoff_len` | 1024–2048 | match your data, not the model max |
| `per_device_batch_size` × `gradient_accumulation_steps` | 1 × 8–16 | effective batch ~8–16 |
| `compute_type` | bf16 | Blackwell: bf16 over fp16 |
| `lr_scheduler_type` | cosine | |
| `target_modules` | all linear | modern practice: q/k/v/o **and** gate/up/down — not attention only |
| dataset size floor | **several hundred to a few thousand** | format consistency matters more than raw count |

## How to answer when the user brings one of these

1. Split the verdict in two: **theory (usually right)** vs **practical route (usually wrong here)**.
2. Say plainly whether they need to rent anything — for ≤7B LoRA they don't.
3. Fill in the missing hyperparameters rather than praising the article.
4. If the article admits a failure (overfitting, "model only repeats itself"), **quote it** — a real flip-out teaches more than a success story.
5. Locate it against the user's actual priorities; a LoRA exercise must not displace the 嵌入式 mainline or the CET-6 / 省二级C / 工创赛 three-line constraint.
