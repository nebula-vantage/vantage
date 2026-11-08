import XCTest
@testable import VantageKit

final class SignInThrottleTests: XCTestCase {
    private final class Clock {
        var now = Date(timeIntervalSince1970: 1_800_000_000)
        func advance(_ seconds: TimeInterval) { now += seconds }
    }

    private let clock = Clock()
    private lazy var throttle = SignInThrottle { [clock] in clock.now }

    func testFifthFailureWithinFiveMinutesLocksForAMinute() {
        for _ in 0..<4 {
            XCTAssertFalse(throttle.recordFailure())
            clock.advance(60)
        }
        XCTAssertFalse(throttle.isLocked)
        XCTAssertTrue(throttle.recordFailure(), "five failures in four minutes")
        XCTAssertTrue(throttle.isLocked)
        clock.advance(59)
        XCTAssertTrue(throttle.isLocked)
        clock.advance(1)
        XCTAssertFalse(throttle.isLocked, "unlocks after 60 seconds")
    }

    func testFailuresOlderThanFiveMinutesDontCount() {
        XCTAssertFalse(throttle.recordFailure())
        clock.advance(10)
        for _ in 0..<3 { XCTAssertFalse(throttle.recordFailure()) }
        clock.advance(291)  // the first failure is now 301 s old
        XCTAssertFalse(throttle.recordFailure(), "only four failures in the window")
        XCTAssertFalse(throttle.isLocked)
        XCTAssertTrue(throttle.recordFailure())
    }

    func testFailureExactlyFiveMinutesOldStillCounts() {
        XCTAssertFalse(throttle.recordFailure())
        clock.advance(300)
        for _ in 0..<3 { XCTAssertFalse(throttle.recordFailure()) }
        XCTAssertTrue(throttle.recordFailure())
    }

    func testLockoutClearsTheCount() {
        for _ in 0..<5 { throttle.recordFailure() }
        clock.advance(SignInThrottle.lockout)
        for _ in 0..<4 { XCTAssertFalse(throttle.recordFailure()) }
        XCTAssertFalse(throttle.isLocked, "five more tries after the wait")
        XCTAssertTrue(throttle.recordFailure())
    }

    /// Wrong passwords at sign-in and wrong current passwords on the Account screen count together,
    /// and the lockout blocks both, as on the web.
    func testSignInAndPasswordChangeShareOneCount() {
        for _ in 0..<2 { XCTAssertEqual(throttle.failure(.wrongCredentials), .wrongCredentials) }
        for _ in 0..<2 { XCTAssertEqual(throttle.failure(.wrongCurrentPassword), .wrongCurrentPassword) }
        XCTAssertNoThrow(try throttle.checkUnlocked())
        XCTAssertEqual(throttle.failure(.wrongCurrentPassword), .tooManyAttempts, "the fifth, wherever it was typed")
        XCTAssertThrowsError(try throttle.checkUnlocked()) {
            XCTAssertEqual($0 as? AccountError, .tooManyAttempts)
        }
        clock.advance(SignInThrottle.lockout)
        XCTAssertNoThrow(try throttle.checkUnlocked())
        XCTAssertEqual(throttle.failure(.wrongCredentials), .wrongCredentials, "the lockout cleared the count")
    }

    func testSuccessClearsTheCount() {
        for _ in 0..<4 { throttle.recordFailure() }
        throttle.recordSuccess()
        for _ in 0..<4 { XCTAssertFalse(throttle.recordFailure()) }
        XCTAssertFalse(throttle.isLocked)
    }
}
