import AVFoundation
import SwiftUI
import UIKit
import VantageKit

/// Plays a run's copied video with its detections drawn on top.
struct PlayerView: View {
    let run: AnalysisRun
    let videoURL: URL
    let detectionsURL: URL

    @State private var controller: PlaybackController
    @State private var timeline: DetectionTimeline?
    @State private var loadError: String?
    @State private var options = OverlayOptions()
    @State private var scrubTime: Double?

    init(run: AnalysisRun, videoURL: URL, detectionsURL: URL) {
        self.run = run
        self.videoURL = videoURL
        self.detectionsURL = detectionsURL
        _controller = State(initialValue: PlaybackController(url: videoURL))
    }

    var body: some View {
        VStack(spacing: 12) {
            video
            controls
            legend
            Spacer(minLength: 0)
        }
        .padding(.vertical)
        .navigationTitle(run.sourceName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbar }
        .task {
            await loadTimeline()
            #if DEBUG
            // UI check hook: `simctl launch ... -openLatestRun -seek 7.5`.
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-seek"), flag + 1 < arguments.count,
               let seconds = Double(arguments[flag + 1]) {
                controller.seek(to: seconds)
            }
            #endif
        }
        .onDisappear { controller.tearDown() }
    }

    // MARK: Video + overlay

    private var video: some View {
        ZStack(alignment: .topLeading) {
            PlayerLayerView(player: controller.player)
            // Redraw every display frame from the player's actual time.
            TimelineView(.animation) { _ in
                let index = timeline?.frameIndex(at: controller.player.currentTime().seconds)
                let frame = index.flatMap { timeline?.frames[$0] }
                ZStack(alignment: .topLeading) {
                    DetectionOverlay(frame: frame,
                                     ball: index.flatMap { timeline?.ballSamples[$0] },
                                     trail: index.map { timeline?.ballTrail(endingAt: $0, window: 0.5) ?? [] } ?? [],
                                     options: options)
                    hud(frame: frame, index: index)
                }
            }
        }
        .aspectRatio(run.width > 0 && run.height > 0 ? run.width / run.height : 16 / 9, contentMode: .fit)
        .background(.black)
        .onTapGesture { controller.togglePlay() }
    }

    @ViewBuilder
    private func hud(frame: FrameDetections?, index: Int?) -> some View {
        if let loadError {
            Text(loadError).font(.caption).padding(6).background(.red.opacity(0.8))
        } else if timeline == nil {
            ProgressView().padding(8)
        } else if let frame, let index {
            let players = frame.detections.filter { $0.classID == DetectionClass.player }.count
            Text("frame \(index + 1)  ·  \(Int(frame.inferenceMilliseconds)) ms  ·  \(players) players  ·  "
                 + ballStatus(frame: frame, sample: timeline?.ballSamples[index]))
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.white)
                .padding(.horizontal, 6).padding(.vertical, 3)
                .background(.black.opacity(0.55), in: .rect(cornerRadius: 4))
                .padding(6)
        }
    }

    // MARK: Controls

    private var controls: some View {
        VStack(spacing: 8) {
            Slider(value: Binding(
                get: { scrubTime ?? controller.currentTime },
                set: { value in
                    scrubTime = value
                    controller.seek(to: value, precise: false)
                }), in: 0...max(controller.duration, 0.01)) { editing in
                if !editing, let scrubTime {
                    controller.seek(to: scrubTime, precise: true)
                    self.scrubTime = nil
                }
            }
            HStack {
                Text(format(scrubTime ?? controller.currentTime)).monospacedDigit()
                Spacer()
                Button { controller.step(-1) } label: { Image(systemName: "backward.frame.fill") }
                    .accessibilityLabel("Previous frame")
                Button { controller.togglePlay() } label: {
                    Image(systemName: controller.isPlaying ? "pause.fill" : "play.fill").font(.title2)
                        .frame(width: 44)
                }
                Button { controller.step(1) } label: { Image(systemName: "forward.frame.fill") }
                    .accessibilityLabel("Next frame")
                Spacer()
                Menu {
                    ForEach(PlaybackController.rates, id: \.self) { rate in
                        Button { controller.setRate(rate) } label: {
                            if rate == controller.rate { Label(rateLabel(rate), systemImage: "checkmark") }
                            else { Text(rateLabel(rate)) }
                        }
                    }
                } label: { Text(rateLabel(controller.rate)).monospacedDigit().frame(minWidth: 44) }
            }
            .font(.callout)
        }
        .padding(.horizontal)
    }

    private var legend: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 14) {
                legendItem("Players", DetectionOverlay.playerColor)
                legendItem("Ball", DetectionOverlay.ballColor)
                legendItem("Gap-filled", DetectionOverlay.estimatedColor)
                legendItem("Paddles", DetectionOverlay.paddleColor)
            }
            if let timeline {
                Text("Ball tracked in \(timeline.trackedFrameCount) of \(timeline.frames.count) frames · "
                     + "\(timeline.trackCount) track\(timeline.trackCount == 1 ? "" : "s")")
                    .monospacedDigit()
            }
            Text("The ball is tracked from raw detections with the desktop motion tracker (#ID = track). "
                 + "Orange dashed positions are interpolated across short gaps, not detections. "
                 + "A new ID means the track was lost; static clutter can still be followed briefly.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .font(.caption)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal)
    }

    private func legendItem(_ title: String, _ color: Color) -> some View {
        HStack(spacing: 4) { Circle().fill(color).frame(width: 8, height: 8); Text(title) }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .topBarTrailing) {
            Menu {
                Toggle("Players", isOn: $options.players)
                Toggle("Tracked ball", isOn: $options.ball)
                Toggle("Ball trail", isOn: $options.trail)
                Toggle("Raw ball candidates", isOn: $options.rawBalls)
                Toggle("Paddles", isOn: $options.paddles)
                Toggle("Player confidence", isOn: $options.playerLabels)
            } label: { Image(systemName: "square.on.square.dashed") }
                .accessibilityLabel("Overlay options")
            ShareLink(item: detectionsURL) { Image(systemName: "square.and.arrow.up") }
                .accessibilityLabel("Export detections")
        }
    }

    // MARK: Helpers

    private func loadTimeline() async {
        guard timeline == nil else { return }
        let url = detectionsURL
        do {
            timeline = try await Task.detached(priority: .userInitiated) {
                try DetectionTimeline(contentsOf: url)
            }.value
        } catch {
            loadError = "Could not load detections: \(error.localizedDescription)"
        }
    }

    private func ballStatus(frame: FrameDetections, sample: BallSample?) -> String {
        switch sample?.source {
        case .observed: return String(format: "ball #%d %.2f", sample!.trackID, sample!.confidence ?? 0)
        case .interpolated: return "ball #\(sample!.trackID) est."
        case nil:
            let raw = frame.balls.count
            return raw == 0 ? "no ball" : "no ball (\(raw) raw)"
        }
    }

    private func format(_ seconds: Double) -> String {
        guard seconds.isFinite else { return "0:00.0" }
        return String(format: "%d:%04.1f", Int(seconds) / 60, seconds.truncatingRemainder(dividingBy: 60))
    }

    private func rateLabel(_ rate: Float) -> String { rate == 1 ? "1×" : String(format: "%g×", rate) }
}

/// AVPlayerLayer host; aspect-fit to match DetectionOverlay's mapping.
struct PlayerLayerView: UIViewRepresentable {
    let player: AVPlayer

    final class LayerView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }

    func makeUIView(context: Context) -> LayerView {
        let view = LayerView()
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        view.backgroundColor = .black
        return view
    }

    func updateUIView(_ view: LayerView, context: Context) {
        if view.playerLayer.player !== player { view.playerLayer.player = player }
    }
}
