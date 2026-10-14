import AVFoundation
import SwiftUI
import VantageKit

struct OverlayOptions: Equatable {
    var players = true
    var ball = true
    var trail = true
    var paddles = true
    /// Every raw ball candidate before tracking; useful for judging the detector.
    var rawBalls = false
    /// Off by default because crowded scenes become unreadable.
    var playerLabels = false
}

/// Draws one analyzed frame over an aspect-fit video. Boxes are in oriented source pixels,
/// the same space AVPlayerLayer displays.
struct DetectionOverlay: View {
    let frame: FrameDetections?
    let ball: BallSample?
    let trail: [DetectionTimeline.TrailPoint]
    let options: OverlayOptions

    static let playerColor = Color.green
    static let ballColor = Color.yellow
    static let estimatedColor = Color.orange
    static let paddleColor = Color.cyan
    static let rawColor = Color.white

    var body: some View {
        Canvas { context, size in
            guard let frame, frame.width > 0, frame.height > 0 else { return }
            let video = AVMakeRect(aspectRatio: CGSize(width: frame.width, height: frame.height),
                                   insideRect: CGRect(origin: .zero, size: size))
            let scale = video.width / frame.width
            func map(_ rect: CGRect) -> CGRect {
                CGRect(x: video.minX + rect.minX * scale, y: video.minY + rect.minY * scale,
                       width: rect.width * scale, height: rect.height * scale)
            }
            func map(_ point: CGPoint) -> CGPoint {
                CGPoint(x: video.minX + point.x * scale, y: video.minY + point.y * scale)
            }
            func circle(_ center: CGPoint, _ radius: CGFloat) -> Path {
                Path(ellipseIn: CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
            }
            func label(_ text: String, _ color: Color, above rect: CGRect) {
                context.draw(Text(text).font(.system(size: 9, weight: .semibold)).foregroundStyle(color),
                             at: CGPoint(x: rect.minX, y: rect.minY - 1), anchor: .bottomLeading)
            }

            for detection in frame.detections {
                let rect = map(detection.rect)
                switch detection.classID {
                case DetectionClass.player where options.players:
                    context.stroke(Path(rect), with: .color(Self.playerColor), lineWidth: 1.5)
                    if options.playerLabels {
                        label(String(format: "%.2f", detection.confidence), Self.playerColor, above: rect)
                    }
                case DetectionClass.paddle where options.paddles:
                    context.stroke(Path(rect), with: .color(Self.paddleColor), lineWidth: 1)
                case DetectionClass.ball where options.rawBalls:
                    let ring = circle(map(detection.center), 5)
                    context.stroke(ring, with: .color(Self.rawColor.opacity(0.8)), lineWidth: 1)
                    label(String(format: "%.2f", detection.confidence), Self.rawColor, above: ring.boundingRect)
                default:
                    break
                }
            }

            guard options.ball else { return }
            if options.trail, trail.count > 1 {
                // Segments fade with age; interpolated stretches are drawn dashed.
                for (a, b) in zip(trail, trail.dropFirst()) {
                    var segment = Path()
                    segment.move(to: map(a.center))
                    segment.addLine(to: map(b.center))
                    let estimated = a.source == .interpolated || b.source == .interpolated
                    context.stroke(segment,
                                   with: .color((estimated ? Self.estimatedColor : Self.ballColor).opacity(0.15 + 0.7 * b.recency)),
                                   style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: estimated ? [3, 3] : []))
                }
            }
            if let ball {
                // Balls are a few pixels wide; a minimum-size ring keeps them visible.
                let center = map(ball.center)
                switch ball.source {
                case .observed:
                    var radius: CGFloat = 8
                    if let box = frame.balls.first(where: { $0.center == ball.center })?.rect {
                        radius = max(radius, max(box.width, box.height) * scale / 2 + 4)
                    }
                    let ring = circle(center, radius)
                    context.stroke(ring, with: .color(Self.ballColor), lineWidth: 2)
                    label(String(format: "%.2f", ball.confidence ?? 0), Self.ballColor,
                          above: ring.boundingRect)
                case .interpolated:
                    let ring = circle(center, 8)
                    context.stroke(ring, with: .color(Self.estimatedColor),
                                   style: StrokeStyle(lineWidth: 2, dash: [3, 3]))
                    label("est.", Self.estimatedColor, above: ring.boundingRect)
                }
            }
        }
        .allowsHitTesting(false)
    }
}
