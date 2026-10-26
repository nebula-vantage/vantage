import SwiftUI
import VantageKit

/// The game's video with the detection overlays, in a rounded card: tap to play or pause,
/// with the length and the ball-tracked trust signal as badges.
struct GameVideoCard: View {
    let run: AnalysisRun
    let detectionsURL: URL
    let trackedFraction: Double?

    @State private var controller: PlaybackController
    @State private var timeline: DetectionTimeline?

    init(run: AnalysisRun, videoURL: URL, detectionsURL: URL, trackedFraction: Double?) {
        self.run = run
        self.detectionsURL = detectionsURL
        self.trackedFraction = trackedFraction
        _controller = State(initialValue: PlaybackController(url: videoURL))
    }

    private var trackedText: String { "\(Format.percent(trackedFraction)) of frames tracked" }

    var body: some View {
        OverlayVideo(player: controller.player, timeline: timeline, options: OverlayOptions(),
                     aspectRatio: run.videoAspectRatio)
            .overlay {
                if !controller.isPlaying {
                    Image(systemName: "play.fill")
                        .font(Theme.Fonts.title)
                        .foregroundStyle(Theme.Colors.ink)
                        .frame(width: Theme.Size.playButton, height: Theme.Size.playButton)
                        .background(Theme.Colors.surface, in: .circle)
                }
            }
            .overlay(alignment: .bottom) {
                HStack {
                    badge(Format.duration(run.durationSeconds), color: Theme.Colors.surface)
                    Spacer(minLength: Theme.Spacing.s)
                    badge(trackedText, color: Theme.Colors.positiveOnDark)
                }
                .padding(Theme.Spacing.m)
            }
            // Chrome drawn over the video stops growing before it covers the picture; VoiceOver
            // still reads the full text.
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
            .background(Theme.Colors.videoBackground)
            .clipShape(.rect(cornerRadius: Theme.Radius.card, style: .continuous))
            .contentShape(.rect)
            .onTapGesture { controller.togglePlay() }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(controller.isPlaying ? "Pause video" : "Play video")
            .accessibilityValue("\(Format.duration(run.durationSeconds)), \(trackedText)")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { controller.togglePlay() }
            .task { await loadTimeline() }
            // Pause only: the screen comes back after debug playback, so the controller must stay live.
            .onDisappear { controller.player.pause() }
    }

    private func badge(_ text: String, color: Color) -> some View {
        Text(text)
            .font(Theme.Fonts.label)
            .monospacedDigit()
            .foregroundStyle(color)
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .padding(.horizontal, Theme.Spacing.s)
            .padding(.vertical, Theme.Spacing.xs)
            .background(Theme.Colors.scrim, in: .rect(cornerRadius: Theme.Radius.badge))
    }

    private func loadTimeline() async {
        guard timeline == nil else { return }
        let url = detectionsURL
        // Without detections the video still plays, just without overlays.
        timeline = try? await Task.detached(priority: .userInitiated) {
            try DetectionTimeline(contentsOf: url)
        }.value
    }
}
