import Foundation

// Contract between the analysis engine (fills these) and the app (reads them).
//
// stats.json has the same keys and shapes as the desktop pipeline's stats.json (schema 2):
// everything pipeline/vantage/stats.py `aggregate` writes, plus `motion` from motion_stream.py.
// The desktop's provenance keys (input, model, source, tracking, tracks_sha256, analysis_config,
// landing_heatmap, video.encoded_*) and motion.hit_candidates aren't part of the contract;
// decoding ignores them, so a desktop stats.json still decodes.
// calibration.json has the shape pipeline/vantage/court.py `save_calibration` writes.
//
// Per run folder (Documents/Runs/<id>/):
//   calibration.json  written by the app when the user marks the court corners, before analysis
//   stats.json        written after analysis from detections.jsonl + calibration.json
//
// Engine entry point (VantageKit), pure so stats can be recomputed from saved detections:
//   GameStats.compute(frames: [FrameDetections], calibration: CourtCalibration) throws -> GameStats
//
// Conventions (the pipeline's): times in seconds from the start of the video; points are [x, y]
// arrays; court positions in metres, origin at the near-left outer corner, x across the court,
// y toward the far baseline; speeds in km/h; fractions 0...1. A value that can't be measured is
// null (avg_ball_speed_kmh). Counts are 0 when nothing was found; quality.status says whether
// there was enough evidence for a 0 to mean anything.

/// A point in source-video pixels, top-left origin, same oriented image as detections.jsonl.
/// Encoded as `[x, y]`.
public struct PixelPoint: Codable, Sendable, Hashable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
    public init(from decoder: Decoder) throws { (x, y) = try decodePair(decoder) }
    public func encode(to encoder: Encoder) throws { try encodePair(x, y, to: encoder) }
}

/// A point on the court plane in metres (origin near-left outer corner). Encoded as `[x, y]`.
public struct CourtPoint: Codable, Sendable, Hashable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
    public init(from decoder: Decoder) throws { (x, y) = try decodePair(decoder) }
    public func encode(to encoder: Encoder) throws { try encodePair(x, y, to: encoder) }
}

private func decodePair(_ decoder: Decoder) throws -> (Double, Double) {
    var container = try decoder.unkeyedContainer()
    let pair = (try container.decode(Double.self), try container.decode(Double.self))
    guard container.isAtEnd else {
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "Expected [x, y].")
    }
    return pair
}

private func encodePair(_ x: Double, _ y: Double, to encoder: Encoder) throws {
    var container = encoder.unkeyedContainer()
    try container.encode(x)
    try container.encode(y)
}

/// The four outer court corners the user marks on the first frame.
public struct CourtCalibration: Codable, Sendable, Hashable {
    public static let fileName = "calibration.json"
    /// Size of the frame the corners were marked on.
    public var width: Int
    public var height: Int
    /// Near-left, near-right, far-right, far-left.
    public var corners: [PixelPoint]

    public init(width: Int, height: Int, corners: [PixelPoint]) {
        self.width = width; self.height = height; self.corners = corners
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        width = try container.decode(Int.self, forKey: .width)
        height = try container.decode(Int.self, forKey: .height)
        corners = try container.decode([PixelPoint].self, forKey: .corners)
        guard corners.count == 4 else {
            throw DecodingError.dataCorruptedError(forKey: .corners, in: container,
                                                   debugDescription: "Expected 4 corners, got \(corners.count).")
        }
    }

    public var nearLeft: PixelPoint { corners[0] }
    public var nearRight: PixelPoint { corners[1] }
    public var farRight: PixelPoint { corners[2] }
    public var farLeft: PixelPoint { corners[3] }
}

public struct GameStats: Codable, Sendable, Hashable {
    public static let fileName = "stats.json"
    public static let currentSchemaVersion = 2

    public var schemaVersion: Int
    public var video: VideoInfo
    public var rallyCount: Int
    /// Net crossings with uninterrupted observed ball support.
    public var shotCount: Int
    public var crossingEvents: [CrossingEvent]
    public var shotsPerRally: [Int]
    /// 0 when there are no rallies.
    public var longestRally: Int
    /// Time-weighted average court-plane ball speed. Nil without enough consecutive observations.
    public var avgBallSpeedKmh: Double?
    /// Bounce candidates with IN/OUT calls: the landing dots.
    public var inOutCalls: [Bounce]
    public var bounceCandidateCount: Int
    public var rallies: [Rally]
    public var trackingSummary: TrackingSummary
    public var quality: Quality
    /// Per-track player movement.
    public var motion: Motion

    public init(schemaVersion: Int = currentSchemaVersion, video: VideoInfo, rallyCount: Int, shotCount: Int,
                crossingEvents: [CrossingEvent], shotsPerRally: [Int], longestRally: Int,
                avgBallSpeedKmh: Double?, inOutCalls: [Bounce], bounceCandidateCount: Int, rallies: [Rally],
                trackingSummary: TrackingSummary, quality: Quality, motion: Motion) {
        self.schemaVersion = schemaVersion; self.video = video
        self.rallyCount = rallyCount; self.shotCount = shotCount
        self.crossingEvents = crossingEvents; self.shotsPerRally = shotsPerRally
        self.longestRally = longestRally; self.avgBallSpeedKmh = avgBallSpeedKmh
        self.inOutCalls = inOutCalls; self.bounceCandidateCount = bounceCandidateCount
        self.rallies = rallies; self.trackingSummary = trackingSummary
        self.quality = quality; self.motion = motion
    }
}

public struct VideoInfo: Codable, Sendable, Hashable {
    public var width: Int
    public var height: Int
    public var fps: Double
    public var frameCount: Int
    public var durationS: Double

    public init(width: Int, height: Int, fps: Double, frameCount: Int, durationS: Double) {
        self.width = width; self.height = height; self.fps = fps
        self.frameCount = frameCount; self.durationS = durationS
    }
}

/// The ball crossing the net (a shot).
public struct CrossingEvent: Codable, Sendable, Hashable {
    public var frameIndex: Int
    public var timeS: Double

    public init(frameIndex: Int, timeS: Double) { self.frameIndex = frameIndex; self.timeS = timeS }
}

public struct Rally: Codable, Sendable, Hashable, Identifiable {
    public var id: Int
    public var startS: Double
    public var endS: Double
    public var crossingTimesS: [Double]
    /// Net crossings in this rally.
    public var shots: Int
    public var durationS: Double
    /// Share of the rally's frames with an observed ball.
    public var ballObservationCoverage: Double
    /// "heuristic_rally", "low_ball_coverage".
    public var qualityFlags: [String]

    public init(id: Int, startS: Double, endS: Double, crossingTimesS: [Double], shots: Int, durationS: Double,
                ballObservationCoverage: Double, qualityFlags: [String]) {
        self.id = id; self.startS = startS; self.endS = endS; self.crossingTimesS = crossingTimesS
        self.shots = shots; self.durationS = durationS
        self.ballObservationCoverage = ballObservationCoverage; self.qualityFlags = qualityFlags
    }
}

public struct Bounce: Codable, Sendable, Hashable {
    public enum Call: String, Codable, Sendable { case inBounds = "IN", out = "OUT" }
    public var frameIndex: Int
    public var timeS: Double
    public var pixel: PixelPoint
    public var court: CourtPoint
    public var call: Call
    public var fitImprovement: Double
    /// "heuristic_bounce", "near_boundary".
    public var qualityFlags: [String]

    public init(frameIndex: Int, timeS: Double, pixel: PixelPoint, court: CourtPoint, call: Call,
                fitImprovement: Double, qualityFlags: [String]) {
        self.frameIndex = frameIndex; self.timeS = timeS; self.pixel = pixel; self.court = court
        self.call = call; self.fitImprovement = fitImprovement; self.qualityFlags = qualityFlags
    }

    /// Within the line tolerance of a boundary: show the call as uncertain.
    public var nearBoundary: Bool { qualityFlags.contains("near_boundary") }
}

/// Observation coverage and per-track visibility. Track IDs aren't player identities and can
/// split mid-game.
public struct TrackingSummary: Codable, Sendable, Hashable {
    public struct PlayerTrack: Codable, Sendable, Hashable {
        public var trackId: Int
        public var firstSeenS: Double
        public var lastSeenS: Double
        public var observedFrames: Int
        public var observedDurationS: Double

        public init(trackId: Int, firstSeenS: Double, lastSeenS: Double, observedFrames: Int,
                    observedDurationS: Double) {
            self.trackId = trackId; self.firstSeenS = firstSeenS; self.lastSeenS = lastSeenS
            self.observedFrames = observedFrames; self.observedDurationS = observedDurationS
        }
    }
    public var playerDetectionCoverage: Double
    public var framesWithPlayers: Int
    public var maxSimultaneousPlayerDetections: Int
    public var playerTrackCount: Int
    public var playerTracks: [PlayerTrack]
    public var ballTrackCount: Int
    public var longestContiguousBallObservationS: Double

    public init(playerDetectionCoverage: Double, framesWithPlayers: Int, maxSimultaneousPlayerDetections: Int,
                playerTrackCount: Int, playerTracks: [PlayerTrack], ballTrackCount: Int,
                longestContiguousBallObservationS: Double) {
        self.playerDetectionCoverage = playerDetectionCoverage; self.framesWithPlayers = framesWithPlayers
        self.maxSimultaneousPlayerDetections = maxSimultaneousPlayerDetections
        self.playerTrackCount = playerTrackCount; self.playerTracks = playerTracks
        self.ballTrackCount = ballTrackCount
        self.longestContiguousBallObservationS = longestContiguousBallObservationS
    }
}

public struct Quality: Codable, Sendable, Hashable {
    public enum Status: String, Codable, Sendable {
        case insufficientEvidence = "insufficient_evidence"
        case limitedEvidence = "limited_evidence"
        case heuristic
    }
    public var status: Status
    /// Frames with an observed (not interpolated) ball: the "% of frames tracked" in the UI.
    public var ballDetectionCoverage: Double
    public var observedFrames: Int
    public var interpolatedFrames: Int
    public var coastedFrames: Int
    public var interpolationFraction: Double
    public var validSpeedDurationS: Double
    public var validSpeedCoverage: Double
    /// "heuristic_court_projection".
    public var measurementType: String
    /// Human-readable caveats to show under the stats.
    public var warnings: [String]

    public init(status: Status, ballDetectionCoverage: Double, observedFrames: Int, interpolatedFrames: Int,
                coastedFrames: Int, interpolationFraction: Double, validSpeedDurationS: Double,
                validSpeedCoverage: Double, measurementType: String, warnings: [String]) {
        self.status = status; self.ballDetectionCoverage = ballDetectionCoverage
        self.observedFrames = observedFrames; self.interpolatedFrames = interpolatedFrames
        self.coastedFrames = coastedFrames; self.interpolationFraction = interpolationFraction
        self.validSpeedDurationS = validSpeedDurationS; self.validSpeedCoverage = validSpeedCoverage
        self.measurementType = measurementType; self.warnings = warnings
    }
}

/// Player movement per track, from foot points projected onto the court.
public struct Motion: Codable, Sendable, Hashable {
    public struct PlayerTrack: Codable, Sendable, Hashable {
        public var trackId: Int
        public var observedDistanceM: Double
        public var validMovementDurationS: Double

        public init(trackId: Int, observedDistanceM: Double, validMovementDurationS: Double) {
            self.trackId = trackId; self.observedDistanceM = observedDistanceM
            self.validMovementDurationS = validMovementDurationS
        }
    }
    /// "partial_per_track_footpoint_distance".
    public var measurementType: String
    public var playerTracks: [PlayerTrack]

    public init(measurementType: String, playerTracks: [PlayerTrack]) {
        self.measurementType = measurementType; self.playerTracks = playerTracks
    }
}

// MARK: - Derived values the UI shows (computed here, not stored)

extension GameStats {
    public var averageShotsPerRally: Double? {
        shotsPerRally.isEmpty ? nil : Double(shotsPerRally.reduce(0, +)) / Double(shotsPerRally.count)
    }
    public var inCount: Int { inOutCalls.filter { $0.call == .inBounds }.count }
    public var outCount: Int { inOutCalls.filter { $0.call == .out }.count }
}

// MARK: - Court geometry (app side; not in stats.json)

/// Court geometry for drawing the top-down court. Matches the pipeline's config
/// (court.width_m, court.length_m, heatmap.kitchen_depth_m; net at half length).
public struct CourtDimensions: Codable, Sendable, Hashable {
    public var widthM: Double
    public var lengthM: Double
    /// Distance of the net from the near baseline.
    public var netPositionM: Double
    /// Non-volley zone depth on each side of the net.
    public var kitchenDepthM: Double

    public static let pickleball = CourtDimensions(widthM: 6.10, lengthM: 13.41, netPositionM: 6.705,
                                                   kitchenDepthM: 2.1336)
}

// MARK: - JSON (snake_case keys, like the pipeline's stats.json)

extension GameStats {
    public static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

// MARK: - Sample data for SwiftUI previews and building the UI before the engine fills it

extension GameStats {
    public static let sample: GameStats = {
        let crossings: [[Double]] = [[4.1, 6.0, 8.2, 9.9, 11.7, 13.5, 14.0, 14.4, 14.7],
                                     [22.3, 24.0, 25.1, 26.8, 27.2],
                                     [34.0, 35.2, 36.9, 38.1, 39.6, 41.0, 42.4, 43.8, 45.1, 46.5, 47.7, 49.0,
                                      50.6, 52.1, 53.9, 55.4, 56.8, 58.0],
                                     [65.2, 66.9, 68.1, 69.4, 70.8, 72.3, 73.0, 74.6, 75.8, 76.4, 77.1, 78.0,
                                      78.9, 79.5]]
        let spans: [(Double, Double)] = [(3.2, 14.8), (21.0, 27.5), (33.1, 58.4), (64.0, 79.9)]
        let rallies = zip(spans, crossings).enumerated().map { index, pair in
            Rally(id: index + 1, startS: pair.0.0, endS: pair.0.1, crossingTimesS: pair.1, shots: pair.1.count,
                  durationS: pair.0.1 - pair.0.0, ballObservationCoverage: 0.7, qualityFlags: ["heuristic_rally"])
        }
        func bounce(_ time: Double, _ x: Double, _ y: Double, _ call: Bounce.Call, near: Bool = false) -> Bounce {
            Bounce(frameIndex: Int(time * 30), timeS: time, pixel: PixelPoint(x: 0, y: 0),
                   court: CourtPoint(x: x, y: y), call: call, fitImprovement: 0.4,
                   qualityFlags: ["heuristic_bounce"] + (near ? ["near_boundary"] : []))
        }
        let bounces = [bounce(5.1, 1.8, 11.2, .inBounds), bounce(9.7, 4.9, 2.3, .inBounds),
                       bounce(24.6, 6.15, 10.4, .out, near: true), bounce(41.2, 3.0, 12.9, .inBounds),
                       bounce(57.9, 0.4, 14.1, .out)]
        let allCrossings = crossings.flatMap { $0 }
        return GameStats(
            video: VideoInfo(width: 1920, height: 1080, fps: 30, frameCount: 2_400, durationS: 80),
            rallyCount: rallies.count, shotCount: allCrossings.count,
            crossingEvents: allCrossings.map { CrossingEvent(frameIndex: Int($0 * 30), timeS: $0) },
            shotsPerRally: rallies.map(\.shots), longestRally: rallies.map(\.shots).max() ?? 0,
            avgBallSpeedKmh: 31.4, inOutCalls: bounces, bounceCandidateCount: bounces.count, rallies: rallies,
            trackingSummary: TrackingSummary(
                playerDetectionCoverage: 0.95, framesWithPlayers: 2_280, maxSimultaneousPlayerDetections: 4,
                playerTrackCount: 2,
                playerTracks: [.init(trackId: 1, firstSeenS: 0, lastSeenS: 79.9, observedFrames: 2_340,
                                     observedDurationS: 78.0),
                               .init(trackId: 2, firstSeenS: 1.2, lastSeenS: 79.9, observedFrames: 2_235,
                                     observedDurationS: 74.5)],
                ballTrackCount: 6, longestContiguousBallObservationS: 9.4),
            quality: Quality(status: .heuristic, ballDetectionCoverage: 0.62, observedFrames: 1_488,
                             interpolatedFrames: 96, coastedFrames: 12, interpolationFraction: 0.04,
                             validSpeedDurationS: 41.0, validSpeedCoverage: 0.51,
                             measurementType: "heuristic_court_projection",
                             warnings: ["Speed is a court-plane projection, not true airborne ball speed."]),
            motion: Motion(measurementType: "partial_per_track_footpoint_distance",
                           playerTracks: [.init(trackId: 1, observedDistanceM: 212.5, validMovementDurationS: 70.2),
                                          .init(trackId: 2, observedDistanceM: 187.0, validMovementDurationS: 66.8)]))
    }()
}
