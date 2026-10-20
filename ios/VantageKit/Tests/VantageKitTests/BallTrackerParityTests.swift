import Foundation
import XCTest
@testable import VantageKit

/// Replays raw ball candidates from real on-device runs and requires the exact per-frame
/// selections, track IDs, and interpolated frames produced by the desktop Python tracker.
/// Regenerate fixtures with tools/coreml/make_tracker_fixtures.py.
final class BallTrackerParityTests: XCTestCase {
    struct Fixture: Decodable {
        struct Frame: Decodable {
            let t: Double
            let candidates: [[Double]]
            /// [x1, y1, x2, y2, confidence, trackID]
            let ball: [Double]?
            let interpolated_track: Int?
        }
        let name: String
        let width: Double
        let height: Double
        let config: BallTrackerConfig
        let frames: [Frame]
    }

    static func fixtures() throws -> [Fixture] {
        let folder = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures", withExtension: nil))
        let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("tracker-") }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        return try files.map { try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: $0)) }
    }

    func testFixturesPresent() throws {
        XCTAssertGreaterThanOrEqual(try Self.fixtures().count, 3)
    }

    /// The Swift defaults must equal the desktop config.py values the fixtures were made with.
    func testDefaultConfigMatchesDesktop() throws {
        for fixture in try Self.fixtures() {
            XCTAssertEqual(fixture.config, BallTrackerConfig(), "config drift vs desktop (\(fixture.name))")
        }
    }

    func testSelectionsMatchPythonExactly() throws {
        for fixture in try Self.fixtures() {
            var tracker = BallTracker(width: fixture.width, height: fixture.height)
            var mismatches: [String] = []
            for (index, frame) in fixture.frames.enumerated() {
                let candidates = frame.candidates.map {
                    Detection(classID: DetectionClass.ball, confidence: $0[4], box: Array($0[0..<4]))
                }
                let selected = try tracker.select(candidates, at: frame.t)
                let actual = selected.map { $0.detection.box + [$0.detection.confidence, Double($0.trackID)] }
                if actual != frame.ball {
                    mismatches.append("frame \(index): swift \(String(describing: actual)) python \(String(describing: frame.ball))")
                }
            }
            XCTAssertTrue(mismatches.isEmpty,
                          "\(fixture.name): \(mismatches.count) mismatches\n" + mismatches.prefix(10).joined(separator: "\n"))
        }
    }

    func testInterpolatedFramesMatchPython() throws {
        for fixture in try Self.fixtures() {
            let frames = fixture.frames.map { frame in
                FrameDetections(timeSeconds: frame.t, width: fixture.width, height: fixture.height,
                                inferenceMilliseconds: 0, detections: frame.candidates.map {
                                    Detection(classID: DetectionClass.ball, confidence: $0[4], box: Array($0[0..<4]))
                                })
            }
            let samples = BallTrajectory.samples(frames: frames, tracked: BallTrajectory.track(frames))
            let swift = samples.map { $0?.source == .interpolated ? $0?.trackID : nil }
            XCTAssertEqual(swift, fixture.frames.map(\.interpolated_track), fixture.name)
        }
    }
}
