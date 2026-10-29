"""Score rally play segments against hand-labeled rallies, replaying cached tracks.

Run the pipeline once on a clip, then edit CONFIG["rallies"] and rerun this; it
rebuilds the trajectory and rallies from tracks.jsonl without inference or rendering.
"""
import argparse
import json
from pathlib import Path

from vantage.audio import hit_onsets, read_audio
from vantage.ball_physics import build_trajectory, detect_bounces
from vantage.config import CONFIG
from vantage.court import load_calibration
from vantage.stats import aggregate
from vantage.tracking_cache import load_cached_tracks


def replay(run_dir, config):
    stats = json.loads((run_dir / 'stats.json').read_text())
    video = stats['video']
    width, height, fps = video['width'], video['height'], video['fps']
    records = load_cached_tracks(run_dir, stats['source'], config, fps, width, height)
    homography = load_calibration(run_dir, width, height, config)
    if homography is None:
        raise ValueError(f'No valid calibration in {run_dir}; run the pipeline on this clip first.')
    samples = build_trajectory(records, homography, width, height, config)
    bounces = detect_bounces(records, samples, homography, width, height, config)
    rate = config['audio']['sample_rate']
    audio = read_audio(stats['input'], rate)
    onsets = None if audio is None else hit_onsets(audio, rate, config)
    result, _, _ = aggregate(records, samples, bounces, fps, width, height, config, onsets)
    return result


def load_labels(path, duration_s):
    data = json.loads(path.read_text())
    rallies = [tuple(r) for r in data['rallies']]
    previous_end = 0.0
    for start, end in rallies:
        if not previous_end <= start < end <= duration_s + 0.05:
            raise ValueError(f'{path}: rallies must be ordered, non-overlapping, and inside the video.')
        previous_end = end
    return rallies


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def score(segments, labels, duration_s, keep_fraction):
    kept = [(s['start_s'], s['end_s']) for s in segments]
    play = sum(end - start for start, end in labels)
    play_kept = sum(overlap(k, label) for k in kept for label in labels)
    downtime = duration_s - play
    downtime_kept = sum(end - start for start, end in kept) - play_kept
    per_rally = [{'start_s': start, 'end_s': end,
                  'kept_fraction': sum(overlap(k, (start, end)) for k in kept) / (end - start)}
                 for start, end in labels]
    return {'labeled_rallies': len(labels),
            'rallies_kept': sum(r['kept_fraction'] >= keep_fraction for r in per_rally),
            'segments': len(kept),
            'segments_without_rally': sum(not any(overlap(k, label) for label in labels) for k in kept),
            'play_s': play, 'play_lost_s': play - play_kept,
            'downtime_s': downtime, 'downtime_kept_s': downtime_kept,
            'per_rally': per_rally}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path, help='Pipeline --output-dir for the clip')
    parser.add_argument('labels', type=Path, help='ml/labels/rallies/<clip>.json')
    parser.add_argument('--keep-fraction', type=float, default=0.9,
                        help='Share of a labeled rally that must be kept to count it as kept')
    args = parser.parse_args()
    result = replay(args.run_dir, CONFIG)
    duration = result['video']['duration_s']
    report = score(result['play_segments'], load_labels(args.labels, duration), duration, args.keep_fraction)
    print(f"Rallies kept (>= {args.keep_fraction:.0%}): {report['rallies_kept']}/{report['labeled_rallies']}")
    print(f"Play lost:      {report['play_lost_s']:6.1f} s of {report['play_s']:.1f} s")
    print(f"Downtime kept:  {report['downtime_kept_s']:6.1f} s of {report['downtime_s']:.1f} s")
    print(f"Segments: {report['segments']} ({report['segments_without_rally']} with no labeled rally)")
    for rally in report['per_rally']:
        print(f"  {rally['start_s']:7.1f}-{rally['end_s']:7.1f} s  kept {rally['kept_fraction']:4.0%}")
    for segment in result['play_segments']:
        print(f"  predicted {segment['start_s']:7.1f}-{segment['end_s']:7.1f} s")


if __name__ == '__main__':
    main()
