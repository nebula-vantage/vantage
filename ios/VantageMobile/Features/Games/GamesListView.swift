import PhotosUI
import SwiftUI
import VantageKit

/// Screens pushed from the games list.
enum GameRoute: Hashable {
    case detail(AnalysisRun)
    case debugPlayback(AnalysisRun)
}

/// Home screen: upload a video to analyze, follow its progress, and open analyzed games. Your
/// initials in the header open Account.
struct GamesListView: View {
    let store: RunStore
    let importer: RunImporter
    let accounts: AccountStore

    @State private var path: [GameRoute] = []
    @State private var picking = false
    @State private var picked: PhotosPickerItem?
    @State private var deleting: AnalysisRun?
    @State private var showingAccount = false
    /// Sign out ends the session on disk from the Account sheet, then waits for the sheet to close
    /// before the app returns to Sign in.
    @State private var signingOut = false
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

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
            #if DEBUG
            .debugScrollAnchor("games")
            #endif
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
                Button("Delete", role: .destructive) { Task { await store.delete(run) } }
            } message: { _ in
                Text("The video and its analysis are removed from this iPhone.")
            }
            .sheet(isPresented: $showingAccount, onDismiss: signOutIfAsked) {
                AccountView(accounts: accounts) {
                    signingOut = true
                    showingAccount = false
                }
            }
        }
        #if DEBUG
        // UI check hooks: `simctl launch <device> <bundle> -openLatestGame` (game screen),
        // `-openLatestRun` (debug playback) or `-openAccount` (Account sheet). On the stack, not
        // the list, so they don't run again every time the user comes back to the list, and once
        // per launch, so signing out and back in doesn't either.
        .task {
            if LaunchHooks.take("-openAccount") { showingAccount = true }
            guard let run = store.runs.first else { return }
            if LaunchHooks.take("-openLatestGame") { path = [.detail(run)] }
            if LaunchHooks.take("-openLatestRun") { path = [.debugPlayback(run)] }
        }
        #endif
    }

    /// The session already ended on disk when Sign out was tapped; now Sign in replaces Games.
    private func signOutIfAsked() {
        guard signingOut else { return }
        signingOut = false
        accounts.signOut()
    }

    private var isDeleting: Binding<Bool> {
        Binding { deleting != nil } set: { if !$0 { deleting = nil } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.l) {
            HStack(spacing: Theme.Spacing.m) {
                Wordmark()
                Spacer()
                Button { showingAccount = true } label: {
                    // Trailing in its touch area, so it lines up with the cards below.
                    InitialsAvatar(initials: accounts.profile?.initials ?? "?")
                        .frame(minWidth: Theme.Size.minTouch, minHeight: Theme.Size.minTouch, alignment: .trailing)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Account")
                .accessibilityValue(accounts.profile?.name ?? "")
            }
            // Past this size the wordmark and the avatar no longer fit side by side.
            .dynamicTypeSize(...DynamicTypeSize.accessibility2)
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text("Your library").monoLabel()
                Text("Games")
                    .font(Theme.Fonts.pageTitle)
                    .tracking(Theme.Fonts.pageTitleTracking)
                    .foregroundStyle(Theme.Colors.ink)
                    .accessibilityAddTraits(.isHeader)
                Text("Your game. A clearer picture. A next step.")
                    .font(Theme.Fonts.footnote)
                    .foregroundStyle(Theme.Colors.inkSecondary)
            }
        }
    }

    private var uploadTile: some View {
        // The icon sits beside the text, as on the web at phone width; at accessibility sizes it
        // moves above so the text keeps the tile's width.
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Theme.Spacing.l))
            : AnyLayout(HStackLayout(alignment: .top, spacing: Theme.Spacing.l))
        return Button { picking = true } label: {
            layout {
                // A fixed square, as on the web, so the arrow stops growing before it outgrows it.
                Image(systemName: "arrow.up")
                    .font(Theme.Fonts.title)
                    .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                    .foregroundStyle(Theme.Colors.surface)
                    .frame(width: Theme.Size.tileIcon, height: Theme.Size.tileIcon)
                    .background(Theme.Colors.ink, in: .rect(cornerRadius: Theme.Radius.tileIcon, style: .continuous))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                    VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                        Text("Bring your game into focus.")
                            .font(Theme.Fonts.tileTitle)
                            .tracking(Theme.Fonts.tileTitleTracking)
                        Text("Upload a match video. Review the play. Find your next practice focus.")
                            .font(Theme.Fonts.footnote)
                            .foregroundStyle(Theme.Colors.inkSecondary)
                    }
                    HStack(spacing: Theme.Spacing.xs) {
                        Text("Analyze a video")
                        Image(systemName: "arrow.up.right").accessibilityHidden(true)
                    }
                    .font(Theme.Fonts.headline)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .multilineTextAlignment(.leading)
        }
        .buttonStyle(.card)
        .disabled(importer.isRunning)
    }

    /// Lazy, so a game card (and its cover) is only built as it scrolls into view.
    private var games: some View {
        LazyVStack(alignment: .leading, spacing: Theme.Spacing.m) {
            SpreadRow(alignment: .firstTextBaseline) {
                Text("Your games")
                    .font(Theme.Fonts.title)
                    .foregroundStyle(Theme.Colors.ink)
                    .accessibilityAddTraits(.isHeader)
            } trailing: {
                Text(Format.count(store.runs.count, "game", "games")).monoLabel()
            }
            if let notice = importer.notice {
                NoticeCard(message: notice) { importer.notice = nil }
            }
            if let notice = store.notice {
                NoticeCard(message: notice) { store.notice = nil }
            }
            if let pending = importer.pending {
                PendingGameRow(pending: pending) { importer.cancel() }
            }
            if store.runs.isEmpty && importer.pending == nil {
                EmptyGames()
            }
            ForEach(store.runs) { run in
                NavigationLink(value: GameRoute.detail(run)) {
                    GameRow(run: run, stats: store.stats(for: run), thumbnail: store.thumbnailURL(for: run),
                            video: store.videoURL(for: run))
                }
                .buttonStyle(.card(padded: false))
                .contextMenu {
                    #if DEBUG
                    Button("Debug playback", systemImage: "ladybug") { path.append(.debugPlayback(run)) }
                    #endif
                    Button("Delete", systemImage: "trash", role: .destructive) { deleting = run }
                }
            }
        }
    }
}

/// No games yet: a small court, then the title, in a dashed outline on a faint white fill, as the
/// web's empty library. The upload tile above is the one way to add a game, so there's no second
/// button here.
private struct EmptyGames: View {
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
        VStack(spacing: Theme.Spacing.l) {
            CourtDiagram(court: .pickleball)
                .frame(width: Theme.Size.emptyCourt)
                .accessibilityHidden(true)
            VStack(spacing: Theme.Spacing.s) {
                Text("Your next game starts here.")
                    .font(Theme.Fonts.heading)
                    .tracking(Theme.Fonts.headingTracking)
                    .foregroundStyle(Theme.Colors.ink)
                Text("Uploaded games and their analysis stay together in this library.")
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
            }
        }
        .multilineTextAlignment(.center)
        .fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, Theme.Spacing.l)
        .padding(.vertical, Theme.Spacing.xxl)
        .frame(maxWidth: .infinity)
        .background(Theme.Colors.surfaceFaint, in: shape)
        .overlay {
            shape.strokeBorder(Theme.Colors.hairline,
                               style: StrokeStyle(lineWidth: Theme.Size.hairline, dash: [Theme.Size.dash]))
        }
        .accessibilityElement(children: .combine)
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
