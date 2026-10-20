import CoreGraphics
import Foundation

/// A ball position for one frame: either measured (`observed`) or linearly
/// `interpolated` across a short, physically plausible gap within one track.
public struct BallSample: Sendable, Hashable {
    public enum Source: String, Sendable { case observed, interpolated }
    public let frameIndex: Int
    public let time: Double
    public let center: CGPoint
    public let trackID: Int
    public let source: Source
    /// Detector confidence; nil for interpolated samples.
    public let confidence: Double?
}

public enum BallTrajectory {
    /// Runs `BallTracker` over every frame (sorted by time). Frames whose timestamps are not
    /// strictly increasing get no ball rather than failing the whole run.
    public static func track(_ frames: [FrameDetections], config: BallTrackerConfig = .init()) -> [TrackedBall?] {
        guard let first = frames.first else { return [] }
        var tracker = BallTracker(width: first.width, height: first.height, config: config)
        return frames.map { frame in (try? tracker.select(frame.balls, at: frame.timeSeconds)) ?? nil }
    }

    /// Per-frame samples: observed tracked balls, plus interpolation between consecutive
    /// observations of the same track that are at most `interpolateGapSeconds` apart and
    /// within the speed gate. Mirrors the interpolation step of the desktop
    /// `ball_physics.build_trajectory` (without its display-only smoothing and coasting).
    public static func samples(frames: [FrameDetections], tracked: [TrackedBall?],
                               config: BallTrackerConfig = .init()) -> [BallSample?] {
        precondition(frames.count == tracked.count)
        guard let first = frames.first else { return [] }
        let diagonal = hypot(first.width, first.height)
        var samples = [BallSample?](repeating: nil, count: frames.count)
        var previous: (index: Int, ball: TrackedBall)?
        for (index, ball) in tracked.enumerated() {
            guard let ball else { continue }
            if let previous {
                let t0 = frames[previous.index].timeSeconds, t1 = frames[index].timeSeconds
                let dt = t1 - t0
                let gate = diagonal * (config.motionSlackDiagonals + config.maxMotionDiagonalsPerSecond * dt)
                if dt > 0, dt <= config.interpolateGapSeconds, previous.ball.trackID == ball.trackID,
                   distance(previous.ball.center, ball.center) <= gate {
                    for gap in (previous.index + 1)..<index {
                        let alpha = (frames[gap].timeSeconds - t0) / dt
                        let a = previous.ball.center, b = ball.center
                        samples[gap] = BallSample(
                            frameIndex: gap, time: frames[gap].timeSeconds,
                            center: CGPoint(x: a.x + alpha * (b.x - a.x), y: a.y + alpha * (b.y - a.y)),
                            trackID: ball.trackID, source: .interpolated, confidence: nil)
                    }
                }
            }
            samples[index] = BallSample(frameIndex: index, time: frames[index].timeSeconds, center: ball.center,
                                        trackID: ball.trackID, source: .observed,
                                        confidence: ball.detection.confidence)
            previous = (index, ball)
        }
        return samples
    }
}
