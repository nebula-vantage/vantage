import AVFoundation
import Observation

/// Owns the AVPlayer for one run and exposes coarse state for controls.
/// The overlay reads `player.currentTime()` directly every display frame so boxes stay
/// in sync during playback, scrubbing, and frame stepping.
@MainActor @Observable
final class PlaybackController {
    static let rates: [Float] = [0.25, 0.5, 1]

    let player: AVPlayer
    private(set) var currentTime: Double = 0
    private(set) var duration: Double = 0
    private(set) var isPlaying = false
    private(set) var rate: Float = 1

    @ObservationIgnored private var timeObserver: Any?
    @ObservationIgnored private var statusObservation: NSKeyValueObservation?

    init(url: URL) {
        player = AVPlayer(url: url)
        player.actionAtItemEnd = .pause
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 1, timescale: 20), queue: .main) { [weak self] time in
            MainActor.assumeIsolated { self?.currentTime = time.seconds }
        }
        statusObservation = player.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] player, _ in
            let playing = player.timeControlStatus != .paused
            Task { @MainActor in self?.isPlaying = playing }
        }
        Task { [weak self] in
            guard let asset = self?.player.currentItem?.asset,
                  let duration = try? await asset.load(.duration).seconds, duration.isFinite else { return }
            self?.duration = duration
        }
    }

    func togglePlay() {
        if isPlaying {
            player.pause()
        } else {
            if duration > 0, currentTime >= duration - 0.05 { seek(to: 0) }
            player.playImmediately(atRate: rate)
        }
    }

    /// Precise seeks land on the exact frame; imprecise ones keep scrubbing responsive.
    func seek(to seconds: Double, precise: Bool = true) {
        // Duration is 0 until the asset loads; don't clamp against an unknown length.
        let upper = duration > 0 ? duration : seconds
        let time = CMTime(seconds: max(0, min(seconds, upper)), preferredTimescale: 600)
        let tolerance = precise ? CMTime.zero : CMTime(seconds: 0.1, preferredTimescale: 600)
        player.seek(to: time, toleranceBefore: tolerance, toleranceAfter: tolerance)
        currentTime = time.seconds
    }

    func step(_ frames: Int) {
        player.pause()
        player.currentItem?.step(byCount: frames)
    }

    func setRate(_ newRate: Float) {
        rate = newRate
        if isPlaying { player.rate = newRate }
    }

    func tearDown() {
        player.pause()
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        statusObservation = nil
    }
}
