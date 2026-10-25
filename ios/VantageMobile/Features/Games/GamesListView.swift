import SwiftUI
import UniformTypeIdentifiers
import VantageKit

/// Home screen: upload a video to analyze, follow its progress, and open analyzed games.
struct GamesListView: View {
    let store: RunStore
    let importer: RunImporter

    @State private var path: [AnalysisRun] = []
    @State private var importing = false
    @State private var deleting: AnalysisRun?

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
                    header
                    uploadTile
                    games
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.vertical, Theme.Spacing.l)
            }
            .background(Theme.Colors.background)
            .navigationTitle("Games")
            .toolbar(.hidden, for: .navigationBar)
            // Debug playback until the game detail screen exists; then that becomes the row's destination.
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
            .confirmationDialog("Delete this game?", isPresented: isDeleting, titleVisibility: .visible,
                                presenting: deleting) { run in
                Button("Delete", role: .destructive) { store.delete(run) }
            } message: { _ in
                Text("The video and its analysis are removed from this iPhone.")
            }
        }
    }

    private var isDeleting: Binding<Bool> {
        Binding { deleting != nil } set: { if !$0 { deleting = nil } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text("Vantage").monoLabel()
            HStack(alignment: .firstTextBaseline) {
                Text("Games")
                    .font(Theme.Fonts.display)
                    .foregroundStyle(Theme.Colors.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Text(Format.count(store.runs.count, "game", "games")).monoLabel()
            }
        }
    }

    private var uploadTile: some View {
        Button { importing = true } label: {
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                Image(systemName: "square.and.arrow.up")
                    .font(Theme.Fonts.title)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: Theme.Spacing.xxs) {
                    Text("Upload video").font(Theme.Fonts.title)
                    Text("Analyze a saved video")
                        .font(Theme.Fonts.callout)
                        .foregroundStyle(Theme.Colors.inkSecondary)
                }
            }
        }
        .buttonStyle(.card)
        .disabled(importer.isRunning)
    }

    private var games: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            if let notice = importer.notice {
                NoticeCard(message: notice) { importer.notice = nil }
            }
            if let pending = importer.pending {
                PendingGameRow(pending: pending) { importer.cancel() }
            }
            if store.runs.isEmpty && importer.pending == nil {
                Text("Your analyzed games show up here.")
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
            }
            ForEach(store.runs) { run in
                NavigationLink(value: run) { GameRow(run: run, stats: store.stats(for: run)) }
                    .buttonStyle(.card)
                    .contextMenu {
                        Button("Debug playback", systemImage: "play.rectangle") { path.append(run) }
                        Button("Delete", systemImage: "trash", role: .destructive) { deleting = run }
                    }
            }
        }
    }
}

/// The video currently being analyzed. Not tappable: there's nothing to open until it finishes.
private struct PendingGameRow: View {
    let pending: RunImporter.Pending
    let cancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                Text("Pickleball · Analyzing").monoLabel()
                Text(pending.sourceName).font(Theme.Fonts.title).lineLimit(2)
            }
            AnalysisProgressView(fraction: pending.progress)
            HStack(alignment: .center, spacing: Theme.Spacing.m) {
                Text("Keep Vantage open; analysis pauses in the background.")
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkTertiary)
                Spacer()
                Button("Cancel", action: cancel)
                    .font(Theme.Fonts.headline)
                    .foregroundStyle(Theme.Colors.accent)
                    .frame(minWidth: Theme.Size.minTouch, minHeight: Theme.Size.minTouch)
                    .contentShape(.rect)
                    .buttonStyle(.plain)
            }
        }
        .foregroundStyle(Theme.Colors.ink)
        .card()
    }
}

/// Why the last import failed or was cancelled.
private struct NoticeCard: View {
    let message: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: Theme.Spacing.m) {
            Text(message)
                .font(Theme.Fonts.body)
                .foregroundStyle(Theme.Colors.ink)
            Spacer()
            Button("Dismiss", systemImage: "xmark", action: dismiss)
                .labelStyle(.iconOnly)
                .font(Theme.Fonts.headline)
                .foregroundStyle(Theme.Colors.inkSecondary)
                .frame(minWidth: Theme.Size.minTouch, minHeight: Theme.Size.minTouch)
                .contentShape(.rect)
                .buttonStyle(.plain)
        }
        .card()
    }
}
