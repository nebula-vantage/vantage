// Runs the iPhone app's analysis pipeline (same Core ML model, preprocessing, and tracker)
// on a Mac. Useful for fixtures, desktop/mobile comparisons, and debugging without a phone.
//
//   swift run -c release vantage-analyze <model.mlpackage> <video> <detections.jsonl>
import CoreML
import Foundation
import VantageKit

let arguments = CommandLine.arguments
guard arguments.count == 4 else {
    FileHandle.standardError.write(Data("usage: vantage-analyze <model.mlpackage> <video> <detections.jsonl>\n".utf8))
    exit(2)
}
let package = URL(fileURLWithPath: arguments[1])
let video = URL(fileURLWithPath: arguments[2])
let output = URL(fileURLWithPath: arguments[3])

do {
    let compiled = try MLModel.compileModel(at: package)
    defer { try? FileManager.default.removeItem(at: compiled) }
    let reporter = ProgressReporter()
    let result = try await VideoAnalyzer().analyze(video: video, model: compiled, destination: output) { value in
        await reporter.report(value)
    }
    let summary: [String: Any] = [
        "frames": result.frames, "ball_frames": result.ballFrames,
        "tracked_ball_frames": result.trackedBallFrames,
        "average_ms": result.averageMilliseconds, "width": result.width, "height": result.height,
        "duration_s": result.durationSeconds, "output": output.path,
    ]
    let json = try JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys])
    print(String(decoding: json, as: UTF8.self))
} catch {
    FileHandle.standardError.write(Data("error: \(error.localizedDescription)\n".utf8))
    exit(1)
}

/// Prints progress to stderr in 10% steps.
actor ProgressReporter {
    private var lastDecile = -1
    func report(_ value: Double) {
        let decile = Int(value * 10)
        guard decile != lastDecile else { return }
        lastDecile = decile
        FileHandle.standardError.write(Data("\(decile * 10)%\n".utf8))
    }
}
