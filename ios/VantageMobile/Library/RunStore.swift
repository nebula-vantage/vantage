import AVFoundation
import Foundation
import Observation
import UIKit
import VantageKit

/// Persists analysis runs under `Documents/Runs/<id>/`. A folder only counts as a run
/// once `run.json` is written, so interrupted analyses are cleaned up on launch.
@MainActor @Observable
final class RunStore {
    private(set) var runs: [AnalysisRun] = []
    let root: URL

    init() {
        root = URL.documentsDirectory.appending(path: "Runs", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        reload()
    }

    func reload() {
        let folders = (try? FileManager.default.contentsOfDirectory(
            at: root, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])) ?? []
        var loaded: [AnalysisRun] = []
        for folder in folders {
            let metadata = folder.appending(path: AnalysisRun.metadataFileName)
            if let data = try? Data(contentsOf: metadata),
               let run = try? Self.decoder.decode(AnalysisRun.self, from: data) {
                loaded.append(run)
            } else {
                // Incomplete run (app killed mid-analysis): never show a partial result.
                try? FileManager.default.removeItem(at: folder)
            }
        }
        runs = loaded.sorted { $0.createdAt > $1.createdAt }
    }

    nonisolated func folder(for id: UUID) -> URL {
        root.appending(path: id.uuidString, directoryHint: .isDirectory)
    }
    func videoURL(for run: AnalysisRun) -> URL { folder(for: run.id).appending(path: run.videoFileName) }
    func detectionsURL(for run: AnalysisRun) -> URL {
        folder(for: run.id).appending(path: AnalysisRun.detectionsFileName)
    }
    func thumbnailURL(for run: AnalysisRun) -> URL {
        folder(for: run.id).appending(path: AnalysisRun.thumbnailFileName)
    }

    /// Stats the engine wrote after analysis; nil until it has (or if the file is unreadable).
    func stats(for run: AnalysisRun) -> GameStats? {
        guard let data = try? Data(contentsOf: folder(for: run.id).appending(path: GameStats.fileName)) else {
            return nil
        }
        return try? GameStats.decoder.decode(GameStats.self, from: data)
    }

    func add(_ run: AnalysisRun) throws {
        let data = try Self.encoder.encode(run)
        try data.write(to: folder(for: run.id).appending(path: AnalysisRun.metadataFileName), options: .atomic)
        runs.insert(run, at: 0)
    }

    func delete(_ run: AnalysisRun) {
        try? FileManager.default.removeItem(at: folder(for: run.id))
        runs.removeAll { $0.id == run.id }
    }

    /// Removes a run folder that never completed.
    func discard(_ id: UUID) {
        try? FileManager.default.removeItem(at: folder(for: id))
    }

    /// Moves a picked video (the app's own temporary copy) into the run folder.
    /// Synchronous; call off the main actor.
    nonisolated static func moveVideo(from source: URL, into folder: URL) throws -> URL {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let ext = source.pathExtension.isEmpty ? "mov" : source.pathExtension.lowercased()
        let destination = folder.appending(path: "video.\(ext)")
        try FileManager.default.moveItem(at: source, to: destination)
        return destination
    }

    /// Best-effort list thumbnail; failures only mean a placeholder icon.
    nonisolated static func writeThumbnail(for video: URL, to destination: URL) async {
        let generator = AVAssetImageGenerator(asset: AVURLAsset(url: video))
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 320, height: 320)
        guard let (image, _) = try? await generator.image(at: CMTime(seconds: 0.5, preferredTimescale: 600)),
              let data = UIImage(cgImage: image).jpegData(compressionQuality: 0.8) else { return }
        try? data.write(to: destination, options: .atomic)
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }()
    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
