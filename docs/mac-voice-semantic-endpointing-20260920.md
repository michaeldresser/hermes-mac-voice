---
title: Semantic endpointing for the Mac voice bridge (Pipecat Smart Turn v3.2)
status: measured, not yet implemented
updated: 2026-09-20
scope: mac gpt-live bridge turn-taking; latency, accuracy, placement
---

# Semantic endpointing — measured facts

Measured on the Mac Studio M3 Ultra natively (not vendor claims). Full study:
`/workspace/mac-voice-semantic-endpointing-bench.md`, raw JSON in `/workspace/smart-turn-bench/`.

## Don't re-litigate: the answers

- **No GPU is needed.** ~8M params, int8 8.7 MB, ~14–17 ms per turn decision on 4 CPU threads,
  plus 4.5 ms for the Whisper featurizer. It runs **once per VAD pause**, not per frame.
- **CoreML/ANE is SLOWER** for this model: 34.7 ms (int8) vs 9.3 ms on 8 CPU threads, and a
  1.5 s session build. Do not use the GPU path.
- **So the macOS Docker hardware-sharing limit does not bind this design** — there is nothing to
  accelerate. The objection only applies to workloads that genuinely need Metal.
- **There is no GPU node in the swarm.** `docker node inspect` reports `GenericResources=null` on
  all 6 nodes. "Run it on the video card system" is not an available option, and a remote hop
  would be worse anyway: 256 KB (mel) / 512 KB (raw) of audio per decision over the network
  against 14 ms of local compute, plus a hard dependency inside the audio path.
- **Recommended placement:** in-process in `bridge.py`, native Mac, CPU, 4 threads.

## Accuracy (900 labelled clips, official test set)

Overall 85.8% (real speech 81.2% n=16, synthetic 85.9%); COMPLETE recall 95.8%,
INCOMPLETE recall 76.6%. Median p: complete 0.984 vs incomplete 0.012.

The number to quote when justifying adoption: today's pure-VAD rule makes *every* ≥900 ms pause
an end-of-turn (100% false-COMPLETE on mid-turn pauses); the model at threshold 0.7 is wrong on
~20.8%. ~4× fewer premature cutoffs, and `SETTLE_MS` can drop 5000 → ~600 ms (~4.4 s faster/turn).

## Traps that cost time here

- **The ONNX output is already a probability.** Applying sigmoid again collapses every score to
  ~0.5 and reads exactly like a broken model. The output tensor is even *named* `logits`.
- **Input is a Whisper log-mel `[1, 80, 800]`**, not raw audio — and it needs Whisper's
  `log_spec.max() - 8.0` dynamic-range clamp. Use `WhisperFeatureExtractor(chunk_length=8)` with
  `padding="max_length", max_length=128000, do_normalize=True` rather than hand-rolling the mel.
- **Never validate this model on macOS `say` audio.** A `say`-based probe scored ~50% (chance)
  while the labelled set's own synthetic clips scored 85.9%. TTS prosody is out of distribution,
  so a low score there means the test is invalid — not that the model is bad.
- Reading only the first row groups of the HF parquet test set over HTTP range requests
  (`fsspec` + `pyarrow.ParquetFile`) samples 900 clips without downloading 3.3 GB.
- **PyAV's `AudioResampler.resample()` returns a list of frames**, and returns a list on the
  final `resample(None)` call too — append per frame, not the list.