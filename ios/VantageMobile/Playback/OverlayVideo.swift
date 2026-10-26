import AVFoundation
import SwiftUI
import VantageKit

/// A run's video with its detections drawn on top, redrawn every display frame from the player's
/// actual time. `hud` gets the current frame and its index (nil before the timeline loads).
struct OverlayVideo<HUD: View>: View {
    let player: AVPlayer
    let timeline: DetectionTimeline?
    let options: OverlayOptions
    let aspectRatio: CGFloat
    @ViewBuilder var hud: (FrameDetections?, Int?) -> HUD

    var body: some View {
        ZStack(alignment: .topLeading) {
            PlayerLayerView(player: player)
            TimelineView(.animation) { _ in
                let index = timeline?.frameIndex(at: player.currentTime().seconds)
                let frame = index.flatMap { timeline?.frames[$0] }
                ZStack(alignment: .topLeading) {
                    DetectionOverlay(frame: frame,
                                     ball: index.flatMap { timeline?.ballSamples[$0] },
                                     trail: index.map { timeline?.ballTrail(endingAt: $0, window: 0.5) ?? [] } ?? [],
                                     options: options)
                    hud(frame, index)
                }
            }
        }
        .aspectRatio(aspectRatio, contentMode: .fit)
    }
}

extension OverlayVideo where HUD == EmptyView {
    init(player: AVPlayer, timeline: DetectionTimeline?, options: OverlayOptions, aspectRatio: CGFloat) {
        self.init(player: player, timeline: timeline, options: options, aspectRatio: aspectRatio) { _, _ in
            EmptyView()
        }
    }
}

extension AnalysisRun {
    /// Width over height of the analyzed video, 16:9 if unknown.
    var videoAspectRatio: CGFloat { width > 0 && height > 0 ? width / height : 16 / 9 }
}
