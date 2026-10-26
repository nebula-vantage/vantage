import SwiftUI
import UIKit

/// Design tokens. Screens use these, `Format` and `Components/` instead of literal colours,
/// fonts or spacing. Values match the mockups in vantage-design.
enum Theme {
    enum Colors {
        static let background = Color(hex: 0xF5F6F8)
        /// Cards and other raised surfaces.
        static let surface = Color(hex: 0xFFFFFF)
        static let ink = Color(hex: 0x0F141A)
        static let inkSecondary = Color(hex: 0x5B6573)
        static let inkTertiary = Color(hex: 0x9096A0)
        /// Card borders and dividers.
        static let hairline = Color(hex: 0xDCE0E6)
        /// Unfilled part of progress bars.
        static let track = Color(hex: 0xE9ECF0)
        /// The one accent colour.
        static let accent = Color(hex: 0xE8590C)
        /// Completed steps and positive calls.
        static let positive = Color(hex: 0x0F766E)
        /// The opponent's marker; the user's is `accent`.
        static let opponent = Color(hex: 0x1D4ED8)

        /// Behind the video before it draws.
        static let videoBackground = Color(hex: 0x151B22)
        /// Badges drawn over video.
        static let scrim = Color(hex: 0x080B0E).opacity(0.8)
        /// Positive text on a scrim ("94% of frames tracked").
        static let positiveOnDark = Color(hex: 0x7EE2C9)

        static let courtSurround = Color(hex: 0xCFD8DF)
        static let courtSurface = Color(hex: 0xE7ECEF)
        static let courtLine = Color(hex: 0xFFFFFF)
    }

    /// Bricolage Grotesque for headings and numbers, IBM Plex Sans for body, IBM Plex Mono for labels.
    /// Each size equals its text style's default, so the system fallback looks the same size and
    /// both scale with Dynamic Type.
    enum Fonts {
        static let display = resolve("BricolageGrotesque-ExtraBold", size: 34, relativeTo: .largeTitle,
                                      weight: .heavy)
        /// Stat values ("214").
        static let number = resolve("BricolageGrotesque-ExtraBold", size: 28, relativeTo: .title, weight: .heavy)
        static let title = resolve("BricolageGrotesque-Bold", size: 20, relativeTo: .title3, weight: .bold)
        static let headline = resolve("IBMPlexSans-SemiBold", size: 17, relativeTo: .headline, weight: .semibold)
        static let body = resolve("IBMPlexSans-Regular", size: 17, relativeTo: .body, weight: .regular)
        static let callout = resolve("IBMPlexSans-Regular", size: 15, relativeTo: .subheadline, weight: .regular)
        static let label = resolve("IBMPlexMono-Medium", size: 12, relativeTo: .caption, weight: .medium,
                                   design: .monospaced)
        static let labelTracking: CGFloat = 1.2

        /// The bundled face when it's registered, otherwise the system font for the same text style,
        /// so adding the font files later changes no screen code.
        private static func resolve(_ name: String, size: CGFloat, relativeTo style: Font.TextStyle,
                                    weight: Font.Weight, design: Font.Design = .default) -> Font {
            if UIFont(name: name, size: size) != nil { return .custom(name, size: size, relativeTo: style) }
            return .system(style, design: design, weight: weight)
        }
    }

    enum Spacing {
        static let xxs: CGFloat = 2
        static let xs: CGFloat = 4
        static let s: CGFloat = 8
        static let m: CGFloat = 12
        static let l: CGFloat = 16
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 32
    }

    enum Radius {
        static let card: CGFloat = 18
        /// The selected segment inside a card-radius track.
        static let segment: CGFloat = 14
        static let badge: CGFloat = 8
    }

    enum Size {
        /// Minimum height and width of anything tappable.
        static let minTouch: CGFloat = 44
        static let hairline: CGFloat = 1
        static let progressBar: CGFloat = 6
        static let playButton: CGFloat = 56
        /// Player colour dots (toggle, legends).
        static let dot: CGFloat = 8
        static let landingDot: CGFloat = 10
        static let courtLine: CGFloat = 2
        /// A full court is tall; this keeps it to about half a phone screen.
        static let courtMaxWidth: CGFloat = 240
    }
}

extension View {
    /// Mono caps for eyebrows and metadata ("VANTAGE", "5 GAMES", "PICKLEBALL · UPLOADED").
    func monoLabel() -> some View {
        font(Theme.Fonts.label)
            .textCase(.uppercase)
            .tracking(Theme.Fonts.labelTracking)
            .foregroundStyle(Theme.Colors.inkSecondary)
    }
}

private extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}
