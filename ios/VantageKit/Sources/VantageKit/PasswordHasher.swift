import CommonCrypto
import Foundation
import Security

/// A salted PBKDF2-HMAC-SHA256 password hash. The iteration count is stored with it, so a later
/// version can raise the default without locking out existing accounts.
public struct PasswordHash: Codable, Equatable, Sendable {
    public let salt: Data
    public let hash: Data
    public let iterations: Int

    public init(salt: Data, hash: Data, iterations: Int) {
        self.salt = salt
        self.hash = hash
        self.iterations = iterations
    }
}

public enum PasswordHasher {
    /// OWASP's recommendation for PBKDF2-HMAC-SHA256 (2023), the count docs/app-experience.md
    /// specifies.
    public static let defaultIterations = 600_000
    public static let saltLength = 16
    static let hashLength = 32

    public enum Failure: Error {
        case randomBytesUnavailable(OSStatus)
        case derivationFailed(Int32)
    }

    /// A new hash with a fresh random salt. Takes a noticeable fraction of a second by design, so
    /// call it off the main actor.
    public static func hash(_ password: String, iterations: Int = defaultIterations) throws -> PasswordHash {
        var salt = Data(count: saltLength)
        let status = salt.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, saltLength, $0.baseAddress!) }
        guard status == errSecSuccess else { throw Failure.randomBytesUnavailable(status) }
        let hash = try derive(password, salt: salt, iterations: iterations, length: hashLength)
        return PasswordHash(salt: salt, hash: hash, iterations: iterations)
    }

    /// Whether `password` produces `stored`, compared in constant time so the time taken doesn't
    /// reveal how much of the hash matched.
    public static func verify(_ password: String, against stored: PasswordHash) -> Bool {
        guard !stored.hash.isEmpty,
              let actual = try? derive(password, salt: stored.salt, iterations: stored.iterations,
                                       length: stored.hash.count) else { return false }
        return constantTimeEquals(actual, stored.hash)
    }

    static func derive(_ password: String, salt: Data, iterations: Int, length: Int) throws -> Data {
        guard (1...Int(UInt32.max)).contains(iterations), length > 0 else { throw Failure.derivationFailed(-1) }
        var key = Data(count: length)
        // `utf8CString` always has a buffer (its NUL terminator, not counted), even for "".
        let status = password.utf8CString.withUnsafeBufferPointer { passwordBytes in
            salt.withUnsafeBytes { saltBytes in
                key.withUnsafeMutableBytes { keyBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2), passwordBytes.baseAddress, passwordBytes.count - 1,
                        saltBytes.bindMemory(to: UInt8.self).baseAddress, salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), UInt32(iterations),
                        keyBytes.bindMemory(to: UInt8.self).baseAddress, length)
                }
            }
        }
        guard status == kCCSuccess else { throw Failure.derivationFailed(status) }
        return key
    }

    /// Looks at every byte whatever the first difference, so equal-length inputs take the same time.
    static func constantTimeEquals(_ a: Data, _ b: Data) -> Bool {
        guard a.count == b.count else { return false }
        var difference: UInt8 = 0
        for (x, y) in zip(a, b) { difference |= x ^ y }
        return difference == 0
    }
}
