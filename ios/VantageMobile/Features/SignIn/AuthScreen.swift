import SwiftUI

/// The layout both sign-in screens share: the dark brand panel above the form, which sits on the
/// page background (side by side on the web's desktop layout, stacked on the phone), and the
/// footnote under it.
struct AuthScreen<Form: View>: View {
    @ViewBuilder let form: Form

    @State private var panelHeight: CGFloat = 0
    /// Whether the panel is still behind the status bar, which then draws in white.
    @State private var panelUnderStatusBar = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                BrandPanel()
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { panelHeight = $0 }
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    form
                    StatusNote("Your account and games are saved on this iPhone.")
                }
                .padding(.horizontal, Theme.Spacing.xl)
                .padding(.top, Theme.Spacing.xxl)
                .padding(.bottom, Theme.Spacing.xl)
                .background(Theme.Colors.background)
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .onScrollGeometryChange(for: Bool.self) { geometry in
            // The visible rect starts at the top of the screen; the status bar fills the top inset.
            geometry.visibleRect.minY + geometry.contentInsets.top / 2 < panelHeight
        } action: { _, underStatusBar in
            panelUnderStatusBar = underStatusBar
        }
        #if DEBUG
        .debugScrollAnchor("sign-in screens")
        #endif
        // The panel colour runs under the status bar and shows when you pull past the top; the
        // page colour shows past the bottom.
        .background {
            VStack(spacing: 0) {
                Theme.Colors.videoBackground
                Theme.Colors.background
            }
            .ignoresSafeArea()
        }
        .statusBar(overPanel: panelUnderStatusBar)
    }
}

private extension View {
    /// White status bar text over the panel, dark over the form. Before iOS 27 the style can't be
    /// set per screen, so the status bar is hidden rather than drawn dark on dark.
    @ViewBuilder func statusBar(overPanel: Bool) -> some View {
        if #available(iOS 27.0, *) {
            toolbarColorScheme(overPanel ? .dark : .light, for: .statusBar)
        } else {
            statusBarHidden()
        }
    }
}

/// The wordmark, the headline, three short lines and the court, on the panel colour.
private struct BrandPanel: View {
    private static let points = [
        (icon: "tray.and.arrow.up", text: "Upload a match from one fixed camera."),
        (icon: "scope", text: "See the rally, the ball and the court."),
        (icon: "checkmark", text: "Take a focused plan into your next session."),
    ]

    /// Keeps the icons in one column as the text scales.
    @ScaledMetric(relativeTo: .subheadline) private var iconWidth = Theme.Size.brandIcon

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
                Wordmark(large: true, onDark: true)
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    Text("Your game.\nA new perspective.")
                        .font(Theme.Fonts.display)
                        .tracking(Theme.Fonts.displayTracking)
                        .foregroundStyle(Theme.Colors.headingOnDark)
                        .fixedSize(horizontal: false, vertical: true)
                    VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                        ForEach(Self.points, id: \.text) { point in
                            HStack(alignment: .firstTextBaseline, spacing: Theme.Spacing.m) {
                                // Regular weight, like the web's line icons (1.8 stroke in 20px).
                                Image(systemName: point.icon)
                                    .fontWeight(.regular)
                                    .foregroundStyle(Theme.Colors.accent)
                                    .frame(width: iconWidth)
                                    .accessibilityHidden(true)
                                Text(point.text)
                                    .foregroundStyle(Theme.Colors.inkOnDark)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .font(Theme.Fonts.callout)
                }
            }
            .padding(.horizontal, Theme.Spacing.xl)
            // The status bar above already gives the wordmark room.
            .padding(.top, Theme.Spacing.s)
            CourtMotif()
                .frame(maxWidth: .infinity)
                .frame(height: Theme.Size.courtMotif)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.Colors.videoBackground)
    }
}

/// Eyebrow, title and one line of body at the top of the form.
struct FormHeader: View {
    let eyebrow: String
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text(eyebrow).monoLabel()
            Text(title)
                .font(Theme.Fonts.formTitle)
                .tracking(Theme.Fonts.displayTracking)
                .foregroundStyle(Theme.Colors.ink)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            Text(message)
                .font(Theme.Fonts.callout)
                .foregroundStyle(Theme.Colors.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
