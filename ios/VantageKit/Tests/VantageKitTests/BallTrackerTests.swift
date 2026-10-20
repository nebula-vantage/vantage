import CoreGraphics
import XCTest
@testable import VantageKit

/// Behavioral tests ported one-to-one from the desktop tests/test_ball_tracker.py.
final class BallTrackerTests: XCTestCase {
    private var tracker = BallTracker(width: 640, height: 360)

    private func ball(_ x: Double, _ y: Double = 100, confidence: Double = 0.2) -> Detection {
        Detection(classID: DetectionClass.ball, confidence: confidence, box: [x - 2, y - 2, x + 2, y + 2])
    }
    private func select(_ candidates: [Detection], _ time: Double) -> TrackedBall? {
        try! tracker.select(candidates, at: time)
    }

    override func setUp() { tracker = BallTracker(width: 640, height: 360) }

    func testLowConfidenceFastBallNeedsNoBoxOverlap() {
        XCTAssertNil(select([ball(100, confidence: 0.11)], 0))
        let observed = (1...5).map { i in select([ball(100 + Double(i) * 25, confidence: 0.11)], Double(i) / 30) }
        XCTAssertTrue(observed.allSatisfy { $0 != nil })
        XCTAssertEqual(Set(observed.map { $0!.trackID }).count, 1)
        XCTAssertEqual(observed.last!!.center, CGPoint(x: 225, y: 100))
        XCTAssertEqual(observed.last!!.detection.confidence, 0.11)
    }

    func testShortLossReturnsNoFabricatedDetectionAndRejoins() {
        _ = select([ball(100)], 0)
        let first = select([ball(110)], 1.0 / 30)
        XCTAssertNil(select([], 2.0 / 30))
        XCTAssertNil(select([], 3.0 / 30))
        let last = select([ball(140)], 4.0 / 30)
        XCTAssertEqual(first?.trackID, last?.trackID)
        XCTAssertEqual(last?.center, CGPoint(x: 140, y: 100))
    }

    func testLongLossRequiresConfirmationAndNewIdentity() {
        _ = select([ball(100)], 0)
        let first = select([ball(110)], 1.0 / 30)
        XCTAssertNil(select([], 0.5))
        XCTAssertNil(select([ball(400)], 0.6))
        let last = select([ball(410)], 0.6 + 1.0 / 30)
        XCTAssertNotNil(last)
        XCTAssertNotEqual(first?.trackID, last?.trackID)
    }

    func testStationaryHighConfidenceSignCannotBlockAcquisition() {
        let sign = ball(500, confidence: 0.99)
        for i in 0..<10 { XCTAssertNil(select([sign], Double(i) / 30)) }
        XCTAssertNil(select([sign, ball(100)], 10.0 / 30))
        XCTAssertEqual(select([sign, ball(110)], 11.0 / 30)?.center, CGPoint(x: 110, y: 100))
    }

    func testMotionWinsOverHigherConfidenceDistractor() {
        _ = select([ball(100)], 0)
        _ = select([ball(120)], 1.0 / 30)
        XCTAssertEqual(select([ball(140), ball(110, confidence: 0.99)], 2.0 / 30)?.center, CGPoint(x: 140, y: 100))
    }

    func testAbruptReversalKeepsIdentity() {
        _ = select([ball(100)], 0)
        let before = select([ball(130)], 1.0 / 30)
        let after = select([ball(100)], 2.0 / 30)
        XCTAssertNotNil(before)
        XCTAssertEqual(before?.trackID, after?.trackID)
        XCTAssertEqual(select([ball(70)], 3.0 / 30)?.trackID, before?.trackID)
    }

    func testImpossibleJumpAndInvalidBoxesRejected() {
        _ = select([ball(100)], 0)
        _ = select([ball(110)], 1.0 / 30)
        XCTAssertNil(select([ball(600)], 2.0 / 30))
        XCTAssertNil(select([ball(.nan), ball(-20), ball(120, confidence: 0.09),
                             Detection(classID: DetectionClass.ball, confidence: 0.9, box: [120, 100, 119, 102])],
                            3.0 / 30))
    }

    func testStationaryTrackIsReleased() {
        _ = select([ball(100)], 0)
        _ = select([ball(110)], 1.0 / 30)
        let observed = (2..<25).map { select([ball(110)], Double($0) / 30) }
        XCTAssertTrue(observed.suffix(5).allSatisfy { $0 == nil })
    }

    func testAcquisitionRequiresDistinctIncreasingTimes() {
        XCTAssertNil(select([ball(100), ball(110)], 0))
        for time in [0, -1, Double.nan] {
            XCTAssertThrowsError(try tracker.select([ball(120)], at: time))
        }
    }

    func testPersistentStaticClutterIsSuppressed() {
        let leaf = { (i: Int) in self.ball(500 + Double(i % 2), confidence: 0.3) }
        let selected = (0..<90).map { select([leaf($0)], Double($0) / 30) }
        XCTAssertTrue(selected[31...].allSatisfy { $0 == nil })
        XCTAssertNil(select([leaf(90), ball(100)], 90.0 / 30))
        XCTAssertEqual(select([leaf(91), ball(115)], 91.0 / 30)?.center, CGPoint(x: 115, y: 100))
    }

    func testBallCrossingSameSpotTwiceIsNotSuppressed() {
        let xs = (0..<60).map { i in 100 + 8 * Double(i < 30 ? i : 59 - i) }
        let selected = xs.enumerated().map { select([ball($1)], Double($0) / 30) }
        XCTAssertEqual(selected.compactMap { $0 }.count, 59)
        XCTAssertEqual(Set(selected.compactMap { $0?.trackID }).count, 1)
    }

    func testStaticSuppressionIsFrameRateIndependent() {
        for fps in [30, 120] {
            var tracker = BallTracker(width: 640, height: 360)
            for i in 0..<(2 * fps) { _ = try! tracker.select([ball(500, confidence: 0.3)], at: Double(i) / Double(fps)) }
            // The leaf is suppressed; a new ball at another spot is a valid seed (no selection yet).
            XCTAssertNil(try! tracker.select([ball(500), ball(100)], at: 2 + 1 / Double(fps)))
            XCTAssertEqual(try! tracker.select([ball(500), ball(110)], at: 2 + 2 / Double(fps))?.center,
                           CGPoint(x: 110, y: 100), "fps \(fps)")
        }
    }

    func testCaptureFPSDoesNotChangeSpeedOrGapLifetime() {
        for fps in [30, 120] {
            var tracker = BallTracker(width: 640, height: 360)
            var frames: [FrameDetections] = []
            var tracked: [TrackedBall?] = []
            for i in 0..<fps {
                let time = Double(i) / Double(fps)
                let candidate = ball(100 + 120 * time)
                tracked.append(try! tracker.select([candidate], at: time))
                frames.append(FrameDetections(timeSeconds: time, width: 640, height: 360,
                                              inferenceMilliseconds: 0, detections: [candidate]))
            }
            XCTAssertEqual(tracker.velocity.dx, 120, accuracy: 1e-6)
            let ids = Set(tracked.compactMap { $0?.trackID })
            XCTAssertEqual(ids.count, 1)
            let samples = BallTrajectory.samples(frames: frames, tracked: tracked)
            XCTAssertTrue(samples.compactMap { $0 }.allSatisfy { $0.source == .observed })
            XCTAssertNil(try! tracker.select([], at: 1.3))
            XCTAssertNil(try! tracker.select([ball(300)], at: 1.4))
        }
    }
}
