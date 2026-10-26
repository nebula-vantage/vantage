import PhotosUI
import SwiftUI
import VantageKit

/// Screens pushed from the games list.
enum GameRoute: Hashable {
    case detail(AnalysisRun)
    case debugPlayback(AnalysisRun)
}

/// Home screen: upload a video to analyze, follow its progress, and open analyzed games.
struct GamesListView: View {
    let store: RunStore
    let importer: RunImporter

    @State private var path: [GameRoute] = []
    @State private var picking = false
    @State private var picked: PhotosPickerItem?
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
            .navigationDestination(for: GameRoute.self) { route in
                switch route {
                case .detail(let run):
                    GameDetailView(run: run, store: store)
                case .debugPlayback(let run):
                    PlayerView(run: run, videoURL: store.videoURL(for: run),
                               detectionsURL: store.detectionsURL(for: run))
                }
            }
            #if DEBUG
            // UI check hooks: `simctl launch <device> <bundle> -openLatestGame` (game screen)
            // or `-openLatestRun` (debug playback).
            .task {
                let arguments = ProcessInfo.processInfo.arguments
                guard let run = store.runs.first else { return }
                if arguments.contains("-openLatestGame") { path = [.detail(run)] }
                if arguments.contains("-openLatestRun") { path = [.debugPlayback(run)] }
            }
            #endif
            // `.current` hands over the video as stored, skipping a slow transcode.
            .photosPicker(isPresented: $picking, selection: $picked, matching: .videos,
                          preferredItemEncoding: .current)
            .onChange(of: picked) { _, item in
                guard let item else { return }
                importer.start(item)
                picked = nil
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
            SpreadRow(alignment: .firstTextBaseline) {
                Text("Games")
                    .font(Theme.Fonts.display)
                    .foregroundStyle(Theme.Colors.ink)
                    .accessibilityAddTraits(.isHeader)
            } trailing: {
                Text(Format.count(store.runs.count, "game", "games")).monoLabel()
            }
        }
    }

    private var uploadTile: some View {
        Button { picking = true } label: {
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
                NavigationLink(value: GameRoute.detail(run)) { GameRow(run: run, stats: store.stats(for: run)) }
                    .buttonStyle(.card)
                    .contextMenu {
                        Button("Debug playback", systemImage: "ladybug") { path.append(.debugPlayback(run)) }
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
                Text(pending.sourceName ?? "Video from Photos").font(Theme.Fonts.title).lineLimit(2)
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
