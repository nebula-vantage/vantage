import SwiftUI

/// The Vantage mark from the landing page (`site/index.html`, `icon-logo`): an orange V crossed by
/// a slash in the background colour. Square; size it with a frame.
struct VantageMark: View {
    /// The colour behind the mark, which the slash cuts through.
    var background = Theme.Colors.background

    var body: some View {
        ZStack {
            VantageMarkShape().fill(Theme.Colors.accent)
            VantageMarkSlash().fill(background)
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

/// The V of the mark: `M2 5h10l7.2 17.5L26.3 5H36L23 34h-8L2 5Z` in a 36×36 viewBox.
struct VantageMarkShape: Shape {
    func path(in rect: CGRect) -> Path {
        let point = ViewBox(rect, width: 36, height: 36).point
        var path = Path()
        path.move(to: point(2, 5))
        for (x, y) in [(12, 5), (19.2, 22.5), (26.3, 5), (36, 5), (23, 34), (15, 34)] as [(CGFloat, CGFloat)] {
            path.addLine(to: point(x, y))
        }
        path.closeSubpath()
        return path
    }
}

/// The slash across the mark: the line `m1 18 32-9` stroked 3 units wide, as an outline so it can
/// be filled at any size.
struct VantageMarkSlash: Shape {
    func path(in rect: CGRect) -> Path {
        let box = ViewBox(rect, width: 36, height: 36)
        var line = Path()
        line.move(to: box.point(1, 18))
        line.addLine(to: box.point(33, 9))
        return line.strokedPath(StrokeStyle(lineWidth: 3 * box.scale))
    }
}

/// Maps an SVG viewBox onto the largest rect of its shape inside `rect`, centred horizontally and
/// either centred vertically or on the bottom edge (`xMidYMid` / `xMidYMax meet`).
private struct ViewBox {
    let scale: CGFloat
    let origin: CGPoint

    init(_ rect: CGRect, width: CGFloat, height: CGFloat, alignBottom: Bool = false) {
        scale = min(rect.width / width, rect.height / height)
        origin = CGPoint(x: rect.midX - width * scale / 2,
                         y: alignBottom ? rect.maxY - height * scale : rect.midY - height * scale / 2)
    }

    func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
        CGPoint(x: origin.x + x * scale, y: origin.y + y * scale)
    }
}

/// The mark and "vantage." in Bricolage Grotesque Bold with an orange period, as on the landing
/// page. `large` on the sign-in screens, regular in the Games header.
struct Wordmark: View {
    var large = false
    /// White letters, with the mark cut in the panel colour, for the sign-in screens' brand panel.
    var onDark = false

    /// Scales the mark and letter spacing with the text.
    @ScaledMetric(relativeTo: .title) private var scale: CGFloat = 1

    var body: some View {
        HStack(spacing: Theme.Spacing.s * scale) {
            VantageMark(background: onDark ? Theme.Colors.videoBackground : Theme.Colors.background)
                .frame(width: (large ? Theme.Size.markLarge : Theme.Size.mark) * scale)
            (Text("vantage") + Text(".").foregroundStyle(Theme.Colors.accent))
                .font(large ? Theme.Fonts.wordmarkLarge : Theme.Fonts.wordmark)
                .tracking((large ? Theme.Fonts.wordmarkLargeTracking : Theme.Fonts.wordmarkTracking) * scale)
                .foregroundStyle(onDark ? Theme.Colors.headingOnDark : Theme.Colors.ink)
                .lineLimit(1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Vantage")
    }
}

/// The perspective court at the bottom of the sign-in screens' brand panel, from the web's
/// `auth-court` SVG (680×340 viewBox), drawn as large as fits on the bottom edge of its frame.
struct CourtMotif: View {
    var body: some View {
        ZStack {
            CourtMotifShape(part: .surface).fill(Theme.Colors.courtMotifFill)
            CourtMotifShape(part: .lines).fill(Theme.Colors.courtMotifLine)
            CourtMotifShape(part: .net).fill(Theme.Colors.courtMotifNet)
            CourtMotifShape(part: .ball).fill(Theme.Colors.accent)
        }
        .accessibilityHidden(true)
    }
}

/// One layer of `CourtMotif`. Lines come back as outlines at their SVG stroke width, scaled with
/// the court, so every layer is filled.
private struct CourtMotifShape: Shape {
    enum Part { case surface, lines, net, ball }
    let part: Part

    func path(in rect: CGRect) -> Path {
        let box = ViewBox(rect, width: 680, height: 340, alignBottom: true)
        var path = Path()
        func line(_ x1: CGFloat, _ y1: CGFloat, _ x2: CGFloat, _ y2: CGFloat) {
            path.move(to: box.point(x1, y1))
            path.addLine(to: box.point(x2, y2))
        }
        switch part {
        case .surface, .lines:
            // M75 330 232 56h216l157 274Z
            path.addLines([box.point(75, 330), box.point(232, 56), box.point(448, 56), box.point(605, 330)])
            path.closeSubpath()
            guard part == .lines else { return path }
            // M166 171h348M145 210h390M186 136h308M340 56v80M340 210v120
            line(166, 171, 514, 171)
            line(145, 210, 535, 210)
            line(186, 136, 494, 136)
            line(340, 56, 340, 136)
            line(340, 210, 340, 330)
            return path.strokedPath(StrokeStyle(lineWidth: 1.5 * box.scale))
        case .net:
            // M159 171h362
            line(159, 171, 521, 171)
            return path.strokedPath(StrokeStyle(lineWidth: 2 * box.scale))
        case .ball:
            // The circle at (452, 118), radius 7.
            let diameter = 14 * box.scale
            return Path(ellipseIn: CGRect(origin: box.point(445, 111), size: CGSize(width: diameter, height: diameter)))
        }
    }
}

#Preview {
    VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
        Wordmark()
        Wordmark(large: true)
        VStack(alignment: .leading, spacing: Theme.Spacing.l) {
            Wordmark(large: true, onDark: true)
            CourtMotif().frame(height: Theme.Size.courtMotif)
        }
        .padding(Theme.Spacing.l)
        .background(Theme.Colors.videoBackground)
        HStack(spacing: Theme.Spacing.l) {
            VantageMark().frame(width: 36)
            VantageMark().frame(width: 120)
            VantageMark(background: Theme.Colors.surface).frame(width: 120).background(Theme.Colors.surface)
        }
        Wordmark().dynamicTypeSize(.accessibility3)
    }
    .padding(Theme.Spacing.l)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .background(Theme.Colors.background)
}
