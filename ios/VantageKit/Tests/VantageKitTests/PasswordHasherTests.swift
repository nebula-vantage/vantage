import XCTest
@testable import VantageKit

final class PasswordHasherTests: XCTestCase {
    private func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }

    /// RFC 7914 §11 PBKDF2-HMAC-SHA256 vectors (first 32 bytes), plus non-ASCII input checked
    /// against Python's `hashlib.pbkdf2_hmac`, so the hash is standard PBKDF2 over UTF-8.
    func testDerivationMatchesKnownVectors() throws {
        XCTAssertEqual(hex(try PasswordHasher.derive("passwd", salt: Data("salt".utf8), iterations: 1, length: 32)),
                       "55ac046e56e3089fec1691c22544b605f94185216dde0465e68b9d57c20dacbc")
        XCTAssertEqual(hex(try PasswordHasher.derive("Password", salt: Data("NaCl".utf8), iterations: 80_000, length: 32)),
                       "4ddcd8f60b98be21830cee5ef22701f9641a4418d04c0414aeff08876b34ab56")
        XCTAssertEqual(hex(try PasswordHasher.derive("pässwörd🙂", salt: Data(0..<16), iterations: 1_000, length: 32)),
                       "08b53c8b2a3382b79e3517079963f0662440fb165f588e297feddcf9fa006720")
    }

    func testDefaultHashUsesAFreshSaltAndTheSpecIterations() throws {
        XCTAssertEqual(PasswordHasher.defaultIterations, 600_000, "docs/app-experience.md")
        let first = try PasswordHasher.hash("correct horse")
        let second = try PasswordHasher.hash("correct horse")
        XCTAssertEqual(first.iterations, PasswordHasher.defaultIterations)
        XCTAssertEqual(first.salt.count, 16)
        XCTAssertEqual(first.hash.count, 32)
        XCTAssertNotEqual(first.salt, second.salt)
        XCTAssertNotEqual(first.hash, second.hash)
        XCTAssertTrue(PasswordHasher.verify("correct horse", against: first))
        XCTAssertFalse(PasswordHasher.verify("correct horsf", against: first))
    }

    func testVerify() throws {
        let stored = try PasswordHasher.hash("pickleball", iterations: 1_000)
        XCTAssertTrue(PasswordHasher.verify("pickleball", against: stored))
        XCTAssertFalse(PasswordHasher.verify("Pickleball", against: stored))
        XCTAssertFalse(PasswordHasher.verify("pickleball ", against: stored))
        XCTAssertFalse(PasswordHasher.verify("", against: stored))
        // The stored iteration count is used, not the current default.
        XCTAssertFalse(PasswordHasher.verify("pickleball", against: PasswordHash(
            salt: stored.salt, hash: stored.hash, iterations: 1_001)))
        XCTAssertFalse(PasswordHasher.verify("pickleball", against: PasswordHash(
            salt: stored.salt, hash: Data(), iterations: stored.iterations)), "an empty hash never matches")
        XCTAssertFalse(PasswordHasher.verify("pickleball", against: PasswordHash(
            salt: stored.salt, hash: stored.hash, iterations: 0)))
    }

    func testConstantTimeEquals() {
        XCTAssertTrue(PasswordHasher.constantTimeEquals(Data([1, 2, 3]), Data([1, 2, 3])))
        XCTAssertTrue(PasswordHasher.constantTimeEquals(Data(), Data()))
        XCTAssertFalse(PasswordHasher.constantTimeEquals(Data([1, 2, 3]), Data([1, 2, 4])))
        XCTAssertFalse(PasswordHasher.constantTimeEquals(Data([0, 2, 3]), Data([1, 2, 3])))
        XCTAssertFalse(PasswordHasher.constantTimeEquals(Data([1, 2, 3]), Data([1, 2])))
    }

    func testHashRoundTripsThroughJSON() throws {
        let stored = try PasswordHasher.hash("pickleball", iterations: 1_000)
        let decoded = try JSONDecoder().decode(PasswordHash.self, from: JSONEncoder().encode(stored))
        XCTAssertEqual(decoded, stored)
        XCTAssertTrue(PasswordHasher.verify("pickleball", against: decoded))
    }
}
