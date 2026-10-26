import SwiftUI

/// One stat: mono label, big value and an optional unit ("AVG SPEED · 31 · km/h"). Takes
/// formatted strings; a `Format.missing` value is read to VoiceOver as "Not measured".
struct StatTile: View {
    let label: String
    let value: String
    var unit: String? = nil

    private var spokenValue: String {
        value == Format.missing ? "Not measured" : [value, unit].compactMap { $0 }.joined(separator: " ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(label).monoLabel()
            Text(value)
                .font(Theme.Fonts.number)
                .foregroundStyle(Theme.Colors.ink)
                .monospacedDigit()
            if let unit {
                Text(unit)
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
            }
        }
        // Fill the row so tiles side by side share a height.
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .card()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityValue(spokenValue)
    }
}

#Preview {
    ScrollView {
        VStack(spacing: Theme.Spacing.m) {
            Grid(horizontalSpacing: Theme.Spacing.m, verticalSpacing: Theme.Spacing.m) {
                GridRow {
                    StatTile(label: "Rallies", value: "58")
                    StatTile(label: "Avg rally", value: "7.1", unit: "shots")
                    StatTile(label: "Longest", value: Format.missing, unit: "shots")
                }
                GridRow {
                    StatTile(label: "Avg speed", value: "31", unit: Format.kmh)
                    StatTile(label: "A long label that wraps", value: "1,204")
                    StatTile(label: "Tracked", value: "97%", unit: "of frames")
                }
            }
            StatTile(label: "Distance", value: Format.missing, unit: Format.metres)
                .dynamicTypeSize(.accessibility3)
        }
        .padding(Theme.Spacing.l)
    }
    .background(Theme.Colors.background)
}
