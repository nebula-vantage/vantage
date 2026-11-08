import CoreText
import os
import SwiftUI
import UIKit

/// Design tokens. Screens use these, `Format` and `Components/` instead of literal colours,
/// fonts or spacing. Values match the mockups in vantage-design and the web app
/// (docs/app-experience.md).
enum Theme {
    enum Colors {
        static let background = Color(hex: 0xF5F6F8)
        /// Cards and other raised surfaces.
        static let surface = Color(hex: 0xFFFFFF)
        static let ink = Color(hex: 0x0F141A)
        static let inkSecondary = Color(hex: 0x5B6573)
        static let inkTertiary = Color(hex: 0x9096A0)
        /// Text field placeholders ("you@example.com"), the web's `--placeholder`.
        static let placeholder = Color(hex: 0x6D7784)
        /// Card borders and dividers.
        static let hairline = Color(hex: 0xDCE0E6)
        /// The empty library's faint white fill, the web's `#ffffff75`.
        static let surfaceFaint = Color(hex: 0xFFFFFF).opacity(0.46)
        /// Unfilled part of progress bars.
        static let track = Color(hex: 0xE9ECF0)
        /// The one accent colour.
        static let accent = Color(hex: 0xE8590C)
        /// Accent at partial strength, for uncertain marks (close calls).
        static let accentMuted = Color(hex: 0xE8590C).opacity(0.4)
        /// Completed steps and positive calls.
        static let positive = Color(hex: 0x0F766E)
        /// The opponent's marker; the user's is `accent`.
        static let opponent = Color(hex: 0x1D4ED8)
        /// Form errors ("Enter a valid email address."), the web app's error text colour.
        static let error = Color(hex: 0x9D3027)
        /// The tinted box behind errors that belong to the whole form ("That email and password
        /// don't match."), and its border.
        static let errorSurface = Color(hex: 0xFFF7F5)
        static let errorLine = Color(hex: 0xE3BBB6)

        /// The sign-in screens' brand panel, and behind the video before it draws.
        static let videoBackground = Color(hex: 0x151B22)
        /// The headline and wordmark on the brand panel.
        static let headingOnDark = Color(hex: 0xFFFFFF)
        /// Body text on the brand panel ("Upload a match from one fixed camera.").
        static let inkOnDark = Color(hex: 0xC3CCD5)
        /// Badges drawn over video.
        static let scrim = Color(hex: 0x080B0E).opacity(0.8)
        /// Positive text on a scrim ("94% of frames tracked").
        static let positiveOnDark = Color(hex: 0x7EE2C9)
        /// The soft ring around a focused text field, the web's `#0f766e40` outline.
        static let focusRing = Color(hex: 0x0F766E).opacity(0.25)

        static let courtSurround = Color(hex: 0xCFD8DF)
        static let courtSurface = Color(hex: 0xE7ECEF)
        static let courtLine = Color(hex: 0xFFFFFF)

        /// The perspective court at the bottom of the brand panel (the web's `auth-court` SVG).
        static let courtMotifFill = Color(hex: 0x1E2C35)
        static let courtMotifLine = Color(hex: 0x405662)
        static let courtMotifNet = Color(hex: 0x6E8390)
    }

    /// Bricolage Grotesque for headings and numbers, IBM Plex Sans for body, IBM Plex Mono for labels.
    /// Each size equals its text style's default, so the system fallback looks the same size and
    /// both scale with Dynamic Type.
    enum Fonts {
        static let display = resolve(bricolageExtraBold, size: 34, relativeTo: .largeTitle, weight: .heavy)
        /// The web's tight heading spacing (-1.3px at 32-36px), for the sign-in headline and titles.
        static let displayTracking: CGFloat = -1
        /// A page's title ("Games"), as the web's page header at phone width (36px, -1.1px).
        static let pageTitle = resolve(bricolageExtraBold, size: 36, relativeTo: .largeTitle, weight: .heavy)
        static let pageTitleTracking: CGFloat = -1.1
        /// The sign-in forms' titles ("Sign in to Vantage"), as the web at phone width (32px).
        static let formTitle = resolve(bricolageExtraBold, size: 32, relativeTo: .largeTitle, weight: .heavy)
        /// The name on the Account screen and the empty library's title, as the web's 26px headings.
        static let heading = resolve(bricolageBold, size: 26, relativeTo: .title, weight: .bold)
        static let headingTracking: CGFloat = -0.6
        /// The upload tile's title ("Bring your game into focus."), as the web at phone width (22px).
        static let tileTitle = resolve(bricolageExtraBold, size: 22, relativeTo: .title2, weight: .heavy)
        static let tileTitleTracking: CGFloat = -0.7
        /// Stat values ("214").
        static let number = resolve(bricolageExtraBold, size: 28, relativeTo: .title, weight: .heavy)
        static let title = resolve(bricolageBold, size: 20, relativeTo: .title3, weight: .bold)
        /// "vantage." in the Games header; `wordmarkLarge` on the sign-in screens. The tracking is the
        /// landing page's (-1.4px at 32px) at each size.
        static let wordmark = resolve(bricolageBold, size: 22, relativeTo: .title2, weight: .bold)
        static let wordmarkTracking: CGFloat = -1
        static let wordmarkLarge = resolve(bricolageBold, size: 28, relativeTo: .title, weight: .bold)
        static let wordmarkLargeTracking: CGFloat = -1.2
        static let headline = resolve("IBMPlexSans-SemiBold", size: 17, relativeTo: .headline, weight: .semibold)
        static let body = resolve("IBMPlexSans-Regular", size: 17, relativeTo: .body, weight: .regular)
        static let callout = resolve("IBMPlexSans-Regular", size: 15, relativeTo: .subheadline, weight: .regular)
        /// Small print, as the web's 13px: field errors, the form error banner, status notes and links
        /// ("Forgot password?").
        static let footnote = resolve("IBMPlexSans-Regular", size: 13, relativeTo: .footnote, weight: .regular)
        /// Form field labels ("Email"), in sentence case as on the web, and other small semibold text
        /// (the Show toggle, a game card's "Open game").
        static let fieldLabel = resolve("IBMPlexSans-SemiBold", size: 13, relativeTo: .footnote, weight: .semibold)
        /// Button labels, as the web's large buttons (15px).
        static let button = resolve("IBMPlexSans-SemiBold", size: 15, relativeTo: .subheadline, weight: .semibold)
        static let label = resolve("IBMPlexMono-Medium", size: 12, relativeTo: .caption, weight: .medium,
                                   design: .monospaced)
        static let labelTracking: CGFloat = 1.2
        /// The initials in the avatar ("AR"), mono as on the web; `initialsLarge` on the Account screen.
        static let initials = resolve("IBMPlexMono-Medium", size: 12, relativeTo: .caption, weight: .medium,
                                      design: .monospaced)
        static let initialsLarge = resolve("IBMPlexMono-Medium", size: 20, relativeTo: .title3, weight: .medium,
                                           design: .monospaced)
        static let initialsTracking: CGFloat = 0.5

        /// Bricolage Grotesque is one variable font; these are the PostScript names of its 700 and 800
        /// named instances (the web's `font-weight` values). The instances fix the optical size at
        /// 14pt, where the web's browser matches it to the text size, so large headings are set a
        /// little wider than on the web.
        private static let bricolageBold = "BricolageGrotesque-96ptExtraBold_Bold"
        private static let bricolageExtraBold = "BricolageGrotesque-96ptExtraBold_ExtraBold"

        /// Every face above, for the launch check below.
        private static let faces = [bricolageBold, bricolageExtraBold, "IBMPlexSans-Regular", "IBMPlexSans-SemiBold",
                                    "IBMPlexMono-Medium"]

        private static let registered: Void = {
            for url in Bundle.main.urls(forResourcesWithExtension: "woff2", subdirectory: nil) ?? [] {
                CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            }
            #if DEBUG
            // The font each face name opens, with its axes (weight, optical size), so one that falls
            // back to the system font shows in the log: subsystem Vantage, category Fonts.
            let log = Logger(subsystem: "Vantage", category: "Fonts")
            for name in faces {
                let font = UIFont(name: name, size: 17)
                // Variation axes by their four-letter tags ("opsz=14.0 wght=700.0"); none for static fonts.
                let variation = font.flatMap { CTFontCopyVariation($0 as CTFont) as? [Int: Double] } ?? [:]
                let axes = variation.map { tag, value in
                    let letters = (0..<4).map { UInt8(truncatingIfNeeded: tag >> (24 - 8 * $0)) }
                    return "\(String(decoding: letters, as: UTF8.self))=\(value)"
                }.sorted().joined(separator: " ")
                let opened = font.map { "\($0.fontName) (\($0.familyName)) \(axes)" } ?? "nothing"
                log.notice("\(name, privacy: .public) opens \(opened, privacy: .public)")
            }
            #endif
        }()

        /// Registers the bundled fonts (`Resources/Fonts`, the web app's WOFF2 files, which Core Text
        /// reads directly) for this process, once. Called at launch; the fonts above also call it, so
        /// previews, which skip the app's `init`, get them too.
        static func register() {
            registered
        }

        /// The bundled face when it's registered, otherwise the system font for the same text style,
        /// so a missing font file changes no screen code. Debug builds stop instead, so a face that
        /// doesn't load (a misspelt name, a file missing from the bundle) can't go unnoticed.
        private static func resolve(_ name: String, size: CGFloat, relativeTo style: Font.TextStyle,
                                    weight: Font.Weight, design: Font.Design = .default) -> Font {
            register()
            if UIFont(name: name, size: size) != nil { return .custom(name, size: size, relativeTo: style) }
            assertionFailure("The bundled font \(name) isn't registered")
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
        /// Buttons and text fields, as on the web (12px).
        static let control: CGFloat = 12
        /// The upload tile's icon square, as on the web at phone width (13px).
        static let tileIcon: CGFloat = 13
    }

    enum Size {
        /// Minimum height and width of anything tappable.
        static let minTouch: CGFloat = 44
        /// Minimum height of a text field, as on the web (48px).
        static let field: CGFloat = 48
        /// Minimum height of the primary button, as the web's `.button-large` (50px).
        static let primaryButton: CGFloat = 50
        static let hairline: CGFloat = 1
        static let progressBar: CGFloat = 6
        static let playButton: CGFloat = 56
        /// Player colour dots (toggle, legends).
        static let dot: CGFloat = 8
        static let landingDot: CGFloat = 10
        /// Outline of marks on the court diagram.
        static let markStroke: CGFloat = 2
        static let courtLine: CGFloat = 2
        /// A full court is tall; this keeps it to about half a phone screen.
        static let courtMaxWidth: CGFloat = 240
        /// The initials button in the Games header, and the Account screen's header, as on the web
        /// at phone width (44px and 64px).
        static let avatar: CGFloat = 44
        static let avatarLarge: CGFloat = 64
        /// The mark beside the wordmark (29/32 of its font size, as on the landing page).
        static let mark: CGFloat = 20
        static let markLarge: CGFloat = 25
        /// The upload tile's icon square, as on the web at phone width (44px).
        static let tileIcon: CGFloat = 44
        /// The cover at the top of a game card, as the web at phone width (188px).
        static let gameCover: CGFloat = 188
        /// Dash length of the empty-library outline.
        static let dash: CGFloat = 4
        /// The small court above the empty library's title.
        static let emptyCourt: CGFloat = 64
        /// Width of the ring around a focused text field, as the web's 3px outline.
        static let focusRing: CGFloat = 3
        /// The accent icons beside the brand panel's three lines.
        static let brandIcon: CGFloat = 20
        /// The court at the bottom of the brand panel.
        static let courtMotif: CGFloat = 120
    }
}

extension View {
    /// Mono caps for eyebrows and metadata ("VANTAGE", "5 GAMES", "PICKLEBALL · UPLOADED"); white
    /// (`Colors.headingOnDark`) over a game's cover.
    func monoLabel(_ color: Color = Theme.Colors.inkSecondary) -> some View {
        font(Theme.Fonts.label)
            .textCase(.uppercase)
            .tracking(Theme.Fonts.labelTracking)
            .foregroundStyle(color)
    }

    /// Keeps white text readable over a photo, as the web's `text-shadow: 0 1px 3px #000`.
    func shadowOverPhoto() -> some View {
        shadow(color: Theme.Colors.scrim, radius: 3, y: 1)
    }
}

private extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}
