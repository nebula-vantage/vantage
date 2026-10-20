"""Evaluate the ball tracker against saved raw detections without rerunning YOLO."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ball_tracker import BallTracker
from config import CONFIG
from records import Detection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path('output/ball-diagnostic'))
    parser.add_argument('--output-dir', type=Path, default=Path('output/ball-motion-replay'))
    args = parser.parse_args()
    if args.source_dir.resolve() == args.output_dir.resolve():
        parser.error('Choose a different output directory to preserve source observations.')
    source_summary = json.loads((args.source_dir / 'summary.json').read_text())
    tracker = BallTracker(CONFIG, source_summary['width'], source_summary['height'])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames = raw_frames = previous_frames = selected_frames = 0
    ids = set()
    with (args.source_dir / 'frames.jsonl').open() as source, (args.output_dir / 'frames.jsonl').open('w') as out:
        for line in source:
            row = json.loads(line)
            candidates = [Detection(tuple(b['box']), b['confidence'], None, CONFIG['model']['classes']['ball'])
                          for b in row['raw']]
            ball = tracker.select(candidates, row['time_s'])
            out.write(json.dumps({'frame': row['frame'], 'time_s': row['time_s'], 'raw': row['raw'],
                                  'legacy': row['selected'], 'selected': asdict(ball) if ball else None}) + '\n')
            frames += 1
            raw_frames += bool(candidates)
            previous_frames += row['selected'] is not None
            selected_frames += ball is not None
            if ball:
                ids.add(ball.track_id)
    summary = {'frames': frames, 'raw_candidate_frames': raw_frames,
               'legacy_selected_frames': previous_frames, 'motion_selected_frames': selected_frames,
               'motion_track_count': len(ids), 'config': CONFIG,
               'source_dir': str(args.source_dir.resolve()),
               'method': 'Replay of saved raw detections; no new inference. Candidate coverage is not accuracy.'}
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'config'}, indent=2))


if __name__ == '__main__':
    main()
