"""Isolated full-frame vs full-frame + native-resolution crop experiment.

Uses the unchanged desktop model/config/tracker read-only. Writes only to a new
report folder; neither desktop inference nor the iPhone prototype is replaced.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[2]
from vantage.ball_tracker import BallTracker
from vantage.config import CONFIG
from vantage.records import Detection


def crop_box(center, width, height, side):
    """Clamp a native-pixel square to the image, preserving its size at edges."""
    side = min(side, width, height)
    x = min(max(0, round(center[0] - side / 2)), width - side)
    y = min(max(0, round(center[1] - side / 2)), height - side)
    return (x, y, x + side, y + side)


def scan_boxes(width, height, side):
    side = min(side, width, height)
    def starts(length):
        count = max(1, math.ceil((length-side)/(side*0.75)))
        return sorted(set(round(i*(length-side)/count) for i in range(count+1)))
    return [(x, y, x+side, y+side) for y in starts(height) for x in starts(width)]


def select_crop(tracker, time_s, index, width, height, side):
    # Periodically scan even when locked, so clutter cannot monopolize the crop.
    if tracker.last and time_s - tracker.last[0] <= CONFIG['detection']['candidate_reset_s'] and index % 10:
        elapsed = time_s-tracker.last[0]
        center = tuple(p+v*elapsed for p,v in zip(tracker.last[1].center, tracker.velocity))
        return crop_box(center, width, height, side), 'predicted'
    boxes = scan_boxes(width, height, side)
    # Caller advances scan_index only for scans, including during a locked track.
    return boxes, 'scan'


def restore_crop(detections, region, width, height):
    x, y, right, bottom = region
    restored = []
    for d in detections:
        a,b,c,e = d.box
        # Reject partial detections on internal crop edges; retain image edges.
        if ((x > 0 and a <= 2) or (y > 0 and b <= 2) or
            (right < width and c >= right-x-2) or (bottom < height and e >= bottom-y-2)):
            continue
        restored.append(replace(d, box=(a+x,b+y,c+x,e+y)))
    return restored


def merge_candidates(full, cropped):
    from compare import iou
    kept = []
    for d in sorted([*full, *cropped], key=lambda d: d.confidence, reverse=True):
        if not any(iou(d.box, other.box) >= 0.4 for other in kept):
            kept.append(d)
    return kept


def evaluate_labels(records, labels, radius):
    """Optional independently labelled ball centers; null means no visible ball.

    Labels: {"123": [x, y], "124": null}. Unlabelled frames are excluded.
    A wrong visible-ball position counts both as a miss and a false detection.
    """
    result = {name: dict(labelled_frames=0, visible_frames=0, correct=0, missed=0, false_detection=0)
              for name in ('baseline', 'cropped')}
    for record in records:
        key = str(record['frame_index'])
        if key not in labels:
            continue
        truth = labels[key]
        for name, totals in result.items():
            totals['labelled_frames'] += 1
            detection = record[name]
            center = None if detection is None else ((detection['box'][0]+detection['box'][2])/2,
                                                     (detection['box'][1]+detection['box'][3])/2)
            correct = truth is not None and center is not None and math.dist(truth, center) <= radius
            totals['visible_frames'] += truth is not None
            totals['correct'] += correct
            totals['missed'] += truth is not None and not correct
            totals['false_detection'] += center is not None and not correct
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--crop-side', type=int, default=960, help='Square side in ORIGINAL video pixels')
    parser.add_argument('--max-frames', type=int, default=0, help='0 processes the entire clip')
    parser.add_argument('--labels', type=Path)
    parser.add_argument('--label-radius', type=float, default=15, help='Native pixel tolerance for labelled centers')
    args = parser.parse_args()
    if args.crop_side <= 0 or args.max_frames < 0 or not args.video.is_file() or args.label_radius <= 0:
        parser.error('Existing video, positive crop size/tolerance, and nonnegative frame limit required')
    labels = None
    if args.labels:
        labels = json.loads(args.labels.read_text())
        if not isinstance(labels, dict) or any(
            not str(k).isdigit() or (v is not None and
            (not isinstance(v, list) or len(v) != 2 or
             not all(isinstance(n, (float,int)) and math.isfinite(n) for n in v)))
            for k,v in labels.items()):
            parser.error('Labels must map frame-index strings to finite [x,y] centers or null')
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    cache = ROOT / '.cache/ultralytics'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR', str(cache))
    import cv2
    import numpy as np
    from ultralytics import YOLO
    weights = ROOT / CONFIG['model']['path']
    if not weights.is_file():
        raise RuntimeError('Local desktop weights are required; no automatic downloads')
    model = YOLO(str(weights))
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps <= 0:
        raise RuntimeError('Invalid video FPS')
    cfg = CONFIG['detection']
    def detect(frame):
        # Keep all desktop classes through postprocessing for a fair baseline.
        result = model.predict(frame, imgsz=cfg['image_size'], conf=cfg['confidence'],
            iou=cfg['iou'], classes=list(CONFIG['model']['classes'].values()),
            max_det=cfg['max_detections'], device=cfg['device'], verbose=False)[0]
        return [Detection(tuple(box), float(score), None, int(cls))
                for box,score,cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist())
                if int(cls) == CONFIG['model']['classes']['ball']]
    records, writer, trackers = [], None, None
    scan_index, previous_time = 0, -1.0
    timestamp_fallbacks = 0
    def draw(frame, detection, title, region=None):
        view = frame.copy()
        if region:
            x,y,r,b = region
            cv2.rectangle(view, (x,y), (r,b), (255,180,0), 2)
        if detection:
            x,y,r,b = map(round, detection.box)
            cv2.rectangle(view, (x,y), (r,b), (0,255,255), 3)
            cv2.circle(view, tuple(map(round,detection.center)), 12, (0,255,255), 2)
        view = cv2.resize(view, (960, round(view.shape[0]*960/view.shape[1])))
        cv2.rectangle(view, (0,0), (960,32), (0,0,0), -1)
        cv2.putText(view, title, (10,22), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
        return view
    try:
        with (args.output/'frames.jsonl').open('w') as log:
            while args.max_frames == 0 or len(records) < args.max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                index = len(records)
                height, width = frame.shape[:2]
                if trackers is None:
                    trackers = [BallTracker(CONFIG,width,height), BallTracker(CONFIG,width,height)]
                timestamp = cap.get(cv2.CAP_PROP_POS_MSEC)/1000
                fallback = not math.isfinite(timestamp) or timestamp <= previous_time
                if fallback:
                    timestamp = max(index/fps, previous_time+1/fps)
                    timestamp_fallbacks += 1
                previous_time = timestamp
                start = time.perf_counter()
                full = detect(frame)
                baseline = trackers[0].select(full,timestamp)
                full_ms = (time.perf_counter()-start)*1000
                start = time.perf_counter()
                region, mode = select_crop(trackers[1],timestamp,index,width,height,args.crop_side)
                if mode == 'scan':
                    region = region[scan_index % len(region)]
                    scan_index += 1
                x,y,r,b = region
                crop = restore_crop(detect(frame[y:b,x:r]), region,width,height)
                merged = merge_candidates(full,crop)
                selected = trackers[1].select(merged,timestamp)
                extra_ms = (time.perf_counter()-start)*1000
                record = dict(frame_index=index,time_s=timestamp,timestamp_fallback=fallback,
                    crop_region=region,crop_mode=mode,full_ms=full_ms,extra_crop_ms=extra_ms,
                    full_candidates=[asdict(d) for d in full],crop_candidates=[asdict(d) for d in crop],
                    baseline=asdict(baseline) if baseline else None,cropped=asdict(selected) if selected else None)
                records.append(record)
                log.write(json.dumps(record)+'\n')
                comparison = np.concatenate([draw(frame,baseline,f'Full frame | frame {index}'),
                    draw(frame,selected,f'Full frame + crop ({mode}) | frame {index}',region)],axis=1)
                if writer is None:
                    # Codec expects even dimensions.
                    video_height = comparison.shape[0]//2*2
                    writer = cv2.VideoWriter(str(args.output/'comparison.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(1920,video_height))
                    if not writer.isOpened():
                        raise RuntimeError('Cannot open comparison video writer')
                writer.write(comparison[:video_height])
                if index % 30 == 0:
                    print(f'{index+1} frames processed',flush=True)
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    if not records:
        raise RuntimeError('No video frames decoded')
    # Confirm export isn't truncated before reporting success.
    check = cv2.VideoCapture(str(args.output/'comparison.mp4'))
    decoded = 0
    while check.read()[0]:
        decoded += 1
    check.release()
    if decoded != len(records):
        raise RuntimeError(f'Comparison video truncated: {decoded}/{len(records)}')
    report = dict(video=str(args.video.resolve()),frames=len(records),source_fps=fps,
        crop_side=min(args.crop_side,width,height),input_size=cfg['image_size'],
        model_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),config=CONFIG,
        timestamp_fallbacks=timestamp_fallbacks,
        baseline_observed_frames=sum(r['baseline'] is not None for r in records),
        cropped_observed_frames=sum(r['cropped'] is not None for r in records),
        crop_only_observed_frames=sum(r['baseline'] is None and r['cropped'] is not None for r in records),
        baseline_only_observed_frames=sum(r['baseline'] is not None and r['cropped'] is None for r in records),
        median_full_ms=statistics.median(r['full_ms'] for r in records[1:] or records),
        median_extra_crop_ms=statistics.median(r['extra_crop_ms'] for r in records[1:] or records),
        note='Observed coverage is NOT accuracy. Inspect comparison and label frames before accepting improvements. CPU timings exclude encoding, not an iPhone benchmark.')
    if labels is not None:
        report['label_evaluation'] = evaluate_labels(records,labels,args.label_radius)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'config'},indent=2))


if __name__ == '__main__':
    main()
