"""Compare raw YOLO predictions with independent ball motion tracking."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import CONFIG
from detector import Detector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('assets/videoplayback.mp4'))
    parser.add_argument('--output-dir', type=Path, default=Path('output/ball-motion-diagnostic'))
    parser.add_argument('--max-frames', type=int, default=0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.input))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open {args.input}')
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = (int(cap.get(p)) for p in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
    config = deepcopy(CONFIG)
    detector = Detector(config, width, height, fps, args.output_dir)
    counts = Counter()
    examples = {key: [] for key in ('raw_dropped', 'selected', 'no_raw')}
    last_example = {key: -1000 for key in examples}
    started = time.monotonic()
    previous = started
    with (args.output_dir / 'frames.jsonl').open('w') as out:
        index = 0
        while not args.max_frames or index < args.max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            record = detector.process(frame, index, index / fps)
            raw = [{'box': b.box, 'confidence': b.confidence} for b in detector.raw_balls]
            counts['frames'] += 1
            counts['raw_ball_boxes'] += len(raw)
            counts['raw_ball_frames'] += bool(raw)
            counts['selected_ball_frames'] += record.ball is not None
            counts['raw_but_no_selected_frames'] += bool(raw) and record.ball is None
            out.write(json.dumps({'frame': index, 'time_s': index / fps, 'raw': raw,
                                  'selected': record.to_dict()['ball']}) + '\n')
            category = 'raw_dropped' if raw and record.ball is None else 'selected' if record.ball else 'no_raw' if not raw else None
            if category and len(examples[category]) < 12 and index - last_example[category] >= fps * 2:
                display = frame.copy()
                for b in raw:
                    x1, y1, x2, y2 = map(round, b['box'])
                    cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 255), 1)
                    cv2.putText(display, f"{b['confidence']:.2f}", (x1, max(32, y1-3)), cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 255), 1)
                cv2.rectangle(display, (0, 0), (width, 24), (0, 0, 0), -1)
                cv2.putText(display, f'{category} frame {index} {index/fps:.2f}s', (5, 17), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
                path = args.output_dir / f'{category}-{index:05d}.jpg'
                if not cv2.imwrite(str(path), display):
                    raise RuntimeError(f'Cannot write {path}')
                examples[category].append(str(path))
                last_example[category] = index
            index += 1
            now = time.monotonic()
            if now - previous > 20:
                print(json.dumps(dict(counts), sort_keys=True), flush=True)
                previous = now
    cap.release()
    if not counts['frames']:
        raise RuntimeError('No frames decoded')
    summary = {'input': str(args.input.resolve()), 'width': width, 'height': height,
               'fps': fps, 'config': config, 'counts': dict(counts),
               'coverage': {key: counts[key] / counts['frames'] for key in (
                   'raw_ball_frames', 'selected_ball_frames')},
               'elapsed_s': time.monotonic() - started, 'examples': examples,
               'note': 'Coverage measures model candidates, not ground-truth recall. Raw ball candidates bypass player ByteTrack and enter the independent motion tracker.'}
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: summary[key] for key in ('counts', 'coverage', 'elapsed_s')}, indent=2))


if __name__ == '__main__':
    main()
