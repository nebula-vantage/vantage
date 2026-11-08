import SwiftUI

/// Your initials in mono in an ink circle ("AR"), as the web's `.avatar`: the Account button in the
/// Games header and the Account screen's header. Grows with Dynamic Type so the letters never overflow.
struct InitialsAvatar: View {
    let initials: String
    var large = false

    @ScaledMetric(relativeTo: .headline) private var scale: CGFloat = 1

    var body: some View {
        let side = (large ? Theme.Size.avatarLarge : Theme.Size.avatar) * scale
        Text(initials)
            .font(large ? Theme.Fonts.initialsLarge : Theme.Fonts.initials)
            .tracking(Theme.Fonts.initialsTracking)
            .foregroundStyle(Theme.Colors.surface)
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            .padding(Theme.Spacing.xs)
            .frame(width: side, height: side)
            .background(Theme.Colors.ink, in: .circle)
    }
}

#Preview {
    HStack(spacing: Theme.Spacing.l) {
        InitialsAvatar(initials: "AR")
        InitialsAvatar(initials: "W")
        InitialsAvatar(initials: "AR", large: true)
        InitialsAvatar(initials: "AR").dynamicTypeSize(.accessibility3)
    }
    .padding(Theme.Spacing.l)
    .background(Theme.Colors.background)
}
