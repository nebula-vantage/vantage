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

    /// Video length as h:mm:ss ("0:38:12").
    static func duration(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite else { return missing }
        return Duration.seconds(seconds.rounded()).formatted(.time(pattern: .hourMinuteSecond))
    }

    /// "Today, 6:10 PM", "Yesterday, 6:10 PM", "Sat, Oct 3", or "Oct 3, 2025" in another year.
    static func gameDate(_ date: Date, now: Date = .now, calendar: Calendar = .current) -> String {
        let time = date.formatted(date: .omitted, time: .shortened)
        if calendar.isDate(date, inSameDayAs: now) { return "Today, \(time)" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
           calendar.isDate(date, inSameDayAs: yesterday) {
            return "Yesterday, \(time)"
        }
        if calendar.isDate(date, equalTo: now, toGranularity: .year) {
            return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
        }
        return date.formatted(.dateTime.month(.abbreviated).day().year())
    }
}
