import Foundation
import Observation
import PhotosUI
import SwiftUI
import UIKit
import UniformTypeIdentifiers
import VantageKit

/// Imports one video at a time: copies it into a new run folder, writes its thumbnail, analyzes
/// it on device and adds the finished run to the store. Owned by the app, so the job keeps going
/// while the user moves between screens.
@MainActor @Observable
final class RunImporter {
    struct Pending: Identifiable {
        let id: UUID
        /// Nil until the video has arrived from Photos.
        var sourceName: String?
        /// Nil while the video is being copied, then 0...1 during analysis.
        var progress: Double?
    }

    private(set) var pending: Pending?
    /// Why the last import failed or stopped, until dismissed.
    var notice: String?

    private let store: RunStore
    private var job: Task<Void, Never>?

    var isRunning: Bool { job != nil }

    init(store: RunStore) {
        self.store = store
    }

    func cancel() { job?.cancel() }

    func start(_ item: PhotosPickerItem) {
        guard job == nil else { return }
        guard let model = Bundle.main.url(forResource: "VantageDetector", withExtension: "mlmodelc") else {
            notice = "Missing model. Add the exported VantageDetector.mlpackage to the app target."
            return
        }
        let id = UUID()
        let folder = store.folder(for: id)
        let detections = folder.appending(path: AnalysisRun.detectionsFileName)
        notice = nil
        pending = Pending(id: id, sourceName: nil, progress: nil)
        UIApplication.shared.isIdleTimerDisabled = true
        job = Task {
            defer {
                job = nil
                pending = nil
                UIApplication.shared.isIdleTimerDisabled = false
            }
            do {
                // Videos only in iCloud download here, which can take a while.
                guard let picked = try await item.loadTransferable(type: PickedVideo.self) else {
                    throw AnalysisError.message("This video can't be read from Photos.")
                }
                defer { try? FileManager.default.removeItem(at: picked.url.deletingLastPathComponent()) }
                try Task.checkCancellation()
                let source = picked.url
                pending?.sourceName = source.lastPathComponent
                let video = try await Task.detached { try RunStore.moveVideo(from: source, into: folder) }.value
                try Task.checkCancellation()
                await RunStore.writeThumbnail(for: video, to: folder.appending(path: AnalysisRun.thumbnailFileName))
                pending?.progress = 0
                let result = try await VideoAnalyzer().analyze(video: video, model: model, destination: detections) { value in
                    await MainActor.run { self.pending?.progress = value }
                }
                let run = AnalysisRun(
                    id: id, createdAt: .now, sourceName: source.lastPathComponent,
                    videoFileName: video.lastPathComponent, frames: result.frames, ballFrames: result.ballFrames,
                    trackedBallFrames: result.trackedBallFrames,
                    averageMilliseconds: result.averageMilliseconds, width: result.width, height: result.height,
                    durationSeconds: result.durationSeconds)
                try store.add(run)
            } catch is CancellationError {
                store.discard(id)
                notice = "Analysis cancelled."
            } catch {
                store.discard(id)
                notice = error.localizedDescription
            }
        }
    }
}

/// A video from the photo library. Photos hands over a file that's deleted once the import
/// closure returns, so it's copied into its own temporary folder (keeping the original name).
private struct PickedVideo: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .movie) { received in
            let folder = URL.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let copy = folder.appending(path: received.file.lastPathComponent)
            try FileManager.default.copyItem(at: received.file, to: copy)
            return PickedVideo(url: copy)
        }
    }
}
