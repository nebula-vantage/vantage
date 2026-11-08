import XCTest
@testable import VantageKit

final class AccountTests: XCTestCase {
    /// The strings are shared word for word with the web app (docs/app-experience.md).
    func testMessagesMatchTheSpec() {
        XCTAssertEqual(AccountError.invalidName.message, "Enter your name.")
        XCTAssertEqual(AccountError.invalidEmail.message, "Enter a valid email address.")
        XCTAssertEqual(AccountError.invalidPassword.message, "Use at least 8 characters.")
        XCTAssertEqual(AccountError.wrongCredentials.message, "That email and password don't match.")
        XCTAssertEqual(AccountError.tooManyAttempts.message, "Too many attempts. Wait a minute and try again.")
        XCTAssertEqual(AccountError.wrongCurrentPassword.message, "Your current password isn't right.")
        XCTAssertEqual(AccountError.invalidName.localizedDescription, "Enter your name.")
    }

    func testNameIsTrimmedAndLimitedTo80Characters() throws {
        XCTAssertEqual(try AccountValidation.name("  Alex   Rivera \n"), "Alex Rivera")
        XCTAssertEqual(try AccountValidation.name(String(repeating: "a", count: 80)).count, 80)
        XCTAssertEqual(try AccountValidation.name("  " + String(repeating: "a", count: 80) + "  ").count, 80)
        for invalid in ["", "   ", "\n\t", String(repeating: "a", count: 81)] {
            XCTAssertThrowsError(try AccountValidation.name(invalid)) {
                XCTAssertEqual($0 as? AccountError, .invalidName)
            }
        }
        // Python counts code points: "é" written as e + combining accent is two.
        XCTAssertThrowsError(try AccountValidation.name(String(repeating: "e\u{301}", count: 41)))
    }

    func testEmailIsTrimmedLowercasedAndChecked() throws {
        XCTAssertEqual(try AccountValidation.email("  Alex.Rivera@Example.COM \n"), "alex.rivera@example.com")
        XCTAssertEqual(try AccountValidation.email("a@b.co"), "a@b.co")
        XCTAssertEqual(try AccountValidation.email("first+tag@sub.example.org"), "first+tag@sub.example.org")
        for invalid in ["", "alex", "alex@", "@example.com", "alex@example", "alex@@example.com",
                        "alex rivera@example.com", "alex@exa mple.com", "alex@example.", "alex@.com"] {
            XCTAssertThrowsError(try AccountValidation.email(invalid), invalid) {
                XCTAssertEqual($0 as? AccountError, .invalidEmail)
            }
        }
    }

    func testEmailIsLimitedTo254Characters() throws {
        let domain = "@example.com"
        let longest = String(repeating: "a", count: 254 - domain.count) + domain
        XCTAssertEqual(try AccountValidation.email(longest), longest)
        XCTAssertThrowsError(try AccountValidation.email("a" + longest))
        XCTAssertEqual(try AccountValidation.email("  " + longest.uppercased() + "  "), longest, "limit applies after trimming")
    }

    func testPasswordIs8To128Characters() {
        XCTAssertNoThrow(try AccountValidation.password("12345678"))
        XCTAssertNoThrow(try AccountValidation.password(String(repeating: "p", count: 128)))
        XCTAssertNoThrow(try AccountValidation.password("        "), "spaces count and aren't trimmed")
        for invalid in ["", "1234567", String(repeating: "p", count: 129)] {
            XCTAssertThrowsError(try AccountValidation.password(invalid)) {
                XCTAssertEqual($0 as? AccountError, .invalidPassword)
            }
        }
    }

    func testFirstNameAndInitials() {
        func profile(_ name: String) -> AccountProfile {
            AccountProfile(name: name, email: "a@b.co", createdAt: .distantPast)
        }
        XCTAssertEqual(profile("Alex Rivera").firstName, "Alex")
        XCTAssertEqual(profile("Alex").firstName, "Alex")
        XCTAssertEqual(profile("Alex Rivera").initials, "AR")
        XCTAssertEqual(profile("alex de la rivera").initials, "AR")
        XCTAssertEqual(profile("Alex").initials, "A")
        XCTAssertEqual(profile("Émile Zola").initials, "ÉZ")
        XCTAssertEqual(profile("").initials, "?")
    }

    func testProfileRoundTripsThroughJSON() throws {
        let profile = AccountProfile(name: "Alex Rivera", email: "alex@example.com",
                                     createdAt: Date(timeIntervalSince1970: 1_800_000_000))
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        XCTAssertEqual(try decoder.decode(AccountProfile.self, from: encoder.encode(profile)), profile)
    }
}
