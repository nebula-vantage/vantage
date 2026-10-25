import Foundation

// Contract between the analysis engine (fills these) and the app (reads them).
//
// Per run folder (Documents/Runs/<id>/):
//   calibration.json  written by the app when the user marks the court corners, before analysis
//   stats.json        written after analysis from detections.jsonl + calibration.json
//
// Engine entry point (VantageKit), pure so stats can be recomputed from saved detections:
//   GameStats.compute(frames: [FrameDetections], calibration: CourtCalibration) throws -> GameStats
//
// Conventions: times in seconds from the start of the video (source timestamps), court
// positions in metres, speeds in km/h, fractions 0...1. A value that can't be measured is
// nil, never 0. JSON keys are snake_case, matching the desktop pipeline's stats.json.

/// A point in source-video pixels: top-left origin, same oriented image as detections.jsonl.
public struct PixelPoint: Codable, Sendable, Hashable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
}

/// A point on the court plane in metres. Origin at the near-left outer corner, x across the
/// court, y toward the far baseline (same axes as the desktop pipeline).
public struct CourtPoint: Codable, Sendable, Hashable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
}

/// The four outer court corners the user taps on the first frame.
public struct CourtCalibration: Codable, Sendable, Hashable {
    public static let fileName = "calibration.json"
    public var nearLeft: PixelPoint
    public var nearRight: PixelPoint
    public var farRight: PixelPoint
    public var farLeft: PixelPoint
    /// Size of the frame the corners were marked on.
    public var imageWidth: Double
    public var imageHeight: Double

    public init(nearLeft: PixelPoint, nearRight: PixelPoint, farRight: PixelPoint, farLeft: PixelPoint,
                imageWidth: Double, imageHeight: Double) {
        self.nearLeft = nearLeft; self.nearRight = nearRight
        self.farRight = farRight; self.farLeft = farLeft
        self.imageWidth = imageWidth; self.imageHeight = imageHeight
    }
}

/// Court geometry for drawing the top-down court and placing bounces.
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

public struct GameStats: Codable, Sendable, Hashable {
    public static let fileName = "stats.json"
    public static let currentSchemaVersion = 1

    public var schemaVersion: Int
    public var court: CourtDimensions
    /// Net crossings with continuous ball evidence (the pipeline's shot_count).
    public var shotCount: Int
    public var rallies: [Rally]
    /// Time-weighted average court-plane ball speed. Nil when there isn't enough evidence.
    public var averageBallSpeedKmh: Double?
    /// Bounce candidates with in/out calls; the landing dots on the court diagram.
    public var bounces: [Bounce]
    /// Per-track movement. Track IDs aren't player identities and can split mid-game.
    public var players: [PlayerTrack]
    public var quality: Quality
}

public struct Rally: Codable, Sendable, Hashable, Identifiable {
    public var id: Int
    public var startS: Double
    public var endS: Double
    /// Net crossings in this rally.
    public var shots: Int
}

public struct Bounce: Codable, Sendable, Hashable {
    public enum Call: String, Codable, Sendable { case inBounds = "IN", out = "OUT" }
    public var timeS: Double
    public var court: CourtPoint
    public var call: Call
    /// Within the line tolerance of a boundary: show the call as uncertain.
    public var nearBoundary: Bool
}

public struct PlayerTrack: Codable, Sendable, Hashable, Identifiable {
    public var id: Int
    /// Observed distance covered. Nil when the track never had a valid court position.
    public var distanceM: Double?
    /// How long the track was visible.
    public var visibleS: Double
}

public struct Quality: Codable, Sendable, Hashable {
    public enum Status: String, Codable, Sendable {
        case insufficientEvidence = "insufficient_evidence"
        case limitedEvidence = "limited_evidence"
        case heuristic
    }
    public var status: Status
    /// Frames with an observed (not interpolated) ball: the "% of frames tracked" in the UI.
    public var ballTrackedFraction: Double
    /// Human-readable caveats to show under the stats.
    public var warnings: [String]
}

// MARK: - Derived values the UI shows (computed here, not stored)

extension GameStats {
    public var rallyCount: Int { rallies.count }
    public var longestRally: Int { rallies.map(\.shots).max() ?? 0 }
    public var averageShotsPerRally: Double? {
        rallies.isEmpty ? nil : Double(rallies.reduce(0) { $0 + $1.shots }) / Double(rallies.count)
    }
    public var inCount: Int { bounces.filter { $0.call == .inBounds }.count }
    public var outCount: Int { bounces.filter { $0.call == .out }.count }
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
    public static let sample = GameStats(
        schemaVersion: currentSchemaVersion,
        court: .pickleball,
        shotCount: 46,
        rallies: [
            Rally(id: 1, startS: 3.2, endS: 14.8, shots: 9),
            Rally(id: 2, startS: 21.0, endS: 27.5, shots: 5),
            Rally(id: 3, startS: 33.1, endS: 58.4, shots: 18),
            Rally(id: 4, startS: 64.0, endS: 79.9, shots: 14),
        ],
        averageBallSpeedKmh: 31.4,
        bounces: [
            Bounce(timeS: 5.1, court: CourtPoint(x: 1.8, y: 11.2), call: .inBounds, nearBoundary: false),
            Bounce(timeS: 9.7, court: CourtPoint(x: 4.9, y: 2.3), call: .inBounds, nearBoundary: false),
            Bounce(timeS: 24.6, court: CourtPoint(x: 6.15, y: 10.4), call: .out, nearBoundary: true),
            Bounce(timeS: 41.2, court: CourtPoint(x: 3.0, y: 12.9), call: .inBounds, nearBoundary: false),
            Bounce(timeS: 57.9, court: CourtPoint(x: 0.4, y: 14.1), call: .out, nearBoundary: false),
        ],
        players: [
            PlayerTrack(id: 1, distanceM: 212.5, visibleS: 78.0),
            PlayerTrack(id: 2, distanceM: 187.0, visibleS: 74.5),
        ],
        quality: Quality(status: .heuristic, ballTrackedFraction: 0.62,
                         warnings: ["Speed is a court-plane projection, not true airborne ball speed."]))
}
