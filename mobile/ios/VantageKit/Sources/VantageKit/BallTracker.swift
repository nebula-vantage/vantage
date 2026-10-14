import CoreGraphics
import Foundation

/// Tuning for `BallTracker` and `BallTrajectory`. Defaults equal the desktop pipeline's
/// `config.py` (sections `detection`, `ball_tracker`, `trajectory`); the parity fixtures
/// record the Python values so a drift fails `swift test`.
public struct BallTrackerConfig: Codable, Sendable, Equatable {
    // CONFIG["detection"]
    public var ballConfidence = 0.10
    public var maxMotionDiagonalsPerSecond = 2.0
    public var motionSlackDiagonals = 0.015
    public var candidateResetSeconds = 0.20
    // CONFIG["ball_tracker"]
    public var confirmationWindowSeconds = 0.20
    public var minConfirmationMotionDiagonals = 0.003
    public var predictionSlackDiagonals = 0.015
    public var maxAccelerationDiagonalsPerSecond2 = 12.0
    public var velocitySmoothingSeconds = 0.04
    public var confidenceWeight = 0.15
    public var turnWindowSeconds = 0.10
    public var stationaryTimeoutSeconds = 0.40
    public var stationaryRadiusDiagonals = 0.004
    // Static-clutter suppression (leaves, debris, signs); time-based, frame-rate independent.
    public var staticMemorySeconds = 3.0
    public var staticMinAgeSeconds = 1.0
    public var staticMinObservedSeconds = 0.25
    public var staticRadiusDiagonals = 0.006
    public var staticMaxFrameGapSeconds = 0.10
    // CONFIG["trajectory"]
    public var interpolateGapSeconds = 0.20

    public init() {}
}

/// A measured ball detection assigned to a track identity.
public struct TrackedBall: Sendable, Hashable {
    public let detection: Detection
    public let trackID: Int
    public var center: CGPoint { detection.center }
}

public enum BallTrackerError: Error, Equatable {
    case nonIncreasingTime(Double)
}

/// Single-ball association from raw candidates using capture-time motion.
/// Port of the desktop `ball_tracker.py`. Predictions choose among observations; they are
/// never returned as detections.
public struct BallTracker: Sendable {
    public let config: BallTrackerConfig
    public let width: Double
    public let height: Double
    public let diagonal: Double

    private var last: (time: Double, ball: TrackedBall)?
    public private(set) var velocity = CGVector(dx: 0, dy: 0)
    private var pending: [(time: Double, detection: Detection)] = []
    private var anchor: (time: Double, center: CGPoint)?
    private var lastUpdate: Double?
    private var nextID = 1
    /// Recent valid candidates (time, center, observed frame time), oldest first.
    private var history: [(time: Double, center: CGPoint, weight: Double)] = []

    public init(width: Double, height: Double, config: BallTrackerConfig = .init()) {
        self.config = config
        self.width = width
        self.height = height
        diagonal = hypot(width, height)
    }

    private func limit(_ dt: Double) -> Double {
        diagonal * (config.motionSlackDiagonals + config.maxMotionDiagonalsPerSecond * dt)
    }

    private func measuredVelocity(_ a: CGPoint, _ b: CGPoint, _ dt: Double) -> CGVector {
        let v = CGVector(dx: (b.x - a.x) / dt, dy: (b.y - a.y) / dt)
        let speed = hypot(v.dx, v.dy)
        let maxSpeed = diagonal * config.maxMotionDiagonalsPerSecond
        let scale = speed > 0 ? min(1, maxSpeed / speed) : 1
        return CGVector(dx: v.dx * scale, dy: v.dy * scale)
    }

    private func isValid(_ c: Detection) -> Bool {
        guard c.box.count == 4, (c.box + [c.confidence]).allSatisfy(\.isFinite) else { return false }
        let center = c.center
        return config.ballConfidence <= c.confidence && c.confidence <= 1
            && c.box[2] > c.box[0] && c.box[3] > c.box[1]
            && 0 <= center.x && center.x < width && 0 <= center.y && center.y < height
    }

    /// Drops candidates at spots that keep producing detections (leaves, debris). A spot is
    /// static when nearby candidates were first seen at least `staticMinAgeSeconds` ago and
    /// add up to `staticMinObservedSeconds` of frame time within `staticMemorySeconds`.
    /// Port of `BallTracker._without_static`.
    private mutating func withoutStatic(_ candidates: [Detection], at time: Double,
                                        previousUpdate: Double?) -> [Detection] {
        history.removeAll { time - $0.time > config.staticMemorySeconds }
        let radius = diagonal * config.staticRadiusDiagonals
        var kept: [Detection] = []
        for candidate in candidates {
            var oldest: Double?
            var observed = 0.0
            for entry in history where distance(candidate.center, entry.center) <= radius {
                if oldest == nil { oldest = entry.time }
                observed += entry.weight
            }
            if let oldest, time - oldest >= config.staticMinAgeSeconds, observed >= config.staticMinObservedSeconds {
                continue
            }
            kept.append(candidate)
        }
        let weight = previousUpdate.map { min(time - $0, config.staticMaxFrameGapSeconds) } ?? 0
        // Record every valid candidate, including suppressed ones, so clutter stays known.
        history += candidates.map { (time, $0.center, weight) }
        return kept
    }

    /// Selects this frame's ball from raw ball candidates (in detector order).
    /// Times must be finite and strictly increasing.
    public mutating func select(_ candidates: [Detection], at time: Double) throws -> TrackedBall? {
        if !time.isFinite || (lastUpdate.map { time <= $0 } ?? false) {
            throw BallTrackerError.nonIncreasingTime(time)
        }
        let previousUpdate = lastUpdate
        lastUpdate = time
        let candidates = withoutStatic(candidates.filter(isValid), at: time, previousUpdate: previousUpdate)
        let window = config.confirmationWindowSeconds
        pending.removeAll { time - $0.time > window }
        if let last, time - last.time > config.candidateResetSeconds {
            self.last = nil
            anchor = nil
        }

        if let last {
            let dt = time - last.time
            let lastCenter = last.ball.center
            let possible = candidates.filter { distance($0.center, lastCenter) <= limit(dt) }
            let prediction = CGPoint(x: lastCenter.x + velocity.dx * dt, y: lastCenter.y + velocity.dy * dt)
            let radius = diagonal * (config.predictionSlackDiagonals
                                     + 0.5 * config.maxAccelerationDiagonalsPerSecond2 * dt * dt)
            let nearPrediction = possible.filter { distance($0.center, prediction) <= radius }
            // A paddle impact or bounce can abruptly invalidate the velocity.
            // Only allow this fallback over short gaps, within the speed gate.
            let turning = nearPrediction.isEmpty && dt <= config.turnWindowSeconds
            let pool = !nearPrediction.isEmpty ? nearPrediction : (turning ? possible : [])
            if !pool.isEmpty {
                let target = turning ? lastCenter : prediction
                let scale = turning ? limit(dt) : radius
                // First minimum wins on ties, like Python's min().
                var selected = pool[0]
                var bestScore = Double.infinity
                for c in pool {
                    let score = distance(c.center, target) / scale - config.confidenceWeight * c.confidence
                    if score < bestScore { bestScore = score; selected = c }
                }
                let anchor = self.anchor!
                if distance(selected.center, anchor.center) > diagonal * config.stationaryRadiusDiagonals {
                    self.anchor = (time, selected.center)
                } else if time - anchor.time >= config.stationaryTimeoutSeconds {
                    // Stop following stationary clutter; require fresh moving evidence.
                    self.last = nil
                    self.anchor = nil
                    pending = candidates.map { (time, $0) }
                    return nil
                }
                let measured = measuredVelocity(lastCenter, selected.center, dt)
                let weight = turning ? 1.0 : 1 - exp(-dt / config.velocitySmoothingSeconds)
                velocity = CGVector(dx: (1 - weight) * velocity.dx + weight * measured.dx,
                                    dy: (1 - weight) * velocity.dy + weight * measured.dy)
                let ball = TrackedBall(detection: selected, trackID: last.ball.trackID)
                self.last = (time, ball)
                pending.removeAll()
                return ball
            }
            // Hold state over a short loss without inventing an observation.
            pending += candidates.map { (time, $0) }
            return nil
        }

        // Keep alternative seeds so a high-confidence stationary sign cannot
        // prevent a lower-confidence moving ball from being acquired.
        var best: (time: Double, seed: Detection, current: Detection)?
        var bestScore = -Double.infinity
        for (seedTime, seed) in pending {
            for current in candidates {
                let d = distance(seed.center, current.center)
                guard diagonal * config.minConfirmationMotionDiagonals <= d, d <= limit(time - seedTime) else { continue }
                let score = (seed.confidence + current.confidence) / 2
                    - config.confidenceWeight * (time - seedTime) / window
                if score > bestScore { bestScore = score; best = (seedTime, seed, current) }  // first maximum
            }
        }
        if let best {
            velocity = measuredVelocity(best.seed.center, best.current.center, time - best.time)
            let ball = TrackedBall(detection: best.current, trackID: nextID)
            nextID += 1
            last = (time, ball)
            anchor = (time, ball.center)
            pending.removeAll()
            return ball
        }
        pending += candidates.map { (time, $0) }
        return nil
    }
}

@inline(__always) func distance(_ a: CGPoint, _ b: CGPoint) -> Double { hypot(b.x - a.x, b.y - a.y) }
