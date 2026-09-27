# Semantic endpointing (Pipecat Smart Turn v3.2) — measured performance study

**Date:** 2026-09-20 · **Host:** Mac Studio M3 Ultra (28 CPU cores, 96 GB unified), macOS, natively
**Measured by:** DarkAgent, on the live Mac (not vendor claims)
**Artifacts:** `/workspace/smart-turn-bench/*.json`, harnesses in `~/smart-turn-bench/` on the Mac
**Status:** decision gate — NOT yet implemented

## Why this was asked

The gpt-live bridge currently decides "user finished talking" with energy VAD only:
`SILENCE_MS=900` closes an utterance, `SETTLE_MS=5000` of quiet before it delegates to Hermes.
That causes both complaints: cuts you off mid-sentence, and makes you wait ~5 s before an answer.
Semantic endpointing replaces the fixed rule with a small model that listens to prosody.

The open question was whether it needs GPU acceleration — because Docker on macOS cannot reach
Metal, so "in a container" appeared to mean "CPU only".

## Headline: the workload is CPU-class, and the GPU path is *slower*

Smart Turn v3.2 is Whisper-Tiny backbone + linear classifier, ~8M params, int8 quantised to 8.7 MB.
Input is a Whisper log-mel `[1, 80, 800]` (8 s @16 kHz). It runs **once per VAD pause**, not per
audio frame.

Measured on the M3 Ultra, 60 timed iterations each, median (ms):

| Config | int8 (8.7 MB) | fp32 (32.4 MB) |
|---|---|---|
| CPU 1 thread | 33.6 | 74.7 |
| CPU 2 threads | 19.5 | 40.4 |
| CPU 4 threads | **12.5** | 23.5 |
| CPU 8 threads | **9.3** | 14.7 |
| **CoreML (GPU + Neural Engine)** | **34.7** | 43.7 |

Plus the featurizer (official `WhisperFeatureExtractor`): **4.5 ms**. Session build **25 ms**
(CPU) vs **1.5 s** (CoreML). Peak RSS of the whole bench process 222 MB, but that includes
transformers + pyarrow; the deployment needs only onnxruntime + numpy + a vendored mel filterbank.

**Conclusion: total cost per turn decision ≈ 14–17 ms on 4 threads.** The CoreML/ANE path is
~2.4× *slower* than plain CPU for a model this small (partition/copy overhead dominates), so
there is nothing to gain from the GPU — and the macOS Docker hardware-sharing limit therefore
does not bind this design at all.

## Accuracy: validated on the official labelled test set (not a guess)

900 clips from `pipecat-ai/smart-turn-data-v3-test` (shard 0, row groups 0–8), scored through the
exact pipeline above:

| Group | Accuracy | n |
|---|---|---|
| all | 85.8% | 900 |
| real human speech | 81.2% | 16 |
| synthetic (TTS) | 85.9% | 884 |
| label = COMPLETE | 95.8% | 429 |
| label = INCOMPLETE | 76.6% | 471 |

Median output: complete 0.984 vs incomplete 0.012 — the classes separate cleanly, confirming the
pipeline is wired correctly. (The model outputs a **probability directly**; do not sigmoid it
again — doing so collapses everything to ~0.5 and looks like a broken model.)

### Threshold sweep — the operating point is the real decision

| threshold | accuracy | false-COMPLETE (cuts you off) | false-INCOMPLETE (you wait) |
|---|---|---|---|
| 0.50 | 85.8% | 23.4% | 4.2% |
| 0.70 | 86.1% | 20.8% | 6.3% |
| 0.80 | 86.3% | 18.7% | 8.2% |

**The comparison that matters is against the status quo, not against perfection.** Today's
pure-VAD rule treats *every* ≥900 ms pause as end-of-turn — a 100% false-COMPLETE rate on
mid-turn pauses. At threshold 0.7 the model is wrong on ~21% of them: roughly a **4× reduction in
premature cutoffs**. It is a large improvement, not a cure.

## Placement analysis

| Option | Verdict |
|---|---|
| **Native in the bridge process (Mac, CPU)** | **Recommended.** ~14 ms/decision, no new network hop, no new failure mode, no GPU needed. |
| Container on the Mac (CPU only) | Viable — no Metal needed — but the bridge is native Python already; a container only adds a hop and a second thing to supervise. |
| Remote "video card system" | **No.** There is no GPU node in the fleet (`docker node inspect` → `GenericResources=null` on all 6 nodes). And each decision would ship the audio to another host — 512 KB as raw float32, or 256 KB as mel — versus 14 ms of local compute. Strictly worse, and it puts a hard network dependency inside the audio path. |
| CoreML / ANE on the Mac | Slower than CPU (34.7 vs 9.3 ms) and a 1.5 s session build. Not worth it. |

## What adoption would actually buy

- Turn latency: `SETTLE_MS` 5000 → ~600 ms + 14 ms decision ≈ **~4.4 s faster per turn**.
- Cutoffs: ~4× fewer premature end-of-turn decisions on mid-sentence pauses.

## Implementation notes (if adopted)

- Run in-process in `~/gpt-live-bridge/bridge.py`; call it **only during a VAD pause** (as the
  reference does), on the last ≤8 s.
- Vendor the Whisper mel filterbank as a `.npy` to drop the `transformers` dependency; the
  featurizer itself is 4.5 ms.
- Use `intra_op_num_threads=4` (12.5 ms) — 8 threads buys 3 ms and steals more from the bridge loop.
- Keep the existing VAD as the trigger and the safety net (`turn_completion_max_silence`, e.g. 2 s,
  so a classifier that never fires cannot hang a turn forever).
- Threshold ~0.7 as the starting point; it is a UX knob, not a correctness knob.

## Open items

- Only 16 of the 900 sampled clips were real human speech; a real-speech-focused sample from the
  other shards would firm up the accuracy split.
- macOS `say` TTS is a poor stand-in for human prosody: a quick `say`-based probe scored ~50%,
  while the dataset's own synthetic clips scored 85.9%. Do not validate this model on `say` audio.