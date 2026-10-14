import Foundation

/// Per-frame detections indexed by source presentation time, for overlay lookup.
/// Times come from the same asset timeline as AVPlayer, so they align directly.
struct DetectionTimeline: Sendable {
    struct TrailPoint: Sendable {
        let center: CGPoint
        /// 0 (oldest) ... 1 (current frame).
        let recency: Double
    }

    let frames: [FrameDetections]
    private let times: [Double]
    /// Median spacing between frames; used to decide when a time has no analyzed frame.
    let frameInterval: Double

    init(frames: [FrameDetections]) {
        let sorted = frames.sorted { $0.timeSeconds < $1.timeSeconds }
        self.frames = sorted
        times = sorted.map(\.timeSeconds)
        let gaps = zip(times.dropFirst(), times).map { $0 - $1 }.filter { $0 > 0 }.sorted()
        frameInterval = gaps.isEmpty ? 1.0 / 30 : gaps[gaps.count / 2]
    }

    init(contentsOf url: URL) throws {
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        var frames: [FrameDetections] = []
        for line in data.split(separator: UInt8(ascii: "\n")) where !line.isEmpty {
            frames.append(try decoder.decode(FrameDetections.self, from: Data(line)))
        }
        self.init(frames: frames)
    }

    /// Index of the frame being displayed at `time`: the last frame whose timestamp is
    /// not after `time` (small tolerance for float rounding). Nil before the first frame
    /// or more than two frame intervals past the nearest analyzed frame.
    func frameIndex(at time: Double) -> Int? {
        guard time.isFinite, !times.isEmpty else { return nil }
        let target = time + frameInterval * 0.25
        var low = 0, high = times.count
        while low < high {
            let mid = (low + high) / 2
            if times[mid] <= target { low = mid + 1 } else { high = mid }
        }
        let index = low - 1
        guard index >= 0, time - times[index] <= frameInterval * 2 else { return nil }
        return index
    }

    /// Highest-confidence raw ball candidate per frame, over the previous `window`
    /// seconds. Raw detections, not a tracked trajectory.
    func ballTrail(endingAt index: Int, window: Double) -> [TrailPoint] {
        guard frames.indices.contains(index) else { return [] }
        let end = times[index]
        var points: [TrailPoint] = []
        var i = index
        while i >= 0, end - times[i] <= window {
            if let ball = Self.bestBall(in: frames[i]) {
                points.append(TrailPoint(center: ball.center, recency: 1 - (end - times[i]) / window))
            }
            i -= 1
        }
        return points.reversed()
    }

    static func bestBall(in frame: FrameDetections) -> Detection? {
        frame.detections.filter { $0.classID == DetectionClass.ball }.max { $0.confidence < $1.confidence }
    }
}
