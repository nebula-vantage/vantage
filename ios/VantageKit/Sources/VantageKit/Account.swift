import Foundation

/// The account's profile as stored on the device. The password hash is kept apart from it, in the
/// Keychain. Rules and messages match the web app's `pipeline/vantage/accounts.py` word for word
/// (docs/app-experience.md).
public struct AccountProfile: Codable, Equatable, Sendable {
    public let id: UUID
    public var name: String
    public var email: String
    public let createdAt: Date

    public init(id: UUID = UUID(), name: String, email: String, createdAt: Date) {
        self.id = id
        self.name = name
        self.email = email
        self.createdAt = createdAt
    }

    /// "Alex Rivera" → "Alex", for "Pick up where you left off, Alex."
    public var firstName: String {
        name.split(whereSeparator: \.isWhitespace).first.map(String.init) ?? name
    }

    /// First letters of the first and last words: "Alex de la Rivera" → "AR", "Alex" → "A".
    public var initials: String {
        let words = name.split(whereSeparator: \.isWhitespace)
        let letters = [words.first, words.count > 1 ? words.last : nil].compactMap { $0?.first }
        return letters.isEmpty ? "?" : String(letters).uppercased()
    }
}

/// Why an account action failed, with the exact message both apps show.
public enum AccountError: Error, Equatable, Sendable, LocalizedError {
    case invalidName
    case invalidEmail
    case invalidPassword
    case wrongCredentials
    case tooManyAttempts
    case wrongCurrentPassword

    public var message: String {
        switch self {
        case .invalidName: "Enter your name."
        case .invalidEmail: "Enter a valid email address."
        case .invalidPassword: "Use at least 8 characters."
        case .wrongCredentials: "That email and password don't match."
        case .tooManyAttempts: "Too many attempts. Wait a minute and try again."
        case .wrongCurrentPassword: "Your current password isn't right."
        }
    }

    public var errorDescription: String? { message }
}

/// Checks and normalizes what someone types into the account forms. Lengths count Unicode scalars,
/// as Python's `len` does on the web, so both apps accept exactly the same values.
public enum AccountValidation {
    public static let maxNameLength = 80
    public static let maxEmailLength = 254
    public static let passwordLengths = 8...128

    /// The name as stored: trimmed, with runs of inner whitespace collapsed to one space.
    public static func name(_ raw: String) throws -> String {
        let name = raw.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !name.isEmpty, name.unicodeScalars.count <= maxNameLength else { throw AccountError.invalidName }
        return name
    }

    /// The email as stored, if it's a plausible address of at most 254 characters.
    public static func email(_ raw: String) throws -> String {
        let email = normalizedEmail(raw)
        guard email.unicodeScalars.count <= maxEmailLength,
              email.firstMatch(of: #/^[^@\s]+@[^@\s]+\.[^@\s]+$/#) != nil else { throw AccountError.invalidEmail }
        return email
    }

    /// Trimmed and lowercased, the form an email is stored and compared in.
    public static func normalizedEmail(_ raw: String) -> String {
        raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    public static func password(_ password: String) throws {
        guard passwordLengths.contains(password.unicodeScalars.count) else { throw AccountError.invalidPassword }
    }
}
