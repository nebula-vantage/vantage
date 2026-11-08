import Foundation

/// All number, unit and date formatting the UI shows. A value that wasn't measured is nil and
/// renders as `missing`, never as 0.
enum Format {
    static let missing = "—"

    static func count(_ value: Int?) -> String {
        value.map { $0.formatted() } ?? missing
    }

    /// "1 rally", "9 rallies", "— rallies".
    static func count(_ value: Int?, _ singular: String, _ plural: String) -> String {
        "\(count(value)) \(value == 1 ? singular : plural)"
    }

    static let kmh = "km/h"
    static let metres = "m"

    /// 7.08 → "7.1".
    static func decimal(_ value: Double?, digits: Int = 1) -> String {
        value.map { $0.formatted(.number.precision(.fractionLength(digits))) } ?? missing
    }

    /// Ball speed in whole km/h (unit shown separately).
    static func speed(_ kmh: Double?) -> String { decimal(kmh, digits: 0) }

    /// Distance in whole metres (unit shown separately).
    static func distance(_ metres: Double?) -> String { decimal(metres, digits: 0) }

    /// 0.62 → "62%".
    static func percent(_ fraction: Double?) -> String {
        fraction.map { $0.formatted(.percent.precision(.fractionLength(0))) } ?? missing
    }

    /// Video length as m:ss under an hour ("38:12"), as on the web, then h:mm:ss ("1:02:05").
    static func duration(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite else { return missing }
        let rounded = seconds.rounded()
        return Duration.seconds(rounded).formatted(.time(pattern: rounded < 3_600 ? .minuteSecond : .hourMinuteSecond))
    }

    /// "Analyzed Nov 7, 2026", as on the web app's game cards.
    static func analyzedDate(_ date: Date) -> String {
        "Analyzed \(date.formatted(.dateTime.month(.abbreviated).day().year()))"
    }
}
