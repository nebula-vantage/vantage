import Foundation

/// Slows down password guessing as the web app does: five wrong passwords within five minutes, at
/// sign-in or as the current password when changing it, lock both for 60 seconds. Locking clears
/// the count, so each wait is followed by five more tries. `clock` is injectable for tests.
public struct SignInThrottle {
    public static let failureLimit = 5
    public static let failureWindow: TimeInterval = 5 * 60
    public static let lockout: TimeInterval = 60

    private let clock: () -> Date
    private var failures: [Date] = []
    private var lockedUntil = Date.distantPast

    public init(clock: @escaping () -> Date = Date.init) {
        self.clock = clock
    }

    public var isLocked: Bool { clock() < lockedUntil }

    /// Throws `AccountError.tooManyAttempts` while locked, before any password is checked.
    public func checkUnlocked() throws {
        guard !isLocked else { throw AccountError.tooManyAttempts }
    }

    /// Counts a wrong password and returns the error to show: `.tooManyAttempts` when this one
    /// starts the lockout, otherwise `error` (`.wrongCredentials` at sign-in,
    /// `.wrongCurrentPassword` when changing it). Both share one count.
    public mutating func failure(_ error: AccountError) -> AccountError {
        recordFailure() ? .tooManyAttempts : error
    }

    /// Records a wrong email or password. Returns true when this attempt starts the lockout.
    @discardableResult
    public mutating func recordFailure() -> Bool {
        let now = clock()
        failures.removeAll { now.timeIntervalSince($0) > Self.failureWindow }
        failures.append(now)
        guard failures.count >= Self.failureLimit else { return false }
        failures.removeAll()
        lockedUntil = now.addingTimeInterval(Self.lockout)
        return true
    }

    public mutating func recordSuccess() {
        failures.removeAll()
    }
}
