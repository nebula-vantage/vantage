import Foundation
import Observation
import os
import VantageKit

/// The one account on this iPhone. The profile is JSON in Application Support, the password hash
/// is in the Keychain (`PasswordVault`), and you stay signed in until you sign out. Games aren't
/// part of the account, so resetting it keeps them. Rules and messages are shared with the web app
/// (docs/app-experience.md).
@MainActor @Observable
final class AccountStore {
    enum Status: Equatable {
        /// The account file is there but can't be read yet: iOS can launch the app after a restart,
        /// before the first unlock makes the file readable. Not the same as having no account.
        case unavailable
        /// First launch or after a reset: Create account.
        case noAccount
        /// An account exists: Sign in.
        case signedOut
        case signedIn
    }

    /// Storage failures, which the shared screens have no words for.
    enum Failure: LocalizedError {
        case couldNotSave
        case couldNotReset
        case couldNotSignOut

        var errorDescription: String? {
            switch self {
            case .couldNotSave: "Your account couldn't be saved. Try again."
            case .couldNotReset: "Your account couldn't be reset. Try again."
            case .couldNotSignOut: "Couldn't sign out. Try again."
            }
        }
    }

    private(set) var profile: AccountProfile?
    private(set) var isSignedIn = false
    /// Set while `account.json` exists but can't be read; `reloadIfUnavailable()` tries again.
    private(set) var isUnavailable = false

    var status: Status {
        if isUnavailable { return .unavailable }
        guard profile != nil else { return .noAccount }
        return isSignedIn ? .signedIn : .signedOut
    }

    private let folder: URL
    private let vault: PasswordVault
    private let clock: () -> Date
    /// In memory, like the web app's: relaunching clears it. Shared by sign-in and changing the
    /// password.
    @ObservationIgnored private var throttle: SignInThrottle
    /// `account.json` still says signed in, as version 1 did, because it couldn't be rewritten at
    /// launch. Signing out then has to rewrite it, or the next launch would sign back in.
    @ObservationIgnored private var legacySignedIn = false

    private static let log = Logger(subsystem: "Vantage", category: "AccountStore")

    /// What `account.json` holds. Version 1 also kept whether you were signed in; that's now the
    /// `signed-in` marker, so signing out deletes a file rather than writing one.
    private struct Saved: Codable {
        var version = 2
        var profile: AccountProfile
        /// Version 1's sign-in state, read once to carry it over to the marker.
        var signedIn: Bool?
    }

    private var fileURL: URL { folder.appending(path: "account.json") }
    /// Exists while you're signed in. Deleting it works even on a full disk, so signing out can't
    /// quietly fail and leave the next launch signed in.
    private var signedInURL: URL { folder.appending(path: "signed-in") }
    private var hasSignedInMarker: Bool { FileManager.default.fileExists(atPath: signedInURL.path(percentEncoded: false)) }

    init(folder: URL = .applicationSupportDirectory.appending(path: "Account", directoryHint: .isDirectory),
         vault: PasswordVault = PasswordVault(), clock: @escaping () -> Date = Date.init) {
        self.folder = folder
        self.vault = vault
        self.clock = clock
        throttle = SignInThrottle(clock: clock)
        load()
    }

    /// Only a missing or undecodable `account.json` means there's no account. One that's there but
    /// can't be read yet leaves the status `.unavailable` rather than offering Create account, which
    /// would replace it.
    private func load() {
        let data: Data
        do {
            data = try Data(contentsOf: fileURL)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
            isUnavailable = false
            return
        } catch {
            isUnavailable = true
            Self.log.error("Can't read account.json yet: \(String(describing: error), privacy: .public)")
            return
        }
        isUnavailable = false
        let saved: Saved
        do {
            saved = try Self.decoder.decode(Saved.self, from: data)
        } catch {
            // Nothing to sign in to without a profile; Create account replaces the file.
            Self.log.error("Unreadable account.json: \(String(describing: error), privacy: .public)")
            return
        }
        profile = saved.profile
        if let signedIn = saved.signedIn { migrate(signedIn: signedIn, profile: saved.profile) }
        isSignedIn = hasSignedInMarker
    }

    /// Carries version 1's sign-in state over to the marker and drops it from `account.json`. A
    /// marker that can't be written only means Sign in this time.
    private func migrate(signedIn: Bool, profile: AccountProfile) {
        if signedIn && !hasSignedInMarker { markSignedIn() }
        do {
            try save(Saved(profile: profile))
        } catch {
            legacySignedIn = signedIn
            Self.log.error("Could not migrate account.json: \(String(describing: error), privacy: .public)")
        }
    }

    /// Tries `account.json` again after it couldn't be read: when protected data becomes available
    /// (the first unlock after a restart) or the app becomes active.
    func reloadIfUnavailable() {
        guard isUnavailable else { return }
        load()
    }

    /// Creates the account and signs in. Throws `AccountError` for the first invalid field.
    func createAccount(name: String, email: String, password: String) async throws {
        let profile = AccountProfile(name: try AccountValidation.name(name), email: try AccountValidation.email(email),
                                     createdAt: clock())
        try AccountValidation.password(password)
        do {
            try vault.write(try await Self.hash(password))
            try save(Saved(profile: profile))
        } catch {
            Self.log.error("Could not create account: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotSave
        }
        markSignedIn()
        self.profile = profile
        isSignedIn = true
    }

    /// Throws `AccountError.wrongCredentials`, or `.tooManyAttempts` while sign-in is locked.
    func signIn(email: String, password: String) async throws {
        try throttle.checkUnlocked()
        let passwordMatches = await Self.verify(password, against: storedHash())
        guard let profile, passwordMatches, AccountValidation.normalizedEmail(email) == profile.email else {
            throw throttle.failure(.wrongCredentials)
        }
        throttle.recordSuccess()
        markSignedIn()
        isSignedIn = true
    }

    /// Signing out takes two steps, so the Account sheet can close in between. This one ends the
    /// session on disk by deleting the signed-in marker, and throws `Failure.couldNotSignOut`
    /// rather than pretending when it can't: the next launch would open Games again.
    func endSession() throws {
        do {
            try FileManager.default.removeItem(at: signedInURL)
        } catch CocoaError.fileNoSuchFile {
            // Already signed out on disk.
        } catch {
            Self.log.error("Could not remove the sign-in marker: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotSignOut
        }
        guard legacySignedIn, let profile else { return }
        do {
            try save(Saved(profile: profile))
        } catch {
            Self.log.error("Could not drop the old sign-in state: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotSignOut
        }
    }

    /// Then Sign in replaces Games. Does nothing until `endSession()` has succeeded, so the screen
    /// never shows you signed out while the next launch would sign you back in.
    func signOut() {
        guard !hasSignedInMarker, !legacySignedIn else { return }
        isSignedIn = false
    }

    /// Throws `AccountError` for the first invalid field.
    func updateProfile(name: String, email: String) throws {
        guard var profile else { return }
        profile.name = try AccountValidation.name(name)
        profile.email = try AccountValidation.email(email)
        do {
            try save(Saved(profile: profile))
        } catch {
            Self.log.error("Could not save profile: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotSave
        }
        self.profile = profile
    }

    /// Checks the current password first, as the web app's server does, then the new one. A wrong
    /// current password counts toward the same lockout as sign-in, so this can't be used to keep
    /// guessing: throws `AccountError.wrongCurrentPassword`, or `.tooManyAttempts`. The Account
    /// screen checks the new one's length before calling, as the web page does.
    func changePassword(current: String, new: String) async throws {
        try throttle.checkUnlocked()
        guard await Self.verify(current, against: storedHash()) else {
            throw throttle.failure(.wrongCurrentPassword)
        }
        try AccountValidation.password(new)
        do {
            try vault.write(try await Self.hash(new))
        } catch {
            Self.log.error("Could not change password: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotSave
        }
    }

    /// Removes the account from this iPhone so a new one can be created. Games stay.
    func resetAccount() throws {
        do {
            try FileManager.default.removeItem(at: fileURL)
        } catch CocoaError.fileNoSuchFile {
            // No account file: nothing to remove.
        } catch {
            Self.log.error("Could not remove account: \(String(describing: error), privacy: .public)")
            throw Failure.couldNotReset
        }
        // Without a profile the account is gone; a stale hash or marker is replaced by the next one.
        do {
            try vault.delete()
        } catch {
            Self.log.error("Could not delete password hash: \(String(describing: error), privacy: .public)")
        }
        try? FileManager.default.removeItem(at: signedInURL)
        profile = nil
        isSignedIn = false
        isUnavailable = false
        legacySignedIn = false
        throttle = SignInThrottle(clock: clock)
    }

    /// The stored hash, or nil (which never matches) when the Keychain can't give it.
    private func storedHash() -> PasswordHash? {
        do {
            return try vault.read()
        } catch {
            Self.log.error("Could not read password hash: \(String(describing: error), privacy: .public)")
            return nil
        }
    }

    /// Records that you're signed in, for the next launch. A failure only means the next launch
    /// opens Sign in.
    private func markSignedIn() {
        do {
            try writeSignedInMarker()
        } catch {
            Self.log.error("Could not save sign-in state: \(String(describing: error), privacy: .public)")
        }
    }

    private func writeSignedInMarker() throws {
        try Data().write(to: signedInURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    private func save(_ saved: Saved) throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        // The hash never leaves this iPhone, so a profile restored onto another one couldn't be
        // signed in to. Left out of backups, a restored iPhone offers Create account instead.
        var folderURL = folder
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try folderURL.setResourceValues(values)
        try Self.encoder.encode(saved).write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        // What's saved never has version 1's flag.
        legacySignedIn = false
    }

    /// Hashing is deliberately slow, so it runs off the main actor while the button reads busy.
    private static func hash(_ password: String) async throws -> PasswordHash {
        try await Task.detached(priority: .userInitiated) { try PasswordHasher.hash(password) }.value
    }

    private static func verify(_ password: String, against stored: PasswordHash?) async -> Bool {
        guard let stored else { return false }
        return await Task.detached(priority: .userInitiated) { PasswordHasher.verify(password, against: stored) }.value
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

#if DEBUG
extension AccountStore {
    static let seededPassword = "pickleball"

    /// UI check hooks, applied once at launch: `-resetAccount` (Create account), `-seedSignedOut`
    /// (Sign in, with an account for Alex Rivera) or `-seedSignedIn` (Games). The seeded password
    /// is `seededPassword`.
    func applyLaunchArguments() {
        let seedSignedIn = LaunchHooks.take("-seedSignedIn")
        let seedSignedOut = LaunchHooks.take("-seedSignedOut")
        let reset = LaunchHooks.take("-resetAccount")
        let seed = seedSignedIn || seedSignedOut
        guard seed || reset else { return }
        try? resetAccount()
        guard seed else { return }
        let profile = AccountProfile(name: "Alex Rivera", email: "alex@example.com", createdAt: clock())
        do {
            try vault.write(PasswordHasher.hash(Self.seededPassword))
            try save(Saved(profile: profile))
            if seedSignedIn { try writeSignedInMarker() }
        } catch {
            Self.log.error("Could not seed account: \(String(describing: error), privacy: .public)")
            return
        }
        self.profile = profile
        isSignedIn = seedSignedIn
    }
}
#endif
