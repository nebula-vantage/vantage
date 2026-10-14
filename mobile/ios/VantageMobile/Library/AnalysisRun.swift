import Foundation

/// One completed on-device analysis. Stored as `run.json` inside the run's folder,
/// next to the copied source video, its detections, and a thumbnail.
struct AnalysisRun: Codable, Identifiable, Hashable, Sendable {
    static let metadataFileName = "run.json"
    static let detectionsFileName = "detections.jsonl"
    static let thumbnailFileName = "thumbnail.jpg"

    let id: UUID
    let createdAt: Date
    /// Original file name as picked in Files.
    let sourceName: String
    /// File name of the copied video inside the run folder.
    let videoFileName: String
    let frames: Int
    let ballFrames: Int
    let averageMilliseconds: Double
    let width: Double
    let height: Double
    let durationSeconds: Double

    var ballFrameFraction: Double { frames > 0 ? Double(ballFrames) / Double(frames) : 0 }
}
