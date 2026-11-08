import SwiftUI

@main
struct VantageMobileApp: App {
    @State private var accounts: AccountStore
    @State private var store: RunStore
    @State private var importer: RunImporter
    @Environment(\.scenePhase) private var scenePhase

    init() {
        Theme.Fonts.register()
        let accounts = AccountStore()
        #if DEBUG
        accounts.applyLaunchArguments()
        #endif
        _accounts = State(initialValue: accounts)
        let store = RunStore()
        _store = State(initialValue: store)
        _importer = State(initialValue: RunImporter(store: store))
    }

    var body: some Scene {
        WindowGroup {
            // Signed out shows Create account (no account yet) or Sign in; signed in shows Games.
            Group {
                switch accounts.status {
                case .unavailable:
                    OpeningView()
                case .noAccount:
                    CreateAccountView(accounts: accounts)
                case .signedOut:
                    SignInView(accounts: accounts)
                case .signedIn:
                    GamesListView(store: store, importer: importer, accounts: accounts)
                }
            }
            .animation(.default, value: accounts.status)
            .tint(Theme.Colors.ink)
            // The palette is light-only for the MVP.
            .preferredColorScheme(.light)
            // A launch before the first unlock after a restart can't read the account or the games yet.
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.protectedDataDidBecomeAvailableNotification)) { _ in
                reloadUnreadable()
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { reloadUnreadable() }
            }
        }
    }

    /// Reads the account and the games again if they couldn't be read before.
    private func reloadUnreadable() {
        accounts.reloadIfUnavailable()
        // Not during an import: reloading removes run folders without `run.json`, as the import's is.
        if store.hadUnreadableRuns, !importer.isRunning { store.reload() }
    }
}

/// While the account can't be read yet (`AccountStore.Status.unavailable`): the wordmark and a
/// spinner on the page background, rather than Create account.
private struct OpeningView: View {
    var body: some View {
        VStack(spacing: Theme.Spacing.xl) {
            Wordmark(large: true)
            ProgressView()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.Colors.background)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Opening Vantage")
    }
}

#if DEBUG
/// The UI check hooks' launch arguments (ios/README.md). Each fires at most once per process, so
/// signing out and back in during a check doesn't run it again.
@MainActor
enum LaunchHooks {
    private static var used: Set<String> = []

    /// Whether `argument` was passed and hasn't fired yet. Firing uses it up.
    static func take(_ argument: String) -> Bool {
        ProcessInfo.processInfo.arguments.contains(argument) && used.insert(argument).inserted
    }

    /// The value after `argument` (`-password pickleball`), the first time it's asked for.
    static func takeValue(after argument: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: argument), arguments.indices.contains(index + 1),
              used.insert(argument).inserted else { return nil }
        return arguments[index + 1]
    }

    /// For hooks that hold for a whole screen (`-scrollToBottom`): whether `argument` was passed and
    /// `screen` hasn't been shown with it before. `finish(_:on:)` ends it when the screen goes.
    static func holds(_ argument: String, on screen: String) -> Bool {
        ProcessInfo.processInfo.arguments.contains(argument) && !used.contains("\(argument) \(screen)")
    }

    static func finish(_ argument: String, on screen: String) {
        used.insert("\(argument) \(screen)")
    }
}
#endif
