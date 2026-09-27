# Could Gemini 3.8 Flash-Lite TTS improve our voice quality?

**Asked by Michael, 2026-09-26.** Short answer: **yes on the quality ceiling, but it is a cloud
model, so it collides with our standing local-first rule** — it cannot be adopted without his
explicit approval — and there is a local-first route to better quality that we have never tried.

---

## 1. What actually exists (launched 2026-09-23, three days ago)

| | `gemini-3.8-flash-tts` | `gemini-3.8-flash-lite-tts` |
|---|---|---|
| Position | flagship creative tier, studio-grade fidelity | cost / latency-optimised sibling |
| Benchmark | **#1** Hume AI Voice Design (71.4); accent modelling 60.8; also #1 Hume Overall Quality Index | **#2** Hume Overall Quality Index; top positions on Voice Arena for JA, pt-BR, VI, MSA, es-MX, HI |
| Languages | 130 | 101 |
| Voices | 2 000+ production voices, generative voice design from a prompt, replication from a 30 s sample (consent-verified) | as above, shared schema |
| Best at (Google's own words) | audiobooks, studio narration, multi-speaker dialogue, heavy vocal acting, dialects | **high-volume production, real-time voice agent cascades, read-aloud features**, everyday single-speaker generation |
| Replaces | new tier | `gemini-3.1-flash-tts-preview` |

Both models share one API schema and prompting structure. Every clip carries a **SynthID
watermark** plus C2PA credentials. Voice replication is gated by verbal consent verification and
is blocked in several regions (UK, EEA, India, Texas, Illinois).

Sources: `blog.google/…/gemini-3-8-text-to-speech/` (announcement),
`ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts` (model doc), Android Authority
(2026-09-24), aichatdaily, texttolab review 2026, dev.to build guide.

## 2. Why it maps onto our two workloads almost exactly

Flash-Lite's stated sweet spot — *read-aloud features* and *real-time voice agent cascades* — is
precisely what we run:

- **chained mode** = read-aloud (assistant reply → speech, sentence by sentence)
- **gpt-live mode** = a real-time voice agent cascade (bridge.py owns turn-taking)

And the quality gap is real: our current voice is **Kokoro-82M** (`af_heart`), an 82-million
parameter model chosen for CPU/Docker practicality. It ranks well among *open-source* models and
is still in the top handful in 2026, but it is not in the same tier as frontier TTS models. It is
also English-only and cannot clone a voice.

## 3. The blocker: it is cloud, and our rule is local-first

Standing preference (recorded, and Michael has enforced it before): **all audio processing stays
on the Mac**; cloud voice modes only with his explicit approval — the cloud `gpt-live` path was
gated for exactly this reason. Gemini TTS means a WAN round trip per utterance.

Three specific consequences:

1. **Latency inside the audio path.** For `gpt-live` duplex conversation this puts a network
   dependency between the user finishing a sentence and hearing the reply. We already fought one
   version of this failure class locally (see `docs/voice-live-bridge-502-20260917.md`); a cloud
   TTS adds a new one that we cannot debug on the Mac.
2. **Permanent watermarking.** SynthID + C2PA on every clip is a property of the audio itself,
   not a setting we can turn off.
3. **Preview status.** The API surface can change under us.

## 4. Integration is not a one-line swap

We got TTS onto the Mac by changing only `tts.openai.base_url`, because Speaches speaks the
OpenAI `/v1/audio/speech` contract. **Google's OpenAI-compatibility layer does not cover audio
output** — `https://generativelanguage.googleapis.com/v1beta/openai/` exposes chat/completions
(including audio *input*, for transcription), embeddings and images. There is **no
`/v1/audio/speech`**. Gemini TTS is reached through `generateContent` with
`response_modalities: ["AUDIO"]`.

So adoption needs one of:

- **Path A — a shim.** A small OpenAI-compatible `/v1/audio/speech` facade in front of Gemini
  `generateContent`, returning WAV. ~1 file, deployed next to Speaches. Keeps the Hermes side
  untouched.
- **Path B — a Hermes command provider.** `tts.providers.gemini: {type: command, command: …}`,
  with `warm_command` / `release_command` if the backend needs preloading. This is the documented
  extension seam and needs no core changes.

One migration trap: **3.8 treats input text as a verbatim transcript.** Prompt-style direction
(`"Say cheerfully: …"`) is now *spoken aloud*; sustained style and speaker labels must move into
`speech_metadata` (GenerateContent) or annotations (Interactions API). Our input is plain
assistant output, which mostly plays to our advantage — but any existing style-in-text steering
must be stripped.

## 5. Cost

Published Gemini TTS pricing at the 3.1 generation: **$1.00 / 1M text-input tokens** and
**$20.00 / 1M audio-output tokens**; audio is metered at 25 tokens per second, i.e. ≈ **$0.037
per minute of speech** (Batch API halves both). For scale: OpenAI `gpt-4o-mini-tts` ≈ $0.015/min,
ElevenLabs Flash ≈ $0.05/1k chars.

**Do not assume those rates carry over to 3.8** — pricing for the new models was not confirmed in
the sources reviewed. Verify on Google's pricing page before anyone commits to anything.

## 6. The local-first option we have not tried (arguably the better answer)

Kokoro was selected on 2026-09-14 for CPU/Docker practicality, **not as the quality ceiling**
(`docs/mac-voice-engine-research-selfexecuted.md`). Larger open models have shipped since:

| Model | Params | Licence | Notes |
|---|---|---|---|
| Qwen3-TTS | 1.7B | Apache 2.0 | natural-language voice direction, ~10 languages, zero-shot cloning from ~3 s |
| CosyVoice 2/3 | 0.5B | Apache 2.0 | zero-shot cloning, 9 languages + 18 dialects |
| Zonos / Zonos2 | 1.6B / 8B | Apache 2.0 | high quality, GPU-oriented |
| Higgs Audio V3 | — | — | 100+ languages, published error rates |
| Breeze TTS 2 | — | — | 12 GB VRAM floor; vendor claims it beats ElevenLabs v3 |

**Hardware caveat that changes the calculus:** Docker on macOS is CPU-only, which is why we
chose a tiny model. But a *native* macOS process can use **MPS**, so a 1.7B model on the M3 Ultra
via MPS/MLX is plausible **without audio ever leaving the Mac**. Kokoro's own documentation notes
MPS support when run via UV rather than Docker.

Treat all of the above as vendor/blog claims — none of it has been measured on our hardware.
It is a candidate list to benchmark, not evidence.

## 7. Recommendation

1. **Do not swap blind.** Build an A/B harness first: ~20 representative utterances
   (short reply, long explanation, numbers/units, code-adjacent text, the wake word "DarkAgent")
   rendered by (a) current Kokoro `af_heart`, (b) one larger local model on MPS, and
   (c) Gemini 3.8 Flash-Lite — then *listen*. Naturalness is the one thing benchmarks cannot
   settle for us.
2. **Keep Kokoro as the default.** Add the alternative as an opt-in provider (Path B), so quality
   can be raised per session without a code change and without making the local-first guarantee
   conditional.
3. **The cloud trade-off is Michael's call, explicitly.** It is his stated rule; it should not be
   inferred from a benchmark table.

## 8. Open questions to verify before any commitment

- [ ] Gemini 3.8 Flash / Flash-Lite pricing and effective per-minute cost.
- [ ] Flash-Lite **streaming** support and real end-to-end latency from our network
      (streaming exists from 3.1 onward; confirm for Flash-Lite specifically).
- [ ] 3.8 output sample format (3.1 was 24 kHz, 16-bit, mono PCM).
- [ ] Whether Google adds `/v1/audio/speech` to the OpenAI-compat layer — that would reduce
      adoption to the one-line `base_url` swap we used for Speaches.
- [ ] Real naturalness/WER on **our** text, not benchmark prose.
- [ ] Local: does a 1.7B TTS model hit real-time on MPS on the M3 Ultra, and at what quality vs
      Kokoro?

## 9. Sources

- https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-8-text-to-speech/
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts
- https://ai.google.dev/gemini-api/docs/openai  (OpenAI-compat surface — no audio output)
- https://ai.google.dev/gemini-api/docs/speech-generation  (TTS via generateContent)
- https://androidauthority.com/gemini-3-8-flash-text-to-speech-rolling-out-3714915
- https://aichatdaily.com/ai-models/google-deepmind-ships-gemini-3-8-tts-tops
- https://texttolab.com/blog/gemini-tts-review
- Open-source TTS surveys: bentoml, pinggy.io, texttolab, offlinetts, ocdevel (2026)
