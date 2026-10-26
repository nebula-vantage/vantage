import SwiftUI
import VantageKit

/// A top-down court drawn from its dimensions, near baseline at the bottom, with room around the
/// lines for marks that land out. `overlay` gets a `CourtGeometry` to place marks by court position
/// (landing dots now, the heat map later).
struct CourtDiagram<Overlay: View>: View {
    let court: CourtDimensions
    @ViewBuilder var overlay: (CourtGeometry) -> Overlay

    var body: some View {
        GeometryReader { proxy in
            let geometry = CourtGeometry(court: court, size: proxy.size)
            ZStack(alignment: .topLeading) {
                Canvas { context, _ in Self.drawLines(geometry, in: &context) }
                overlay(geometry)
            }
            .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
        }
        .aspectRatio(CourtGeometry.aspectRatio(of: court), contentMode: .fit)
        .background(Theme.Colors.courtSurround)
        .clipShape(.rect(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private static func drawLines(_ geometry: CourtGeometry, in context: inout GraphicsContext) {
        let court = geometry.court
        let line = Theme.Colors.courtLine
        let width = Theme.Size.courtLine
        context.fill(Path(geometry.courtRect), with: .color(Theme.Colors.courtSurface))
        context.stroke(Path(geometry.courtRect), with: .color(line), lineWidth: width)

        func segment(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, lineWidth: CGFloat) {
            var path = Path()
            path.move(to: geometry.point(x: x1, y: y1))
            path.addLine(to: geometry.point(x: x2, y: y2))
            context.stroke(path, with: .color(line), lineWidth: lineWidth)
        }
        let net = court.netPositionM
        let nearKitchen = net - court.kitchenDepthM
        let farKitchen = net + court.kitchenDepthM
        let centre = court.widthM / 2
        segment(0, nearKitchen, court.widthM, nearKitchen, lineWidth: width)
        segment(0, farKitchen, court.widthM, farKitchen, lineWidth: width)
        segment(centre, 0, centre, nearKitchen, lineWidth: width)
        segment(centre, farKitchen, centre, court.lengthM, lineWidth: width)
        // The net runs past the sidelines to the posts.
        let post = CourtGeometry.marginM / 3
        segment(-post, net, court.widthM + post, net, lineWidth: width * 2)
    }
}

extension CourtDiagram where Overlay == EmptyView {
    init(court: CourtDimensions) {
        self.init(court: court) { _ in EmptyView() }
    }
}

/// Maps court positions in metres (origin near-left corner, y toward the far baseline) to points
/// in a `CourtDiagram`.
struct CourtGeometry {
    /// Room drawn around the lines, so marks that land out stay visible.
    static let marginM = 1.5

    let court: CourtDimensions
    let size: CGSize

    static func aspectRatio(of court: CourtDimensions) -> CGFloat {
        CGFloat((court.widthM + 2 * marginM) / (court.lengthM + 2 * marginM))
    }

    private var scale: CGFloat { size.width / CGFloat(court.widthM + 2 * Self.marginM) }

    func point(_ position: CourtPoint) -> CGPoint { point(x: position.x, y: position.y) }

    func point(x: Double, y: Double) -> CGPoint {
        CGPoint(x: CGFloat(Self.marginM + x) * scale,
                y: CGFloat(Self.marginM + court.lengthM - y) * scale)
    }

    var courtRect: CGRect {
        let farLeft = point(x: 0, y: court.lengthM)
        let nearRight = point(x: court.widthM, y: 0)
        return CGRect(x: farLeft.x, y: farLeft.y, width: nearRight.x - farLeft.x, height: nearRight.y - farLeft.y)
    }
}

#Preview {
    ScrollView {
        HStack(alignment: .top, spacing: Theme.Spacing.m) {
            CourtDiagram(court: .pickleball)
            CourtDiagram(court: .pickleball) { geometry in
                ForEach(Array(GameStats.sample.bounces.enumerated()), id: \.offset) { _, bounce in
                    Circle()
                        .fill(bounce.call == .inBounds ? Theme.Colors.accent : Theme.Colors.surface)
                        .stroke(Theme.Colors.accent, lineWidth: Theme.Size.hairline)
                        .frame(width: Theme.Size.landingDot, height: Theme.Size.landingDot)
                        .position(geometry.point(bounce.court))
                }
            }
        }
        .padding(Theme.Spacing.l)
    }
    .background(Theme.Colors.background)
}
