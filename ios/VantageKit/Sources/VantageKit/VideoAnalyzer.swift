import AVFoundation
import CoreImage
import Foundation

public struct AnalysisResult: Sendable {
    public let frames: Int
    /// Frames with at least one raw ball candidate.
    public let ballFrames: Int
    /// Frames where the ball tracker selected a measured ball.
    public let trackedBallFrames: Int
    public let averageMilliseconds: Double
    public let width: Double
    public let height: Double
    public let durationSeconds: Double
}

public actor VideoAnalyzer {
    public init() {}

    /// Maps a track's preferredTransform (defined in top-left/y-down coordinates) to the
    /// equivalent image orientation. Applying the transform directly to a CIImage (y-up)
    /// rotates portrait video 180° from what AVPlayer displays.
    public static func orientation(for transform: CGAffineTransform) -> CGImagePropertyOrientation {
        switch Int((atan2(transform.b, transform.a) * 180 / .pi).rounded()) {
        case 90: return .right
        case -90: return .left
        case 180, -180: return .down
        default: return .up
        }
    }

    /// Writes one `FrameDetections` JSON line per decoded frame to `destination`.
    /// The file is removed if analysis fails or is cancelled.
    public func analyze(video: URL, model: URL, destination: URL,
                 progress: @Sendable (Double) async -> Void) async throws -> AnalysisResult {
        let detector = try Detector(url: model)
        let asset = AVURLAsset(url: video)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw AnalysisError.message("No video track found.")
        }
        let orientation = VideoAnalyzer.orientation(for: try await track.load(.preferredTransform))
        let duration = try await asset.load(.duration).seconds
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ])
        guard reader.canAdd(output) else { throw AnalysisError.message("Unsupported video format.") }
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? AnalysisError.message("Cannot decode video.") }
        FileManager.default.createFile(atPath: destination.path, contents: nil)
        let file = try FileHandle(forWritingTo: destination)
        defer { try? file.close(); reader.cancelReading() }
        var frames = 0, ballFrames = 0, trackedBallFrames = 0
        var tracker: BallTracker?
        var totalMilliseconds = 0.0
        var size = CGSize.zero
        let encoder = JSONEncoder()
        do {
            while let sample = output.copyNextSampleBuffer() {
                try Task.checkCancellation()
                guard let buffer = CMSampleBufferGetImageBuffer(sample) else { continue }
                let time = CMSampleBufferGetPresentationTimeStamp(sample).seconds
                guard time.isFinite else { throw AnalysisError.message("Invalid video timestamp.") }
                let record: FrameDetections = try autoreleasepool {
                    let image = CIImage(cvPixelBuffer: buffer).oriented(orientation)
                    let start = CFAbsoluteTimeGetCurrent()
                    let detections = try detector.detect(image)
                    return FrameDetections(timeSeconds: time, width: image.extent.width, height: image.extent.height,
                        inferenceMilliseconds: (CFAbsoluteTimeGetCurrent()-start)*1000, detections: detections)
                }
                size = CGSize(width: record.width, height: record.height)
                try file.write(contentsOf: encoder.encode(record))
                try file.write(contentsOf: Data([10]))
                frames += 1
                let balls = record.balls
                ballFrames += balls.isEmpty ? 0 : 1
                if tracker == nil { tracker = BallTracker(width: record.width, height: record.height) }
                // Non-increasing timestamps only skip tracking for that frame.
                let selected: TrackedBall? = (try? tracker!.select(balls, at: time)) ?? nil
                trackedBallFrames += selected == nil ? 0 : 1
                totalMilliseconds += record.inferenceMilliseconds
                if frames % 10 == 0 { await progress(duration > 0 ? min(1, max(0, time/duration)) : 0) }
            }
            guard reader.status == .completed else { throw reader.error ?? AnalysisError.message("Video decoding stopped.") }
            guard frames > 0 else { throw AnalysisError.message("No frames decoded.") }
            await progress(1)
            return AnalysisResult(frames: frames, ballFrames: ballFrames, trackedBallFrames: trackedBallFrames,
                                  averageMilliseconds: totalMilliseconds/Double(frames),
                                  width: size.width, height: size.height, durationSeconds: duration)
        } catch {
            // Never present a truncated run as a completed export.
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }
}
