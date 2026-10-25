import SwiftUI

/// A whole card that acts as one button or navigation link, with pressed and disabled states.
struct CardButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(Theme.Colors.ink)
            .frame(minHeight: Theme.Size.minTouch)
            .card()
            .opacity(isEnabled ? 1 : 0.5)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.snappy(duration: 0.15), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == CardButtonStyle {
    static var card: CardButtonStyle { CardButtonStyle() }
}

#Preview {
    VStack(spacing: Theme.Spacing.m) {
        Button {} label: {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Image(systemName: "square.and.arrow.up").font(Theme.Fonts.title)
                Text("Upload video").font(Theme.Fonts.title)
                Text("Analyze a saved video").font(Theme.Fonts.callout).foregroundStyle(Theme.Colors.inkSecondary)
            }
        }
        .buttonStyle(.card)

        Button {} label: { Text("Disabled while a video is analyzing").font(Theme.Fonts.headline) }
            .buttonStyle(.card)
            .disabled(true)

        Button {} label: {
            Text("A long label that wraps onto more than one line to check the card grows with it")
                .font(Theme.Fonts.headline)
        }
        .buttonStyle(.card)
    }
    .padding(Theme.Spacing.l)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
