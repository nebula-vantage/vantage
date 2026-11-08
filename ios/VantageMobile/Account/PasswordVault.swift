import Foundation
import Security
import VantageKit

/// The account's password hash and salt, kept in the Keychain as one generic-password item. It's
/// readable once the iPhone has been unlocked after a restart, and never leaves this device: no
/// iCloud Keychain, and backups restored onto another iPhone don't include it.
struct PasswordVault {
    struct Failure: Error {
        let status: OSStatus
    }

    var service = "Vantage account"
    private let account = "password-hash"

    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    /// The stored hash, or nil when there isn't one.
    func read() throws -> PasswordHash? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw Failure(status: status) }
        return try JSONDecoder().decode(PasswordHash.self, from: data)
    }

    /// Replaces the stored hash in place, so a failure never leaves the account without one.
    func write(_ hash: PasswordHash) throws {
        let attributes: [String: Any] = [
            kSecValueData as String: try JSONEncoder().encode(hash),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes) { $1 } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw Failure(status: status) }
    }

    func delete() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure(status: status) }
    }
}
