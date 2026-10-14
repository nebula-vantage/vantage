import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Home screen: import a video to analyze, and reopen previous runs for playback.
struct RunListView: View {
    let store: RunStore

    @State private var path: [AnalysisRun] = []
    @State private var importing = false
    @State private var job: Task<Void, Never>?
    @State private var progress = 0.0
    @State private var status: String?

    private var running: Bool { job != nil }

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if running || status != nil { analysisSection }
                if store.runs.isEmpty && !running {
                    ContentUnavailableView {
                        Label("No analyses yet", systemImage: "video.badge.waveform")
                    } description: {
                        Text("Import a court video. It is analyzed on this iPhone; nothing is uploaded.")
                    } actions: {
                        Button("Import video") { importing = true }.buttonStyle(.borderedProminent)
                    }
                    .listRowBackground(Color.clear)
                }
                ForEach(store.runs) { run in
                    NavigationLink(value: run) { RunRow(run: run, thumbnail: store.thumbnailURL(for: run)) }
                }
                .onDelete { offsets in offsets.map { store.runs[$0] }.forEach(store.delete) }
            }
            .navigationTitle("Vantage")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { importing = true } label: { Label("Import video", systemImage: "plus") }
                        .disabled(running)
                }
            }
            .navigationDestination(for: AnalysisRun.self) { run in
                PlayerView(run: run, videoURL: store.videoURL(for: run), detectionsURL: store.detectionsURL(for: run))
            }
            #if DEBUG
            // UI check hook: `simctl launch <device> <bundle> -openLatestRun`.
            .task {
                if ProcessInfo.processInfo.arguments.contains("-openLatestRun"), let run = store.runs.first {
                    path = [run]
                }
            }
            #endif
            .fileImporter(isPresented: $importing, allowedContentTypes: [.movie]) { selection in
                switch selection {
                case .failure(let error): status = error.localizedDescription
                case .success(let url): analyze(url)
                }
            }
        }
    }

    private var analysisSection: some View {
        Section {
            if running {
                VStack(alignment: .leading, spacing: 8) {
                    Text(status ?? "Analyzing…").font(.subheadline)
                    ProgressView(value: progress)
                    Text("Keep Vantage open; analysis pauses in the background.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Cancel", role: .destructive) { job?.cancel() }.font(.callout)
                }
            } else if let status {
                Text(status).font(.callout)
            }
        }
    }

    @MainActor private func analyze(_ source: URL) {
        guard let model = Bundle.main.url(forResource: "VantageDetector", withExtension: "mlmodelc") else {
            status = "Missing model. Add the exported VantageDetector.mlpackage to the app target."
            return
        }
        let id = UUID()
        let folder = store.folder(for: id)
        let detections = folder.appending(path: AnalysisRun.detectionsFileName)
        progress = 0
        status = "Copying video…"
        UIApplication.shared.isIdleTimerDisabled = true
        job = Task {
            defer {
                job = nil
                UIApplication.shared.isIdleTimerDisabled = false
            }
            do {
                let video = try await Task.detached { try RunStore.copyVideo(from: source, into: folder) }.value
                try Task.checkCancellation()
                await RunStore.writeThumbnail(for: video, to: folder.appending(path: AnalysisRun.thumbnailFileName))
                status = "Analyzing \(source.lastPathComponent)…"
                let result = try await VideoAnalyzer().analyze(video: video, model: model, destination: detections) { value in
                    await MainActor.run { progress = value }
                }
                let run = AnalysisRun(
                    id: id, createdAt: .now, sourceName: source.lastPathComponent,
                    videoFileName: video.lastPathComponent, frames: result.frames, ballFrames: result.ballFrames,
                    averageMilliseconds: result.averageMilliseconds, width: result.width, height: result.height,
                    durationSeconds: result.durationSeconds)
                try store.add(run)
                status = nil
                path = [run]
            } catch is CancellationError {
                store.discard(id)
                status = "Analysis cancelled."
            } catch {
                store.discard(id)
                status = error.localizedDescription
            }
        }
    }
}

private struct RunRow: View {
    let run: AnalysisRun
    let thumbnail: URL

    var body: some View {
        HStack(spacing: 12) {
            Group {
                if let image = UIImage(contentsOfFile: thumbnail.path(percentEncoded: false)) {
                    Image(uiImage: image).resizable().scaledToFill()
                } else {
                    Image(systemName: "film").foregroundStyle(.secondary)
                }
            }
            .frame(width: 72, height: 48)
            .background(.quaternary)
            .clipShape(.rect(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 2) {
                Text(run.sourceName).font(.headline).lineLimit(1)
                Text(run.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption).foregroundStyle(.secondary)
                Text("\(Duration.seconds(run.durationSeconds).formatted(.time(pattern: .minuteSecond))) · "
                     + "\(run.frames) frames · ball \(run.ballFrameFraction.formatted(.percent.precision(.fractionLength(0)))) · "
                     + "\(Int(run.averageMilliseconds)) ms/frame")
                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
        }
    }
}
