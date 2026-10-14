import AVFoundation
import SwiftUI

struct OverlayOptions: Equatable {
    var players = true
    var ball = true
    var paddles = true
    var trail = true
    /// Player confidence labels; off by default because crowded scenes become unreadable.
    /// Ball confidence is always shown: it is the main cue for spotting false positives.
    var playerLabels = false
}

/// Draws one analyzed frame's raw detections over an aspect-fit video.
/// Detection boxes are in oriented source pixels, the same space AVPlayerLayer displays.
struct DetectionOverlay: View {
    let frame: FrameDetections?
    let trail: [DetectionTimeline.TrailPoint]
    let options: OverlayOptions

    static let playerColor = Color.green
    static let ballColor = Color.yellow
    static let paddleColor = Color.cyan

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
            func label(_ text: String, _ color: Color, at rect: CGRect) {
                context.draw(Text(text).font(.system(size: 9, weight: .semibold)).foregroundStyle(color),
                             at: CGPoint(x: rect.minX, y: rect.minY - 1), anchor: .bottomLeading)
            }

            if options.trail {
                // The current frame's ball is drawn as a ring below; trail shows earlier frames.
                for point in trail where point.recency < 0.999 {
                    let center = map(point.center)
                    let radius = 2 + 2 * point.recency
                    context.fill(Path(ellipseIn: CGRect(x: center.x - radius, y: center.y - radius,
                                                        width: radius * 2, height: radius * 2)),
                                 with: .color(Self.ballColor.opacity(0.2 + 0.6 * point.recency)))
                }
            }
            for detection in frame.detections {
                let rect = map(detection.rect)
                switch detection.classID {
                case DetectionClass.player where options.players:
                    context.stroke(Path(rect), with: .color(Self.playerColor), lineWidth: 1.5)
                    if options.playerLabels {
                        label(String(format: "%.2f", detection.confidence), Self.playerColor, at: rect)
                    }
                case DetectionClass.paddle where options.paddles:
                    context.stroke(Path(rect), with: .color(Self.paddleColor), lineWidth: 1)
                case DetectionClass.ball where options.ball:
                    // Balls are a few pixels wide; a minimum-size ring keeps them visible.
                    let center = map(detection.center)
                    let radius = max(8, max(rect.width, rect.height) / 2 + 4)
                    let ring = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
                    context.stroke(Path(ellipseIn: ring), with: .color(Self.ballColor), lineWidth: 2)
                    label(String(format: "%.2f", detection.confidence), Self.ballColor, at: ring)
                default:
                    break
                }
            }
        }
        .allowsHitTesting(false)
    }
}
