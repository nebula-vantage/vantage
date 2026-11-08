import SwiftUI

/// A sentence led by a positive dot ("Your account and games are saved on this iPhone."), as the
/// web's `.status-dot` notes: under the sign-in forms, on the Account screen and on game cards.
struct StatusNote: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    /// About as tall as the lowercase letters, and standing on the baseline, at every text size.
    @ScaledMetric(relativeTo: .footnote) private var dot = Theme.Size.dot

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.Spacing.s) {
            Circle()
                .fill(Theme.Colors.positive)
                .frame(width: dot, height: dot)
                .alignmentGuide(.firstTextBaseline) { $0[.bottom] }
                .accessibilityHidden(true)
            Text(text)
                .font(Theme.Fonts.footnote)
                .foregroundStyle(Theme.Colors.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

#Preview {
    VStack(alignment: .leading, spacing: Theme.Spacing.l) {
        StatusNote("Your account and games are saved on this iPhone.")
        StatusNote("Your account and games are saved on this iPhone. Videos are analyzed on the device.")
            .dynamicTypeSize(.accessibility2)
    }
    .padding(Theme.Spacing.l)
    .background(Theme.Colors.background)
}
