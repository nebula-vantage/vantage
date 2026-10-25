import CoreGraphics
import Foundation

/// Per-frame detections indexed by source presentation time, plus the tracked ball
/// trajectory derived from them. Times come from the same asset timeline as AVPlayer.
/// Tracking is recomputed on load, so runs analyzed before tracking existed benefit too.
public struct DetectionTimeline: Sendable {
    public struct TrailPoint: Sendable {
        public let center: CGPoint
        /// 0 (oldest) ... 1 (current frame).
        public let recency: Double
        public let source: BallSample.Source
    }

    public let frames: [FrameDetections]
    /// Tracked ball (measured) or interpolated position per frame.
    public let ballSamples: [BallSample?]
    /// Median spacing between frames; decides when a time has no analyzed frame.
    public let frameInterval: Double
    public let trackedFrameCount: Int
    public let trackCount: Int
    private let times: [Double]

    public init(frames: [FrameDetections], config: BallTrackerConfig = .init()) {
        let sorted = frames.sorted { $0.timeSeconds < $1.timeSeconds }
        self.frames = sorted
        times = sorted.map(\.timeSeconds)
        let gaps = zip(times.dropFirst(), times).map { $0 - $1 }.filter { $0 > 0 }.sorted()
        frameInterval = gaps.isEmpty ? 1.0 / 30 : gaps[gaps.count / 2]
        let tracked = BallTrajectory.track(sorted, config: config)
        ballSamples = BallTrajectory.samples(frames: sorted, tracked: tracked, config: config)
        trackedFrameCount = tracked.compactMap { $0 }.count
        trackCount = Set(tracked.compactMap { $0?.trackID }).count
    }

    public init(contentsOf url: URL, config: BallTrackerConfig = .init()) throws {
        self.init(frames: try Self.load(url), config: config)
    }

    public static func load(_ url: URL) throws -> [FrameDetections] {
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        return try data.split(separator: UInt8(ascii: "\n")).filter { !$0.isEmpty }.map {
            try decoder.decode(FrameDetections.self, from: Data($0))
        }
    }

    /// Index of the frame being displayed at `time`: the last frame whose timestamp is
    /// not after `time` (small tolerance for float rounding). Nil before the first frame
    /// or more than two frame intervals past the nearest analyzed frame.
    public func frameIndex(at time: Double) -> Int? {
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

    /// Trajectory of the ball track visible at `index` over the previous `window` seconds.
    /// Only the most recent track is included, so the trail never jumps between identities.
    public func ballTrail(endingAt index: Int, window: Double) -> [TrailPoint] {
        guard frames.indices.contains(index) else { return [] }
        let end = times[index]
        var points: [TrailPoint] = []
        var trackID: Int?
        var i = index
        while i >= 0, end - times[i] <= window {
            if let sample = ballSamples[i] {
                if trackID == nil { trackID = sample.trackID }
                guard sample.trackID == trackID else { break }
                points.append(TrailPoint(center: sample.center, recency: 1 - (end - times[i]) / window,
                                         source: sample.source))
            }
            i -= 1
        }
        return points.reversed()
    }

    public static func bestRawBall(in frame: FrameDetections) -> Detection? {
        frame.balls.max { $0.confidence < $1.confidence }
    }
}
