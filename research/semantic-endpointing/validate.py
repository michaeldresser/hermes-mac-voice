#!/usr/bin/env python3
"""Validate Smart Turn v3.2 on the official labelled test set (real human speech).

Reads only the first row group(s) of one parquet shard over HTTP range requests, decodes the
audio, and scores it through the SAME featurizer + int8 model we would deploy. Reports accuracy
overall and split by the dataset's own flags (synthetic / midfiller / endfiller), so we can tell
a real accuracy number from a broken integration.
"""
import io, os, sys, json
import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

os.chdir(os.path.expanduser("~/smart-turn-bench"))
SR, NS = 16000, 8 * 16000
URL = ("https://huggingface.co/datasets/pipecat-ai/smart-turn-data-v3-test/resolve/main/"
       "data/train-00000-of-00008.parquet")

FE = WhisperFeatureExtractor(chunk_length=8)
so = ort.SessionOptions()
so.intra_op_num_threads = 4
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
SESS = ort.InferenceSession("models/smart-turn-v3.2-cpu.onnx", so, providers=["CPUExecutionProvider"])


def decode(raw):
    """bytes -> float32 mono 16 kHz."""
    import av
    with av.open(io.BytesIO(raw)) as c:
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
        chunks = []
        for fr in c.decode(st):
            for r in rs.resample(fr):
                chunks.append(r.to_ndarray().reshape(-1))
        for r in rs.resample(None):
            chunks.append(r.to_ndarray().reshape(-1))
        a = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return a.astype(np.float32) / 32768.0


def p_complete(audio):
    a = audio[-NS:] if len(audio) > NS else audio
    f = FE(a, sampling_rate=SR, return_tensors="np", padding="max_length",
           max_length=NS, truncation=True, do_normalize=True).input_features.squeeze(0)[None].astype(np.float32)
    return float(SESS.run(None, {"input_features": f})[0][0][0])


def main(n_groups=2):
    import fsspec, pyarrow.parquet as pq
    fs = fsspec.filesystem("https")
    print(f"opening {URL.rsplit('/',1)[-1]} over HTTP range reads ...")
    f = fs.open(URL)
    pf = pq.ParquetFile(f)
    print(f"rows={pf.metadata.num_rows} row_groups={pf.metadata.num_row_groups}")

    rows = []
    for g in range(min(n_groups, pf.metadata.num_row_groups)):
        t = pf.read_row_group(g)
        d = t.to_pylist()
        rows.extend(d)
        print(f"  read row_group {g}: {len(d)} rows")
    print(f"scoring {len(rows)} clips ...\n")

    res = []
    for i, r in enumerate(rows):
        try:
            a = decode(r["audio"]["bytes"])
            p = p_complete(a)
        except Exception as e:
            print(f"  row {i} decode/infer failed: {e}")
            continue
        res.append({"label": bool(r["endpoint_bool"]), "p": p, "pred": p >= 0.5,
                    "synthetic": bool(r.get("synthetic", False)),
                    "midfiller": bool(r.get("midfiller", False)),
                    "endfiller": bool(r.get("endfiller", False)),
                    "dur_s": round(len(a) / SR, 2), "lang": r.get("language")})

    def acc(sel):
        s = [x for x in res if sel(x)]
        if not s:
            return None, 0
        return sum(x["pred"] == x["label"] for x in s) / len(s), len(s)

    print(f"\nTOTAL clips scored: {len(res)}")
    for name, sel in [
        ("all", lambda x: True),
        ("real human speech", lambda x: not x["synthetic"]),
        ("synthetic (TTS)", lambda x: x["synthetic"]),
        ("real & midfiller", lambda x: not x["synthetic"] and x["midfiller"]),
        ("real & endfiller", lambda x: not x["synthetic"] and x["endfiller"]),
        ("label=COMPLETE", lambda x: x["label"]),
        ("label=INCOMPLETE", lambda x: not x["label"]),
    ]:
        a, n = acc(sel)
        if a is None:
            print(f"  {name:24s} (none)")
        else:
            print(f"  {name:24s} acc={a*100:5.1f}%  n={n}")

    # Threshold sweep: a false COMPLETE cuts the user off mid-sentence (the current complaint);
    # a false INCOMPLETE just makes them wait. Choose the operating point deliberately.
    print("\nthreshold sweep  (FC = said done while still talking; FI = held a finished turn)")
    print(f"{'thr':>5} {'acc':>7} {'FC rate':>9} {'FI rate':>9}")
    for thr in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        pred = lambda x: x["p"] >= thr
        n = len(res)
        correct = sum(pred(x) == x["label"] for x in res)
        fc = sum(1 for x in res if pred(x) and not x["label"]) / max(sum(1 for x in res if not x["label"]), 1)
        fi = sum(1 for x in res if not pred(x) and x["label"]) / max(sum(1 for x in res if x["label"]), 1)
        print(f"{thr:5.2f} {correct/n*100:6.1f}% {fc*100:8.1f}% {fi*100:8.1f}%")

    # balance check: are COMPLETE and INCOMPLETE both represented?
    nc = sum(1 for x in res if x["label"]); ni = len(res) - nc
    print(f"\nlabel balance: complete={nc} incomplete={ni}")
    print(f"median p: complete={np.median([x['p'] for x in res if x['label']]):.3f} "
          f"incomplete={np.median([x['p'] for x in res if not x['label']]):.3f}")
    json.dump(res, open("validation-results.json", "w"), indent=2)
    print("wrote validation-results.json")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)