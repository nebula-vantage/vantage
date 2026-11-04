"""Evaluation sources: one fetch function per public dataset, registered in eval_data.SOURCES.

Each fetch(root) downloads an eval-sized subset into root/"download" and converts it into
root/"clips" and root/"labels" with write_clip. Docstrings record each format and which frames
are labeled, absent, or left out. The label is the ball in play; "absent" means no ball in play
is visible (out of frame, hidden, or dead between points, as with N in label_ball.py), so balls
lying still or held between points are clutter. Where a source's "no ball" marker also covers
frames with the ball in play, those frames are left out (not scored) rather than marked absent,
so a correct detection is never counted as a false one. Every source was checked by drawing its
labels on decoded frames; frame shifts found that way are hard-coded with the evidence.
"""
import json
from pathlib import Path
import re
import urllib.parse
import zipfile
from xml.etree import ElementTree

from eval_data import (cookie_opener, download, download_many, encode_frames, extract, link_video, open_url,
                       read_csv, remote_zip, source, video_info, video_size, write_clip)

def runs(frames):
    """Group frame indices into runs of consecutive frames, in order."""
    grouped = []
    for frame in sorted(frames):
        if grouped and grouped[-1][-1] == frame - 1:
            grouped[-1].append(frame)
        else:
            grouped.append([frame])
    return grouped


ARNAV_PICKLEBALL_RAW = "https://raw.githubusercontent.com/arnavchokshi/pickleball/ebad4d37b869042df5fb3465105a50e07c0b841d"
ARNAV_PICKLEBALL_CLIPS = ("01_burlington_gold_0300_low_steep_corner", "02_wolverine_mixed_0200_mid_steep_corner",
                          "03_outdoor_webcam_iynbd_1500_long_high_baseline",
                          "04_indoor_doubles_fwuks_0500_long_mid_baseline")


@source("arnav-pickleball", sport="pickleball",
        view="fixed club/tournament stream cameras: low and mid corner, mid and high behind the baseline",
        license="not stated (no LICENSE; harvested online footage; research eval only, do not redistribute)",
        url="https://github.com/arnavchokshi/pickleball/tree/main/eval_clips/ball",
        download_size="about 19 MB (4 source.mp4 plus 4 CVAT zips)")
def fetch_arnav_pickleball(root):
    """arnavchokshi/pickleball eval_clips/ball: all 4 1920x1080 clips (source.mp4, linked as is)
    with the CVAT for video 1.1 export of each. The ball is a <track label="ball"> of ellipses
    centered at (cx, cy); keyframe="0" shapes were interpolated by CVAT. outside="1" shapes are left
    out, not marked absent: the annotator also used them to stop labeling while the ball was still
    in view. So are frames no ball track covers or two tracks claim, and interpolated frames whose
    next keyframe is outside (or missing): CVAT moves those toward a ball that is already hidden or
    gone. Clip 3's CVAT task covers 1800 frames but source.mp4 keeps only frames 0-1150, so later
    labels are dropped."""
    pairs = []
    for stem in ARNAV_PICKLEBALL_CLIPS:
        clip = stem[3:]
        pairs += [(f"{ARNAV_PICKLEBALL_RAW}/cvat_upload/exports/{stem}_cvat_for_video_1.1.zip",
                   root / "download" / clip / "cvat_for_video_1.1.zip"),
                  (f"{ARNAV_PICKLEBALL_RAW}/eval_clips/ball/{clip}/source.mp4", root / "download" / clip / "source.mp4")]
    download_many(pairs)
    clips = []
    for stem in ARNAV_PICKLEBALL_CLIPS:
        clip = stem[3:]
        with zipfile.ZipFile(root / "download" / clip / "cvat_for_video_1.1.zip") as archive:
            annotations = ElementTree.fromstring(archive.read("annotations.xml"))
        task = annotations.find("meta/task")
        if int(task.findtext("start_frame") or 0) != 0 or (task.findtext("frame_filter") or "").strip():
            raise ValueError(f"{clip}: CVAT task has a start_frame or frame_filter offset")
        video = link_video(root / "download" / clip / "source.mp4", root / "clips" / f"{clip}.mp4")
        frame_count = video_info(video)[1]
        shapes = {}
        for track in annotations.iter("track"):
            if track.get("label") != "ball":
                continue
            next_key_outside = None  # walking backwards: is the next keyframe outside?
            for shape in sorted(track.iter("ellipse"), key=lambda e: -int(e.get("frame"))):
                if shape.get("keyframe") == "1":
                    next_key_outside = shape.get("outside") == "1"
                if shape.get("outside") != "1" and (shape.get("keyframe") == "1" or next_key_outside is False):
                    shapes.setdefault(int(shape.get("frame")), []).append(shape)
        points = {frame: {"ball": (float(found[0].get("cx")), float(found[0].get("cy"))),
                          "interpolated": found[0].get("keyframe") != "1" or None}
                  for frame, found in shapes.items() if frame < frame_count and len(found) == 1}
        clips.append(write_clip(root, clip, video, points))
    return clips


ROCHESTER_PICKLEBALL_VIDEO = "https://drive.usercontent.google.com/download?id=1_IttM4H7DOy-TL_xemQOnQhvGvwnt7TG&export=download&confirm=t"
ROCHESTER_PICKLEBALL_LABELS = "https://drive.usercontent.google.com/download?id=198jLZ56IMKi0wlC45YRw_Suvx_nklPa9&export=download&confirm=t"
# Rows after this frame are unlabeled "0,-1,-1" placeholders.
ROCHESTER_PICKLEBALL_LAST_FRAME = 12000
# A visible label this close to the frame border means the ball is leaving or entering the picture.
ROCHESTER_PICKLEBALL_EDGE_PX = 40


@source("rochester-pickleball", sport="pickleball",
        view="fixed, moderately elevated broadcast camera centered behind one baseline (pro match stream)",
        license="not stated (no LICENSE in the repo; Zelus stream of the USA Pickleball Tournament of Champions; research eval only)",
        url="https://github.com/AndrewDettor/TrackNet-Pickleball", download_size="about 438 MB (one MP4 plus a 250 KB CSV)")
def fetch_rochester_pickleball(root):
    """TrackNet-Pickleball (Univ. of Rochester): a 7-minute in-play cut of a 2021 pro senior mixed
    doubles match, 1920x1080 at 30 fps CFR (12,810 frames). One CSV, 'Frame,Ball,x,y', with x and y
    normalized to 0-1. Only frames 0-12000 were labeled; later rows are placeholders and are dropped.

    Ball 0 is the labeling tool's default for any frame the annotator did not click ("no ball or
    not clearly visible"), and inside rallies it often hides a clearly visible ball. So Ball 0 is
    kept as absent only where the ball was lobbed out of the picture (the visible labels on both
    sides of the gap touch the frame border); other Ball 0 frames are left unlabeled."""
    video, labels = download_many([
        (ROCHESTER_PICKLEBALL_VIDEO, root / "download" / "InPlayBalls_54min_vid.mp4", 437_921_818),
        (ROCHESTER_PICKLEBALL_LABELS, root / "download" / "InPlayBalls_54min_vid_labels.csv", 249_797)])
    clip = link_video(video, root / "clips" / "inplayballs.mp4")
    width, height = video_size(clip)
    balls = {int(row["Frame"]): (float(row["x"]) * width, float(row["y"]) * height) if row["Ball"] == "1" else None
             for row in read_csv(labels) if int(row["Frame"]) <= ROCHESTER_PICKLEBALL_LAST_FRAME}
    points = {frame: ball for frame, ball in balls.items() if ball is not None}

    def at_edge(ball):
        return ball is not None and min(ball[0], ball[1], width - ball[0], height - ball[1]) < ROCHESTER_PICKLEBALL_EDGE_PX

    for gap in runs(frame for frame, ball in balls.items() if ball is None):
        if at_edge(balls.get(gap[0] - 1)) and at_edge(balls.get(gap[-1] + 1)):
            points.update(dict.fromkeys(gap))
    return [write_clip(root, "inplayballs", clip, points,
                       notes="absent only while the ball is out of the picture; other Ball=0 frames are unlabeled")]


TNV2PIC_URL = "https://www.kaggle.com/api/v1/datasets/download/kagmanedai/tnv2pic/{}?datasetVersionNumber=2"
TNV2PIC_CLIPS = (("test", "1_01_00"), ("test", "1_02_00"), ("train", "1_07_00"))
# The CSVs start with -1 for their first 2-3 frames even when the ball is plainly visible: the
# labels look like the output of a 3-frame TrackNet-style model, which cannot predict them.
TNV2PIC_WARMUP = 3
# A run of "no ball" rows at least this long (1 s at 60 fps) is dead time between points; shorter
# runs are mostly the labeler missing a ball in play, so they are left out.
TNV2PIC_DEAD_BALL_FRAMES = 60
TNV2PIC_NOTES = ("labels look like model pseudo-labels (no warmup prediction, occasional switches to "
                 "dead balls or balls on other courts); frames 0-2 and no-ball runs under 1 s left unlabeled")


@source("tnv2pic-pickleball", sport="pickleball",
        view="1080p60 corner/near-sideline cameras with score overlays: a Vietnamese tournament stream "
             "(test 1_01, zooms mid-clip) and a fixed US indoor rec-doubles camera (test 1_02, train 1_07)",
        license="not stated (Kaggle license 'Unknown'; third-party livestream and YouTube footage; research eval only)",
        url="https://www.kaggle.com/datasets/kagmanedai/tnv2pic", download_size="about 190 MB (3 videos and CSVs)")
def fetch_tnv2pic_pickleball(root):
    """Kaggle TNv2Pic (TrackNetV2 layout): <split>/match1/video/<clip>.mp4 with csv/<clip>_ball.csv
    rows 'frame,x,y' (0-based decoded frame, 1920x1080 pixels, -1,-1 = no ball, every frame listed).
    Subset: test 1_01_00 (Vietnamese tournament) plus test 1_02_00 and train 1_07_00, consecutive
    parts of one US amateur indoor match; fetched per file through Kaggle's anonymous download API.
    The labels look machine-made and sometimes miss a ball in play, so "no ball" counts as absent
    only in runs of TNV2PIC_DEAD_BALL_FRAMES or more (between points)."""
    pairs = []
    for split, clip in TNV2PIC_CLIPS:
        for path in (f"{split}/match1/csv/{clip}_ball.csv", f"{split}/match1/video/{clip}.mp4"):
            path = f"TrackNetV2_Dataset/{path}"
            pairs.append((TNV2PIC_URL.format(urllib.parse.quote(path, safe="")), root / "download" / path))
    download_many(pairs, workers=6)
    clips = []
    for split, clip in TNV2PIC_CLIPS:
        base = root / "download" / "TrackNetV2_Dataset" / split / "match1"
        name = f"{split}_{clip}"
        video = link_video(base / "video" / f"{clip}.mp4", root / "clips" / f"{name}.mp4")
        balls = {int(row["frame"]): None if row["x"] == "-1" else (float(row["x"]), float(row["y"]))
                 for row in read_csv(base / "csv" / f"{clip}_ball.csv")}
        points = {f: p for f, p in balls.items() if p is not None}
        for run in runs(f for f, p in balls.items() if p is None and f >= TNV2PIC_WARMUP):
            if len(run) >= TNV2PIC_DEAD_BALL_FRAMES:
                points.update(dict.fromkeys(run))
        clips.append(write_clip(root, name, video, points, notes=TNV2PIC_NOTES))
    return clips


TRACKNET_TENNIS_ZIP = "https://drive.usercontent.google.com/download?id=1DQ3ZbvokTsgOq6x-ay6O8U2W4a8e3LFw&export=download&confirm=t"
TRACKNET_TENNIS_STATUS = {"1": "hit", "2": "bounce"}
TRACKNET_TENNIS_VISIBILITY = {"1": "visible", "2": "difficult"}  # 3, occluded: left out


@source("tracknet-tennis", sport="tennis",
        view="broadcast main camera behind the baseline; game4 is a low fixed ITF-match camera",
        license="not stated (TV broadcast footage; research eval only)",
        url="https://arxiv.org/abs/1907.03698", download_size="about 1.1 GB of a 2.6 GB zip")
def fetch_tracknet_tennis(root):
    """TrackNet tennis (Huang et al. 2019): game4 (low fixed camera, the closest to Vantage) plus
    the WASB-SBDT test split game8-10. Label.csv per clip: visibility 0-3, x, y, status
    (0 flying, 1 hit, 2 bounce); frames are 1280x720 JPGs at 30 fps. Visibility 0 (out of frame)
    is absent; 3 (occluded: the ball is behind a player) is left out, as WASB-SBDT does."""
    archive = remote_zip(TRACKNET_TENNIS_ZIP, size=2_564_111_322)
    games = ("game4", "game8", "game9", "game10")
    wanted = [n for n in archive.namelist() if n.split("/")[1:2] and n.split("/")[1] in games and not n.endswith("/")]
    extract(archive, wanted, root / "download")
    clips = []
    for label_file in sorted((root / "download" / "Dataset").glob("game*/Clip*/Label.csv"),
                             key=lambda p: (int(p.parent.parent.name[4:]), int(p.parent.name[4:]))):
        rows = read_csv(label_file)
        images = [label_file.parent / row["file name"] for row in rows]
        name = f"{label_file.parent.parent.name}_{label_file.parent.name.lower()}"
        video = encode_frames(images, 30, root / "clips" / f"{name}.mp4")
        points = {}
        for i, row in enumerate(rows):
            if row["visibility"] == "3":
                continue
            visible = row["visibility"] != "0"
            points[i] = {"ball": (float(row["x-coordinate"]), float(row["y-coordinate"])) if visible else None,
                         "visibility": TRACKNET_TENNIS_VISIBILITY.get(row["visibility"], "absent"),
                         "event": TRACKNET_TENNIS_STATUS.get(row["status"])}
        clips.append(write_clip(root, name, video, points))
    return clips


TENNIS_ANALYTICS_URL = ("https://www.kaggle.com/api/v1/datasets/download/benediktvoss/tennisanalytics"
                        "?datasetVersionNumber=2")
# Video_6 is the authors' fully held-out video; the others are one clip per remaining video.
TENNIS_ANALYTICS_CLIPS = ("Video_6/clip_1", "Video_1/clip_6", "Video_2/clip_7", "Video_3/clip_8",
                          "Video_4/clip_7", "Video_5/clip_6")
TENNIS_ANALYTICS_IN_PLAY = {"Flying", "Hit", "Bounce"}  # not "Static": balls lying on the court
TENNIS_ANALYTICS_EVENTS = {"Hit": "hit", "Bounce": "bounce"}


@source("tennis-analytics", sport="tennis",
        view="fixed camera at standing height behind the baseline (Video_1: rear corner); amateur clay courts",
        license="Apache 2.0", url="https://www.kaggle.com/datasets/benediktvoss/tennisanalytics",
        download_size="about 645 MB of a 14.5 GB zip")
def fetch_tennis_analytics(root):
    """TennisAnalytics (Voss 2024), Amateur subset: Video_6/clip_1 plus one clip from each of
    Video_1-5. 00_Dataset/annotations.json lists per-frame balls {x, y (720p), visibility
    Visible|Difficult|Occluded|Blurry|Outside, trajectory Flying|Hit|Bounce|Static}; frames are
    00_Dataset/Amateur/Video_N/clip_M/<idx>.jpg, 1280x720, every frame annotated, 30 fps (the
    authors' own renderer). From each clip's first in-play ball on, exactly one in-play ball (not
    Static, not Outside) is the label, none is absent, and two are left out, as are Occluded balls
    (hidden behind a player)."""
    # Kaggle redirects to a signed storage URL; resolve it once so range reads skip the API.
    with open_url(TENNIS_ANALYTICS_URL, headers={"Range": "bytes=0-0"}) as response:
        archive = remote_zip(response.url, size=14_488_044_392)
    prefixes = tuple(f"00_Dataset/Amateur/{clip}/" for clip in TENNIS_ANALYTICS_CLIPS)
    wanted = [n for n in archive.namelist() if n.startswith(prefixes) and n.endswith(".jpg")]
    dataset = root / "download" / "00_Dataset"
    extract(archive, ["00_Dataset/annotations.json", *wanted], root / "download")
    subset = next(s for s in json.loads((dataset / "annotations.json").read_text())["subsets"]
                  if s["name"] == "Amateur")
    annotated = {f"{v['name']}/{c['name']}": c for v in subset["videos"] for c in v["clips"]}
    clips = []
    for clip in TENNIS_ANALYTICS_CLIPS:
        images = sorted((dataset / "Amateur" / clip).glob("*.jpg"), key=lambda p: int(p.stem))
        if [int(p.stem) for p in images] != list(range(len(images))):
            raise ValueError(f"{clip}: frame files are not numbered 0..n-1")
        name = clip.lower().replace("_", "").replace("/", "_")
        video = encode_frames(images, 30, root / "clips" / f"{name}.mp4")
        frames = {int(f): [b for b in objects["balls"] if b["trajectory"] in TENNIS_ANALYTICS_IN_PLAY]
                  for f, objects in annotated[clip]["frames_with_objects"].items()}
        # Each clip's first track starts at the serve toss or bounce; before it the server's ball
        # is unlabeled though often visible in hand, so those frames are left out. Later gaps
        # follow an Outside keyframe (ball hidden or out of view) and count as absent.
        first = min(f for f, balls in frames.items() if balls)
        points = {}
        for frame, balls in frames.items():
            in_play = [b for b in balls if b["visibility"] != "Outside"]
            if frame < first or len(in_play) > 1 or (in_play and in_play[0]["visibility"] == "Occluded"):
                continue
            ball = in_play[0] if in_play else None
            points[frame] = {"ball": (ball["x"], ball["y"]) if ball else None,
                             "visibility": ball["visibility"].lower() if ball else "absent",
                             "event": TENNIS_ANALYTICS_EVENTS.get(ball["trajectory"]) if ball else None}
        clips.append(write_clip(root, name, video, points,
                                notes="held-out test video" if clip.startswith("Video_6/") else ""))
    return clips


YONGGEST_TENNIS_REPO = "https://huggingface.co/datasets/yonggest/tennis-track-26"
# Pinned commit, so a re-run cannot mix frames or labels from two versions of the dataset.
YONGGEST_TENNIS_REVISION = "cd20cde8788eeac9dfa12de46e5ed4a6d8521d3b"
# Clip folder -> number of leading frames whose labels are used. SW/01 stops at 670: from there
# the server pulls a second ball from her pocket, which is boxed in some frames and not others.
YONGGEST_TENNIS_CLIPS = {"SW/01_20260411_张芸发球": 670, "CB/01_20260328_阿甘发球": 240}
YONGGEST_TENNIS_FPS = 60000 / 1001  # the tennis-video-26 source videos are 59.94 fps HEVC
YONGGEST_TENNIS_BALL = 3  # COCO category "sports ball"


@source("yonggest-tennis", sport="tennis",
        view="fixed raised camera centered behind one baseline (amateur club hard courts, 4K)",
        license="not stated", url=YONGGEST_TENNIS_REPO,
        download_size="about 1.85 GB (1,001 4K JPGs + 2 COCO JSONs)")
def fetch_yonggest_tennis(root):
    """yonggest/tennis-track-26 (Hugging Face): <venue>/<clip>/_annotations.coco.json with person,
    tennis racket and sports ball boxes, plus every frame as <stem>-NNN.jpg (3840x2160, consecutive
    frames of a 59.94 fps video). Takes the two dense clips from different venues: SW/01 (761-frame
    singles rally) and CB/01 (240-frame doubles-match serve). Ball center = box center. Frames
    with no ball box are left out, not marked absent: the ball is still visible in them (held,
    behind the net, or just missed). Frames with two ball boxes (a stray ball as well) are left out."""
    base = f"{YONGGEST_TENNIS_REPO}/resolve/{YONGGEST_TENNIS_REVISION}/"
    clips = []
    for folder, labeled_frames in YONGGEST_TENNIS_CLIPS.items():
        directory = root / "download" / folder
        coco_path = download(base + urllib.parse.quote(f"{folder}/_annotations.coco.json"),
                             directory / "_annotations.coco.json")
        coco = json.loads(coco_path.read_text())
        numbered = {}
        for image in coco["images"]:
            match = re.fullmatch(r"[\w-]+-(\d+)\.jpg", image["file_name"])
            if not match:
                raise ValueError(f"{folder}: unexpected frame name {image['file_name']!r}")
            numbered[int(match.group(1))] = image
        order = sorted(numbered)
        if order != list(range(order[0], order[0] + len(order))):
            raise ValueError(f"{folder}: frame numbers are not consecutive")
        images = [numbered[n] for n in order]
        download_many([(base + urllib.parse.quote(f"{folder}/{image['file_name']}"), directory / image["file_name"])
                       for image in images])
        balls = {}
        for box in coco["annotations"]:
            if box["category_id"] == YONGGEST_TENNIS_BALL:
                x, y, w, h = box["bbox"]
                balls.setdefault(box["image_id"], []).append((x + w / 2, y + h / 2))
        name = coco["info"]["description"].lower()
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            raise ValueError(f"{folder}: unexpected clip name {name!r}")
        video = encode_frames([directory / image["file_name"] for image in images], YONGGEST_TENNIS_FPS,
                              root / "clips" / f"{name}.mp4")
        points = {i: balls[image["id"]][0] for i, image in enumerate(images[:labeled_frames])
                  if len(balls.get(image["id"], ())) == 1}
        clips.append(write_clip(root, name, video, points))
    return clips


BALLYOLO_REPO = "Zoutianjian/Ball-Yolo-A-Sport-Ball-Dataset"
# Pinned commit (main on 2026-11-04): the frame shifts below were verified against it.
BALLYOLO_REVISION = "c6992050c74d6e3f6992bac0e314e7b378a0f51c"
BALLYOLO_RAW = f"https://raw.githubusercontent.com/{BALLYOLO_REPO}/{BALLYOLO_REVISION}/"
BALLYOLO_TREES = f"https://api.github.com/repos/{BALLYOLO_REPO}/git/trees/"
# Video name -> (last decoded frame to keep or None, ((first source frame, shift), ...)). In two
# videos the labels were made on a frame sequence that drops or repeats a frame: from the given
# source frame on, label k belongs to decoded frame k + shift (found by eye on fast balls; 4_0_3's
# labels 655 and 656 are the same point, both on decoded frame 656). Amateur_5_5_5_0's camera
# starts panning at frame 359, so later frames are left out.
BALLYOLO_TENNIS_VIDEOS = {
    "ShunYi_Amaetur_4_0_0": (None, ()),
    "ShunYi_Amaetur_4_0_3": (None, ((144, 1), (656, 0))),
    "Amateur_5_5_5_0": (358, ()),
    "Std_6_0_Confort_PullBall": (None, ((316, 1),)),
}
BALLYOLO_TENNIS_NOTES = {
    "ShunYi_Amaetur_4_0_0": "hard cut to the opposite court corner at frame 338",
    "ShunYi_Amaetur_4_0_3": "source labels 144-655 shifted +1 frame",
    "Amateur_5_5_5_0": "camera pans from frame 359; only frames 19-355 labeled",
    "Std_6_0_Confort_PullBall": "source labels from 316 on shifted +1 frame",
}


@source("ballyolo-tennis", sport="tennis",
        view="fixed amateur-match cameras: low court-corner views (two indoor, one outdoor night) "
             "and one centered behind-the-baseline view (60 fps)",
        license="not stated on GitHub (README: research and academic use only); Dryad release: "
                "labels CC0-1.0, videos CC BY-NC-ND 4.0 (third-party Bilibili footage)",
        url="https://doi.org/10.5061/dryad.3bk3j9m13",
        download_size="about 31 MB (4 videos, 3,790 label files, 1 MB of GitHub tree listings)")
def fetch_ballyolo_tennis(root):
    """Ball-Yolo (Zou & Liu, BUPT) tennis, from the GitHub copy: tennis/Videos/<name>.mp4 (unblurred
    originals) and tennis/Labels/<name>/<name>_<frame>.txt, one YOLO 'class cx cy w h' line
    (normalized) per ball, files only for frames with a ball. Only the four amateur fixed-camera
    videos; the rest are broadcast highlights or coaching close-ups. Frames with two or more boxes
    and frames without a label file are left out: the gaps often hold a faint, occluded, or held
    ball that was not labeled, so they are not reliably absent."""
    def tree(sha):
        path = download(BALLYOLO_TREES + sha, root / "download" / "trees" / f"{sha}.json")
        return {entry["path"]: entry for entry in json.loads(path.read_text())["tree"]}

    labels_tree = tree(tree(tree(BALLYOLO_REVISION)["tennis"]["sha"])["Labels"]["sha"])
    files = {name: [f"tennis/Labels/{name}/{path}" for path, entry in tree(labels_tree[name]["sha"]).items()
                    if entry["type"] == "blob" and path.endswith(".txt")] for name in BALLYOLO_TENNIS_VIDEOS}
    pairs = [(BALLYOLO_RAW + path, root / "download" / path) for paths in files.values() for path in paths]
    pairs += [(BALLYOLO_RAW + f"tennis/Videos/{name}.mp4", root / "download" / "tennis" / "Videos" / f"{name}.mp4")
              for name in BALLYOLO_TENNIS_VIDEOS]
    download_many(pairs)
    clips = []
    for name, (last, shifts) in BALLYOLO_TENNIS_VIDEOS.items():
        video = link_video(root / "download" / "tennis" / "Videos" / f"{name}.mp4",
                           root / "clips" / f"{name.lower()}.mp4")
        width, height = video_size(video)
        points = {}
        for path in files[name]:
            frame = int(Path(path).stem.rsplit("_", 1)[1])
            rows = [line.split() for line in (root / "download" / path).read_text().splitlines() if line.strip()]
            frame += next((shift for start, shift in reversed(shifts) if frame >= start), 0)
            if len(rows) == 1 and (last is None or frame <= last):
                points[frame] = (float(rows[0][1]) * width, float(rows[0][2]) * height)
        clips.append(write_clip(root, name.lower(), video, points, notes=BALLYOLO_TENNIS_NOTES[name]))
    return clips


TENIS_BACKVIEW_URL = ("https://www.kaggle.com/api/v1/datasets/download/gastonarielfrancois/tenis-backview/"
                      "{}?datasetVersionNumber=1")


@source("tenis-backview", sport="tennis",
        view="fixed camera behind one baseline, head height to slightly raised; a different court per clip",
        license="CC0: Public Domain (as stated on Kaggle; the footage is clipped from third-party YouTube videos)",
        url="https://www.kaggle.com/datasets/gastonarielfrancois/tenis-backview",
        download_size="about 90 MB (10 MP4s and their ball CSVs)")
def fetch_tenis_backview(root):
    """tenis_backview (ITBA final project, on Kaggle): all 10 clips, 1920x1080 at 60 or 30 fps.
    videoN_ball.csv: frame ("frame_###", the 0-based decoded frame index), ball_x, ball_y. There is
    no visibility column: a frame without a coordinate holds a click in the top-right corner
    (x 1890-1918, y 1-38), and some of those frames show the ball, so they are left out rather
    than marked absent. The court and player CSVs are not fetched."""
    names = [f"video{i}{suffix}" for i in range(1, 11) for suffix in (".mp4", "_ball.csv")]
    download_many([(TENIS_BACKVIEW_URL.format(n), root / "download" / n) for n in names], workers=4)
    clips = []
    for i in range(1, 11):
        name = f"video{i}"
        points = {}
        for row in read_csv(root / "download" / f"{name}_ball.csv"):
            x, y = float(row["ball_x"]), float(row["ball_y"])
            if not (x >= 1880 and y <= 40):  # the "no coordinate" corner click
                points[int(row["frame"].removeprefix("frame_"))] = (x, y)
        video = link_video(root / "download" / f"{name}.mp4", root / "clips" / f"{name}.mp4")
        clips.append(write_clip(root, name, video, points))
    return clips


# Pinned revision (main on 2026-11-04), so labels cannot change under a re-run.
RACKETVISION_FILES = ("https://huggingface.co/datasets/linfeng302/RacketVision/resolve/"
                      "85157ca21faa2abca96d837dd2b963738029bcc8/")
RACKETVISION_SIZE = (1920, 1080)  # every clip; X and Y are pixels in this frame


def racketvision_clips(root, sport):
    """Official test split of one RacketVision sport: <sport>/info/test.json lists [match, rally];
    the video is <sport>/videos/<match>_<rally>.mp4 and the labels are
    <sport>/all/<match>/csv/<rally>_ball.csv with columns Frame (0-based decoded frame),
    Visibility (1 visible, 0 not visible, with X=Y=0), X, Y. Only sampled frames have rows
    (50 per clip, evenly spaced); the rest are left out, and so are visible rows whose point
    lies outside the frame (one badminton test row, X=-151 Y=-1, is an annotation slip)."""
    download_dir = root / "download"
    split = json.loads(download(RACKETVISION_FILES + f"{sport}/info/test.json",
                                download_dir / sport / "info" / "test.json").read_text())
    split = sorted(split, key=lambda pair: (int(pair[0].removeprefix("match")), pair[1]))
    paths = [f"{sport}/{part}" for match, rally in split
             for part in (f"videos/{match}_{rally}.mp4", f"all/{match}/csv/{rally}_ball.csv")]
    download_many([(RACKETVISION_FILES + path, download_dir / path) for path in paths])
    clips = []
    for match, rally in split:
        name = f"{match}_{rally}".lower()
        video = link_video(download_dir / sport / "videos" / f"{match}_{rally}.mp4", root / "clips" / f"{name}.mp4")
        points = {}
        for row in read_csv(download_dir / sport / "all" / match / "csv" / f"{rally}_ball.csv"):
            x, y = float(row["X"]), float(row["Y"])
            if row["Visibility"] != "1":
                points[int(row["Frame"])] = None
            elif 0 <= x < RACKETVISION_SIZE[0] and 0 <= y < RACKETVISION_SIZE[1]:
                points[int(row["Frame"])] = (x, y)
        clips.append(write_clip(root, name, video, points))
    return clips


@source("racketvision-tennis", sport="tennis",
        view="ATP TV broadcast, mostly the elevated main camera behind the baseline; match1, 13, 107 "
             "and 122 are lower cameras behind the baseline, match113 an elevated corner camera, "
             "match118 and 129 low corner cameras at practice",
        license="MIT (dataset card and repo; the clips are cut from YouTube broadcasts)",
        url="https://github.com/OrcustD/RacketVision",
        download_size="189 MB (43 test-split videos plus label CSVs)")
def fetch_racketvision_tennis(root):
    """RacketVision tennis (Dong et al., AAAI 2026), official test split: 43 clips of about
    10 s, 28 at 25 fps, 5 at 29.97 and 10 at 60, each labeled every 5 to 12 frames.
    See racketvision_clips for the format."""
    return racketvision_clips(root, "tennis")


@source("racketvision-badminton", sport="badminton",
        view="BWF TV broadcast main camera, elevated behind one baseline",
        license="MIT (dataset card and repo; the clips are cut from YouTube broadcasts)",
        url="https://github.com/OrcustD/RacketVision",
        download_size="169 MB (46 test-split videos plus label CSVs)")
def fetch_racketvision_badminton(root):
    """RacketVision badminton (Dong et al., AAAI 2026), official test split: 46 clips of about
    10 s at 25 fps, singles and doubles, each labeled about every 5 frames.
    See racketvision_clips for the format."""
    return racketvision_clips(root, "badminton")


TRACKNETV2_SHARE = ("https://nycu1-my.sharepoint.com/:u:/g/personal/tik_m365_nycu_edu_tw/"
                    "EWisYhAiai9Ju7L-tQp0ykEBZJd9VQkKqsFrjcqqYIDP-g?e=S0AB1Z")
TRACKNETV2_ZIP = ("https://nycu1-my.sharepoint.com/personal/tik_m365_nycu_edu_tw/_layouts/15/download.aspx"
                  "?SourceUrl=%2Fpersonal%2Ftik%5Fm365%5Fnycu%5Fedu%5Ftw%2FDocuments%2FOpenDataset"
                  "%2FTrackNetV2%5FBadminton%2FTrackNetV2%2Ezip")
# TrackNetV3 commit that added drop_frame.json; corrected_test_label/ has not changed since.
TRACKNETV3_LABELS = ("https://raw.githubusercontent.com/qaz812345/TrackNetV3/"
                     "1f4911cc07208c501dc16e6c9eed155943dc8c92/corrected_test_label/")


@source("tracknetv2-badminton", sport="badminton",
        view="amateur: fixed low camera (about head height) behind one baseline of an indoor hall, "
             "tilted up, near court cropped; test: TV broadcast, high view from behind one baseline",
        license="not stated (TrackNetV3's MIT license covers its code, not this data; research eval only)",
        url="https://hackmd.io/Nf8Rh1NrSrqNUzmO0sQKZw",
        download_size="about 390 MB of a 1.73 GB zip, plus 170 KB of corrected labels from GitHub")
def fetch_tracknetv2_badminton(root):
    """Shuttlecock Trajectory Dataset (TrackNetV2, NYCU): one MP4 per rally (1280x720, 30 fps)
    and a <rally>_ball.csv with Frame,Visibility,X,Y (0-based frame, visibility 0/1, pixel
    centre, 0,0 when invisible). Takes Amateur/match1-3 (fixed amateur camera; every labeled
    frame) and the broadcast Test/match1-3 with TrackNetV3's corrected test labels, keeping only
    each rally's drop_frame.json [start, end) span, the in-play frames TrackNetV3 scores (outside
    it the shuttle is in the server's hand or on the floor). Some CSVs stop a few frames before
    the video ends; those trailing frames stay unlabeled. Three corrected rows say visible at
    0,0, a correction-tool slip, and are left out."""
    opener = cookie_opener()
    with open_url(TRACKNETV2_SHARE, opener=opener) as response:  # sets the anonymous-access cookie
        response.read(1)
    archive = remote_zip(TRACKNETV2_ZIP, opener, size=1_731_293_072)
    wanted = [n for n in archive.namelist()
              if n.split("/")[1:2] in (["Amateur"], ["Test"]) and n.endswith((".mp4", ".csv"))]
    extract(archive, wanted, root / "download")
    dataset = root / "download" / "TrackNetV2"
    corrected = root / "download" / "corrected_test_label"
    test_csvs = sorted(dataset.glob("Test/match*/csv/*_ball.csv"))
    download_many([(TRACKNETV3_LABELS + "drop_frame.json", corrected / "drop_frame.json")] +
                  [(f"{TRACKNETV3_LABELS}{p.parent.parent.name}/corrected_csv/{p.name}",
                    corrected / p.parent.parent.name / "corrected_csv" / p.name) for p in test_csvs])
    drop = json.loads((corrected / "drop_frame.json").read_text())
    clips = []
    for split in ("Amateur", "Test"):
        for video in sorted(dataset.glob(f"{split}/match*/video/*.mp4"),
                            key=lambda p: (int(p.parent.parent.name[5:]), p.stem)):
            match, rally = video.parent.parent.name, video.stem
            if split == "Test":
                rows = read_csv(corrected / match / "corrected_csv" / f"{rally}_ball.csv")
                key = f"{match[5:]}_{rally}"
                frames = range(drop["start"][key], drop["end"][key])
            else:
                rows = read_csv(video.parent.parent / "csv" / f"{rally}_ball.csv")
                frames = range(len(rows))
            name = f"{split.lower()}_m{match[5:]}_{rally}"
            clip = link_video(video, root / "clips" / f"{name}.mp4")
            points = {}
            for row in rows:
                frame, x, y = int(row["Frame"]), float(row["X"]), float(row["Y"])
                visible = float(row["Visibility"]) > 0
                if frame in frames and not (visible and x == y == 0):
                    points[frame] = (x, y) if visible else None
            clips.append(write_clip(root, name, clip, points))
    return clips


# (url, size): the sizes pin the uploads the frame shifts below were found on.
KWYOKE_BADMINTON_ZIPS = (
    ("https://drive.usercontent.google.com/download?id=14FOLegDDxgJi5WWeBs0Ok8VQvdZYbZJx&export=download&confirm=t",
     57_470_277),  # am_doubles.zip
    ("https://drive.usercontent.google.com/download?id=1oXeQhJmD5UfBElHVwIsgwlLZ6kFJuZTh&export=download&confirm=t",
     85_308_720),  # am_singles.zip
)
# The china and china2 ball tracks drop 1-2 decoded frames at about 5.6 s and one more at about
# 10.6 s, as if made from a copy of the video missing those frames, so later rows describe later
# frames. Found by matching shuttle motion against shifted tracks and checked frame by frame:
# {clip: ((first CSV frame, decoded frame minus CSV frame from there on), ...)}.
KWYOKE_BADMINTON_SHIFTS = {
    "am_doubles_match_china_doubles0": ((168, 2),),
    "am_doubles_match_china_doubles1": ((168, 1),),
    "am_doubles_match_china_doubles2": ((168, 2),),
    "am_doubles_match_china_doubles3": ((168, 2),),
    "am_singles_match_china2_singles0": ((140, 1),),
    "am_singles_match_china2_singles1": ((140, 2), (264, 3)),
    "am_singles_match_china2_singles2": ((140, 2),),
    "am_singles_match_china2_singles3": ((140, 2), (264, 3)),
}


@source("kwyoke-badminton", sport="badminton",
        view="fixed amateur camera at court level behind the baseline or at a back corner",
        license="not stated (footage partly re-uploaded web video; research eval only)",
        url="https://github.com/kwyoke/Badminton-hit-detection", download_size="about 82 MB (range reads from two zips totalling 143 MB)")
def fetch_kwyoke_badminton(root):
    """kwyoke/Badminton-hit-detection amateur sets: every rally with a ball track, i.e. am_doubles
    match_clementi and match_china, am_singles match_china2 and match_yewtee (am_singles/match25 is
    unlabeled TrackNetV2 video and is skipped). <set>/<match>/ holds rally_video/<rally>.mp4,
    ball_trajectory/<rally>_ball.csv (Frame, Visibility 0/1, X, Y in native pixels; it stops at
    the last visible frame, so the rest of the video is unlabeled) and
    player_hit/<rally>.mp4_player_hit.csv (one row per decoded frame: frame, player_hit 0 none /
    1 / 2, rally_bound, backhand). Ball rows are moved by KWYOKE_BADMINTON_SHIFTS; the decoded
    frames they skip stay unlabeled."""
    for url, size in KWYOKE_BADMINTON_ZIPS:
        archive = remote_zip(url, size=size)
        names = set(archive.namelist())
        wanted = []
        for ball in sorted(n for n in names if n.endswith("_ball.csv") and "/ball_trajectory/" in n):
            match, rally = ball.split("/ball_trajectory/")[0], ball.rsplit("/", 1)[1][:-len("_ball.csv")]
            wanted += [m for m in (ball, f"{match}/rally_video/{rally}.mp4",
                                   f"{match}/player_hit/{rally}.mp4_player_hit.csv") if m in names]
        extract(archive, wanted, root / "download")
    clips = []
    for ball_file in sorted((root / "download").glob("*/*/ball_trajectory/*_ball.csv")):
        match, rally = ball_file.parent.parent, ball_file.name[:-len("_ball.csv")]
        name = f"{match.parent.name}_{match.name}_{rally}".lower()
        video = link_video(match / "rally_video" / f"{rally}.mp4", root / "clips" / f"{name}.mp4")
        hit_file = match / "player_hit" / f"{rally}.mp4_player_hit.csv"
        hits = {int(r["frame"]) for r in read_csv(hit_file) if r["player_hit"] in ("1", "2")} if hit_file.exists() else set()
        shifts = KWYOKE_BADMINTON_SHIFTS.get(name, ())
        points = {}
        for row in read_csv(ball_file):
            frame = int(row["Frame"])
            frame += next((shift for start, shift in reversed(shifts) if frame >= start), 0)
            points[frame] = {"ball": (float(row["X"]), float(row["Y"])) if row["Visibility"] != "0" else None,
                             "event": "hit" if frame in hits else None}
        clips.append(write_clip(root, name, video, points))
    return clips
