import SwiftUI

/// The one primary action on a screen ("Create account", "Sign in"): full width, ink, as the web
/// app's `.button-primary`.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.Fonts.button)
            .foregroundStyle(Theme.Colors.surface)
            .multilineTextAlignment(.center)
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.vertical, Theme.Spacing.m)
            .frame(maxWidth: .infinity, minHeight: Theme.Size.primaryButton)
            .background(Theme.Colors.ink, in: .rect(cornerRadius: Theme.Radius.control, style: .continuous))
            .opacity(isEnabled ? (configuration.isPressed ? 0.85 : 1) : 0.5)
    }
}

/// Actions that still look like buttons but aren't the screen's main one ("Save changes",
/// "Sign out"): white with a hairline and as wide as the label, as the web app's `.button-secondary`.
struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
        configuration.label
            .font(Theme.Fonts.button)
            .foregroundStyle(Theme.Colors.ink)
            .multilineTextAlignment(.center)
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.vertical, Theme.Spacing.m)
            .frame(minHeight: Theme.Size.minTouch)
            .background(configuration.isPressed ? Theme.Colors.background : Theme.Colors.surface, in: shape)
            .overlay { shape.strokeBorder(Theme.Colors.hairline, lineWidth: Theme.Size.hairline) }
            .contentShape(shape)
            .opacity(isEnabled ? 1 : 0.5)
    }
}

/// A link-like action ("Forgot password?"): underlined secondary text, full touch height, as the
/// web app's `.link-button`.
struct TextButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.Fonts.footnote)
            .underline()
            .foregroundStyle(configuration.isPressed ? Theme.Colors.ink : Theme.Colors.inkSecondary)
            .frame(minHeight: Theme.Size.minTouch)
            .contentShape(.rect)
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var primary: PrimaryButtonStyle { PrimaryButtonStyle() }
}

extension ButtonStyle where Self == SecondaryButtonStyle {
    static var secondary: SecondaryButtonStyle { SecondaryButtonStyle() }
}

extension ButtonStyle where Self == TextButtonStyle {
    static var text: TextButtonStyle { TextButtonStyle() }
}

#Preview {
    VStack(spacing: Theme.Spacing.m) {
        Button("Create account") {}.buttonStyle(.primary)
        Button("Creating account…") {}.buttonStyle(.primary).disabled(true)
        Button("Save changes") {}.buttonStyle(.secondary)
        Button("Save changes") {}.buttonStyle(.secondary).disabled(true)
        Button("Forgot password?") {}.buttonStyle(.text)
        Button("A long label that wraps onto more than one line at large text sizes") {}.buttonStyle(.primary)
            .dynamicTypeSize(.accessibility2)
    }
    .padding(Theme.Spacing.l)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
