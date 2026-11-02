"""Generate paddle-hit onset parity fixtures for the Swift port (VantageKit tests).

Runs the desktop band_levels and hit_onsets on 16-bit mono samples and records the per-hop
band levels and onsets the Swift HitOnsetDetector must reproduce. Samples are either a
synthetic recording (pops in court noise, built to exercise each rule) or a window of a
video's audio track, decoded exactly as the pipeline decodes it.

    uv run python tools/coreml/make_hit_fixtures.py --synthetic 16000 \
        ios/VantageKit/Tests/VantageKitTests/Fixtures/hits-synthetic-16k.json
    uv run python tools/coreml/make_hit_fixtures.py --video input/court1-a.mov --start 30 --seconds 3 \
        ios/VantageKit/Tests/VantageKitTests/Fixtures/hits-court1-a.json
"""
import argparse
import base64
import json
from pathlib import Path

import numpy as np

from vantage.audio import band_levels, hit_onsets, read_audio
from vantage.config import CONFIG


def swift_config():
    """Python settings under the Swift HitOnsetConfig property names."""
    a = CONFIG["audio"]
    return {
        "sampleRate": a["sample_rate"],
        "hopSeconds": a["hop_s"],
        "bandLowHz": a["band_low_hz"],
        "bandHighHz": a["band_high_hz"],
        "riseDecibels": a["rise_db"],
        "minIntervalSeconds": a["min_interval_s"],
    }


def synthetic_pcm(rate, seconds=3.0, seed=0):
    """Court noise with pops chosen to exercise each rule; int16 like a decoded track."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(0, 0.01, int(seconds * rate))

    def pop(time_s, amplitude):
        start, length = int(time_s * rate), int(0.01 * rate)
        decay = np.exp(-np.arange(length) / (0.0025 * rate))
        signal[start:start + length] += rng.normal(0, amplitude, length) * decay

    pop(0.30, 0.6)  # clean hit
    pop(0.80, 0.6)  # hit, then an echo 80 ms later that must count once
    pop(0.88, 0.4)
    pop(1.30, 0.05)  # faint pop near the rise threshold
    pop(1.7025, 0.6)  # starts mid-hop, so the rise spreads over two hops
    pop(1.950, 0.12)  # a soft rise then a bigger one in the next hop: one hit, at the peak
    pop(1.955, 1.0)
    pop(2.20, 0.6)  # two hits 150 ms apart: the second is inside min_interval_s
    pop(2.35, 0.6)
    pop(2.70, 3.0)  # clipped at full scale
    hum = np.arange(len(signal)) >= int(1.0 * rate)  # sudden 200 Hz hum: below the band
    signal += hum * 0.3 * np.sin(2 * np.pi * 200 * np.arange(len(signal)) / rate)
    return np.clip(np.round(signal * 32768), -32768, 32767).astype(np.int16)


def build_fixture(pcm, rate, name):
    samples = pcm.astype(np.float32) / 32768  # as vantage.audio.read_audio returns them
    hop, levels = band_levels(samples, rate, CONFIG)
    onsets = hit_onsets(samples, rate, CONFIG)
    return {"name": name, "rate": rate, "config": swift_config(), "hop": hop,
            "summary": {"seconds": len(pcm) / rate, "hops": len(levels), "onsets": len(onsets)},
            "onsets": [float(t) for t in onsets],
            # float32 in Python; Swift computes in double, so tests compare with a tolerance.
            "levels": [round(float(level), 4) for level in levels],
            "pcm_s16le_base64": base64.b64encode(pcm.astype("<i2").tobytes()).decode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", type=int, metavar="RATE", help="synthetic pops at this sample rate")
    source.add_argument("--video", type=Path, help="video whose audio track to sample")
    parser.add_argument("--start", type=float, default=0.0, help="window start in seconds (--video)")
    parser.add_argument("--seconds", type=float, default=3.0, help="window length in seconds (--video)")
    parser.add_argument("output", type=Path, help="fixture JSON path")
    args = parser.parse_args()
    if args.synthetic:
        rate, pcm, name = args.synthetic, synthetic_pcm(args.synthetic), f"synthetic-{args.synthetic}"
    else:
        rate = CONFIG["audio"]["sample_rate"]
        samples = read_audio(args.video, rate)
        if samples is None:
            parser.error(f"{args.video} has no audio track")
        window = samples[int(args.start * rate):int((args.start + args.seconds) * rate)]
        pcm, name = np.round(window * 32768).astype(np.int16), args.video.stem
    fixture = build_fixture(pcm, rate, name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, separators=(",", ":")) + "\n")
    print(json.dumps({**fixture["summary"], "onset_times": fixture["onsets"]}))


if __name__ == "__main__":
    main()
