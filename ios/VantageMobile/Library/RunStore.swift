import AVFoundation
import Foundation
import ImageIO
import Observation
import os
import UIKit
import VantageKit

/// Persists analysis runs under `Documents/Runs/<id>/`. A folder only counts as a run
/// once `run.json` is written, so interrupted analyses are cleaned up on launch.
@MainActor @Observable
final class RunStore {
    private(set) var runs: [AnalysisRun] = []
    var notice: String?
    /// The last `reload()` found games it couldn't read, as before the first unlock after a
    /// restart, when iOS can launch the app; reloading once they're readable lists them.
    private(set) var hadUnreadableRuns = false
    private var statsByRun: [UUID: GameStats] = [:]
    let root: URL

    private static let log = Logger(subsystem: "Vantage", category: "RunStore")

    init() {
        root = URL.documentsDirectory.appending(path: "Runs", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        reload()
    }

    /// Lists the runs on disk and removes interrupted ones, so not during an import, whose folder has
    /// no `run.json` until it finishes.
    func reload() {
        notice = nil
        hadUnreadableRuns = false
        let folders: [URL]
        do {
            folders = try FileManager.default.contentsOfDirectory(
                at: root, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
                options: [.skipsHiddenFiles])
        } catch {
            notice = "Your games could not be read. Try opening Vantage again."
            hadUnreadableRuns = true
            Self.log.error("Could not list runs: \(String(describing: error), privacy: .public)")
            return
        }
        var loaded: [AnalysisRun] = []
        for folder in folders {
            guard let folderID = UUID(uuidString: folder.lastPathComponent),
                  let values = try? folder.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey]),
                  values.isDirectory == true, values.isSymbolicLink != true else { continue }
            let metadata = folder.appending(path: AnalysisRun.metadataFileName)
            var hasCompletionMarker = false
            do {
                // Attributes inspect the marker itself, including a dangling symlink.
                // Failure to read an existing marker must not classify a run as incomplete.
                _ = try FileManager.default.attributesOfItem(atPath: metadata.path(percentEncoded: false))
                hasCompletionMarker = true
                let data = try Data(contentsOf: metadata)
                let run = try Self.decoder.decode(AnalysisRun.self, from: data)
                guard run.id == folderID else {
                    notice = "Some saved games could not be read. Their files have been kept."
                    Self.log.error("Run identity does not match folder \(folderID.uuidString, privacy: .public)")
                    continue
                }
                loaded.append(run)
            } catch CocoaError.fileReadNoSuchFile where !hasCompletionMarker {
                // Only a missing completion marker identifies an interrupted analysis.
                // A corrupt or temporarily unreadable marker must never erase a game.
                do {
                    try FileManager.default.removeItem(at: folder)
                } catch {
                    Self.log.error("Could not remove incomplete run: \(String(describing: error), privacy: .public)")
                }
            } catch {
                notice = "Some saved games could not be read. Their files have been kept."
                // A corrupt file stays corrupt; one that can't be opened may be readable later.
                if !(error is DecodingError) { hadUnreadableRuns = true }
                Self.log.error("Unreadable run \(folderID.uuidString, privacy: .public): \(String(describing: error), privacy: .public)")
            }
        }
        runs = loaded.sorted { $0.createdAt > $1.createdAt }
        statsByRun = [:]
        for run in loaded { statsByRun[run.id] = loadStats(for: run.id) }
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
    func stats(for run: AnalysisRun) -> GameStats? { statsByRun[run.id] }

    func add(_ run: AnalysisRun) throws {
        let data = try Self.encoder.encode(run)
        try data.write(to: folder(for: run.id).appending(path: AnalysisRun.metadataFileName), options: .atomic)
        runs.insert(run, at: 0)
        statsByRun[run.id] = loadStats(for: run.id)
    }

    func delete(_ run: AnalysisRun) async {
        // Nothing more may be written into the folder once it's going. If deleting fails, its cover
        // just isn't remade this launch.
        await Self.thumbnails.forget(run.id)
        do {
            try FileManager.default.removeItem(at: folder(for: run.id))
        } catch CocoaError.fileNoSuchFile {
            // Already absent on disk: removing the stale list entry is safe.
        } catch {
            notice = "This game could not be deleted. Please try again."
            Self.log.error("Could not delete run: \(String(describing: error), privacy: .public)")
            return
        }
        runs.removeAll { $0.id == run.id }
        statsByRun[run.id] = nil
    }

    /// Decodes a run's stats.json once, so screens don't read disk on every render. A file that
    /// exists but can't be used is logged rather than silently shown as "not measured".
    private func loadStats(for id: UUID) -> GameStats? {
        let url = folder(for: id).appending(path: GameStats.fileName)
        guard FileManager.default.fileExists(atPath: url.path(percentEncoded: false)) else { return nil }
        do {
            let stats = try GameStats.decoder.decode(GameStats.self, from: Data(contentsOf: url))
            guard stats.schemaVersion <= GameStats.currentSchemaVersion else {
                Self.log.error("""
                    stats.json for \(id.uuidString, privacy: .public) has schema \(stats.schemaVersion), \
                    newer than \(GameStats.currentSchemaVersion)
                    """)
                return nil
            }
            return stats
        } catch {
            Self.log.error("""
                Unreadable stats.json for \(id.uuidString, privacy: .public): \
                \(String(describing: error), privacy: .public)
                """)
            return nil
        }
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

    /// The longest side of a saved thumbnail, in pixels. A landscape video's frame then fills a game
    /// card's cover (about 370 × 188 points, drawn at 3×) without upscaling, at about 200 KB on disk.
    nonisolated static let thumbnailMaxDimension: CGFloat = 1280

    /// Remakes covers that are too small, one video at a time.
    nonisolated static let thumbnails = ThumbnailRefresher()

    /// A thumbnail of the video at half a second, as JPEG; nil when the video gives no picture or
    /// the task is cancelled.
    nonisolated static func makeThumbnail(for video: URL) async -> Data? {
        let generator = AVAssetImageGenerator(asset: AVURLAsset(url: video))
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: thumbnailMaxDimension, height: thumbnailMaxDimension)
        guard let (image, _) = try? await generator.image(at: CMTime(seconds: 0.5, preferredTimescale: 600)),
              !Task.isCancelled else { return nil }
        return UIImage(cgImage: image).jpegData(compressionQuality: 0.8)
    }

    /// Best-effort list thumbnail; failures only mean the court drawing.
    nonisolated static func writeThumbnail(for video: URL, to destination: URL) async {
        guard let data = await makeThumbnail(for: video) else { return }
        try? data.write(to: destination, options: .atomic)
    }

    /// A game card's cover, decoded off the main thread at `size` (pixels: the cover's size on
    /// screen), so a list of games doesn't hold full-size pictures; nil (the court drawing) without
    /// a thumbnail. A thumbnail smaller than the video allows (games imported when thumbnails were
    /// 320 pixels) is made again from the video first (`thumbnails`), so older games sharpen too.
    nonisolated static func coverImage(for run: AnalysisRun, thumbnail: URL, video: URL, size: CGSize) async -> UIImage? {
        // Reading the size doesn't decode the picture.
        guard let saved = await Task.detached(priority: .userInitiated, operation: { pixelSize(of: thumbnail) }).value
        else { return nil }
        let possible = min(thumbnailMaxDimension, max(run.width, run.height))
        if max(saved.width, saved.height) < possible - 1 {
            _ = await thumbnails.refresh(run.id, video: video, thumbnail: thumbnail)
        }
        guard !Task.isCancelled else { return nil }
        return await Task.detached(priority: .userInitiated) { downsample(thumbnail, toFill: size) }.value
    }

    nonisolated private static func pixelSize(of url: URL) -> CGSize? {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int, width > 0, height > 0 else { return nil }
        return CGSize(width: width, height: height)
    }

    /// Decodes the picture at the smallest size that still fills `size` (pixels) once cropped to
    /// it, as the cover's `scaledToFill` does, so it stays sharp. Never larger than the file.
    nonisolated private static func downsample(_ url: URL, toFill size: CGSize) -> UIImage? {
        guard let pixels = pixelSize(of: url),
              let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary)
        else { return nil }
        let longest = max(pixels.width, pixels.height)
        let fill = max(size.width / pixels.width, size.height / pixels.height)
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            // Decoded here, off the main thread, rather than when first drawn.
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: min(longest, (longest * fill).rounded(.up)),
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        return UIImage(cgImage: image)
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
