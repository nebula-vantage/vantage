import AVFoundation
import CoreImage
import Foundation

struct FrameDetections: Codable, Sendable {
    let timeSeconds: Double
    let width: Double
    let height: Double
    let inferenceMilliseconds: Double
    let detections: [BallDetection]
}

struct AnalysisResult: Sendable {
    let frames: Int
    let ballFrames: Int
    let averageMilliseconds: Double
    let file: URL
}

actor VideoAnalyzer {
    func analyze(video: URL, model: URL,
                 progress: @Sendable (Double) async -> Void) async throws -> AnalysisResult {
        let detector = try Detector(url: model)
        let asset = AVURLAsset(url: video)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw PrototypeError.message("No video track found.")
        }
        let transform = try await track.load(.preferredTransform)
        let duration = try await asset.load(.duration).seconds
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ])
        guard reader.canAdd(output) else { throw PrototypeError.message("Unsupported video format.") }
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? PrototypeError.message("Cannot decode video.") }
        let folder = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let destination = folder.appendingPathComponent("detections-\(UUID().uuidString).jsonl")
        FileManager.default.createFile(atPath: destination.path, contents: nil)
        let file = try FileHandle(forWritingTo: destination)
        defer { try? file.close(); reader.cancelReading() }
        var frames = 0, ballFrames = 0
        var totalMilliseconds = 0.0
        do {
            while let sample = output.copyNextSampleBuffer() {
                try Task.checkCancellation()
                guard let buffer = CMSampleBufferGetImageBuffer(sample) else { continue }
                let time = CMSampleBufferGetPresentationTimeStamp(sample).seconds
                guard time.isFinite else { throw PrototypeError.message("Invalid video timestamp.") }
                let record: FrameDetections = try autoreleasepool {
                    let image = CIImage(cvPixelBuffer: buffer).transformed(by: transform)
                    let start = CFAbsoluteTimeGetCurrent()
                    let detections = try detector.detect(image)
                    return FrameDetections(timeSeconds: time, width: image.extent.width, height: image.extent.height,
                        inferenceMilliseconds: (CFAbsoluteTimeGetCurrent()-start)*1000, detections: detections)
                }
                try file.write(contentsOf: JSONEncoder().encode(record))
                try file.write(contentsOf: Data([10]))
                frames += 1
                ballFrames += record.detections.contains(where: { $0.classID == 32 }) ? 1 : 0
                totalMilliseconds += record.inferenceMilliseconds
                if frames % 10 == 0 { await progress(duration > 0 ? min(1, max(0, time/duration)) : 0) }
            }
            guard reader.status == .completed else { throw reader.error ?? PrototypeError.message("Video decoding stopped.") }
            guard frames > 0 else { throw PrototypeError.message("No frames decoded.") }
            await progress(1)
            return AnalysisResult(frames: frames, ballFrames: ballFrames,
                                  averageMilliseconds: totalMilliseconds/Double(frames), file: destination)
        } catch {
            // Never present a truncated run as a completed export.
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }
}
