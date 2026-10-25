import SwiftUI
import UIKit
import UniformTypeIdentifiers
import VantageKit

/// Home screen: import a video to analyze, and reopen previous runs for playback.
struct RunListView: View {
    let store: RunStore
    let importer: RunImporter

    @State private var path: [AnalysisRun] = []
    @State private var importing = false

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if importer.isRunning || importer.notice != nil { analysisSection }
                if store.runs.isEmpty && !importer.isRunning {
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
                        .disabled(importer.isRunning)
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
                case .failure(let error): importer.notice = error.localizedDescription
                case .success(let url): importer.start(url)
                }
            }
        }
    }

    private var analysisSection: some View {
        Section {
            if let pending = importer.pending {
                VStack(alignment: .leading, spacing: 8) {
                    Text(pending.progress == nil ? "Copying video…" : "Analyzing \(pending.sourceName)…")
                        .font(.subheadline)
                    ProgressView(value: pending.progress ?? 0)
                    Text("Keep Vantage open; analysis pauses in the background.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Cancel", role: .destructive) { importer.cancel() }.font(.callout)
                }
            } else if let notice = importer.notice {
                Text(notice).font(.callout)
            }
        }
    }
}

private struct RunRow: View {
    let run: AnalysisRun
    let thumbnail: URL

    private var ballSummary: String {
        let percent = FloatingPointFormatStyle<Double>.Percent().precision(.fractionLength(0))
        if let tracked = run.trackedBallFraction { return "ball tracked \(tracked.formatted(percent))" }
        return "ball seen \(run.ballFrameFraction.formatted(percent))"
    }

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
                     + "\(run.frames) frames · \(ballSummary) · "
                     + "\(Int(run.averageMilliseconds)) ms/frame")
                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
        }
    }
}
