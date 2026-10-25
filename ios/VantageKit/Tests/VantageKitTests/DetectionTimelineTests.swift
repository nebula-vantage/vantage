import CoreGraphics
import XCTest
@testable import VantageKit

final class DetectionTimelineTests: XCTestCase {
    private func frame(_ t: Double, _ detections: [Detection] = []) -> FrameDetections {
        FrameDetections(timeSeconds: t, width: 640, height: 360, inferenceMilliseconds: 1, detections: detections)
    }
    private func ball(_ x: Double, confidence: Double = 0.5) -> Detection {
        Detection(classID: DetectionClass.ball, confidence: confidence, box: [x - 2, 98, x + 2, 102])
    }

    /// 30 fps: a moving ball for 1 s (with a static low-confidence distractor), then a 1 s gap,
    /// then 1 s of frames without balls.
    private lazy var timeline: DetectionTimeline = {
        var frames = (0..<30).map { frame(Double($0) / 30, [ball(100 + Double($0) * 5), ball(600, confidence: 0.2)]) }
        frames += (60..<90).map { frame(Double($0) / 30) }
        return DetectionTimeline(frames: frames.shuffled())
    }()

    func testFrameLookup() {
        XCTAssertEqual(timeline.frameInterval, 1.0 / 30, accuracy: 1e-9)
        XCTAssertNil(timeline.frameIndex(at: -0.01))
        XCTAssertEqual(timeline.frameIndex(at: 0), 0)
        XCTAssertEqual(timeline.frameIndex(at: 10.0 / 30 + 0.001), 10)
        XCTAssertEqual(timeline.frameIndex(at: 11.0 / 30 - 1e-7), 11, "float rounding just before a frame")
        XCTAssertEqual(timeline.frameIndex(at: 11.0 / 30 - 0.02), 10, "mid-interval stays on previous frame")
        XCTAssertNil(timeline.frameIndex(at: 1.5), "inside a long gap")
        XCTAssertNil(timeline.frameIndex(at: 3.1), "after the last frame")
    }

    func testTrackingIgnoresStaticDistractor() {
        // Acquisition needs two moving observations, so frame 0 has no tracked ball.
        XCTAssertNil(timeline.ballSamples[0])
        XCTAssertEqual(timeline.trackedFrameCount, 29)
        XCTAssertEqual(timeline.trackCount, 1)
        XCTAssertTrue(timeline.ballSamples[1...29].allSatisfy { $0?.center.x ?? 0 < 600 })
    }

    func testTrailFollowsOneTrackWithinWindow() {
        let trail = timeline.ballTrail(endingAt: 29, window: 0.5)
        XCTAssertEqual(trail.count, 16)
        XCTAssertEqual(trail.last?.recency, 1)
        XCTAssertEqual(trail.last?.center, CGPoint(x: 245, y: 100))
        XCTAssertTrue(timeline.ballTrail(endingAt: 30, window: 0.5).isEmpty, "no trail across a long gap")
    }

    func testShortGapIsInterpolatedWithinTrack() {
        // Frames 3-4 have no candidate; the 0.1 s gap is bridged as interpolated.
        let frames = (0..<10).map { i in frame(Double(i) / 30, (3...4).contains(i) ? [] : [ball(100 + Double(i) * 10)]) }
        let timeline = DetectionTimeline(frames: frames)
        XCTAssertEqual(timeline.ballSamples[3]?.source, .interpolated)
        XCTAssertEqual(timeline.ballSamples[3]?.center.x ?? 0, 130, accuracy: 1e-9)
        XCTAssertNil(timeline.ballSamples[3]?.confidence)
        XCTAssertEqual(timeline.ballSamples[5]?.source, .observed)
        XCTAssertEqual(timeline.ballTrail(endingAt: 5, window: 0.5).map(\.source),
                       [.observed, .observed, .interpolated, .interpolated, .observed])
    }

    func testJSONLRoundTrip() throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "timeline-\(UUID()).jsonl")
        defer { try? FileManager.default.removeItem(at: url) }
        let frames = (0..<5).map { frame(Double($0) / 30, [ball(100 + Double($0) * 5)]) }
        let encoder = JSONEncoder()
        let data = try frames.map { try encoder.encode($0) + Data([10]) }.reduce(Data(), +)
        try data.write(to: url)
        let loaded = try DetectionTimeline(contentsOf: url)
        XCTAssertEqual(loaded.frames.count, 5)
        XCTAssertEqual(loaded.frames[4].detections, frames[4].detections)
    }
}
