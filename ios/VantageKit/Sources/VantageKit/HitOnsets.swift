import Accelerate
import AVFoundation
import Foundation

/// Tuning for paddle-hit detection. Defaults equal the desktop pipeline's `config.py`
/// (section `audio`); the parity fixtures record the Python values so a drift fails `swift test`.
public struct HitOnsetConfig: Codable, Sendable, Equatable {
    /// Decoded mono rate; covers the pop's 1-6 kHz band.
    public var sampleRate = 16000.0
    /// A paddle pop rises within a few milliseconds.
    public var hopSeconds = 0.005
    /// Below this is wind, footsteps, and voices.
    public var bandLowHz = 1000.0
    public var bandHighHz = 6000.0
    /// Band-energy jump within one hop that counts as a hit.
    public var riseDecibels = 11.0
    /// Echoes and double peaks of one hit count once.
    public var minIntervalSeconds = 0.2

    public init() {}

    /// Samples per hop, rounded half to even like Python's round().
    public var hop: Int { max(1, Int((sampleRate * hopSeconds).rounded(.toNearestOrEven))) }
}

/// Paddle-hit onsets from mono audio: times where the 1-6 kHz band energy jumps by more than
/// `riseDecibels` within one short hop. Port of the desktop `pipeline/vantage/audio.py`
/// (`band_levels`, `hit_onsets`). It streams, so an hour-long match never sits in memory:
/// append samples as they decode, then read `onsets`.
public struct HitOnsetDetector: Sendable {
    public let config: HitOnsetConfig
    public let hop: Int
    /// rfft bins inside the band, chosen with numpy's `rfftfreq` arithmetic so the edges agree.
    public let bandBins: [Int]
    /// Band energy (dB) of each complete hop so far.
    public private(set) var levels: [Double] = []
    /// Real DFT of the band bins as a hop × (2 × bins) row-major matrix: cosines, then sines.
    private let basis: [Double]
    /// Samples of the next, still incomplete hop.
    private var pending: [Double] = []
    /// Hops per matrix multiply, bounding scratch memory however much is appended at once.
    private static let hopsPerBlock = 4096

    public init(config: HitOnsetConfig = .init()) {
        self.config = config
        let hop = config.hop
        self.hop = hop
        let spacing = 1.0 / (Double(hop) * (1.0 / config.sampleRate))
        let bins = (0...(hop / 2)).filter {
            let frequency = Double($0) * spacing
            return frequency >= config.bandLowHz && frequency <= config.bandHighHz
        }
        bandBins = bins
        var basis = [Double](repeating: 0, count: hop * 2 * bins.count)
        for n in 0..<hop {
            for (column, bin) in bins.enumerated() {
                let angle = 2 * Double.pi * Double(bin * n % hop) / Double(hop)
                basis[n * 2 * bins.count + column] = cos(angle)
                basis[n * 2 * bins.count + bins.count + column] = sin(angle)
            }
        }
        self.basis = basis
    }

    /// Adds the next mono samples in [-1, 1]. A trailing partial hop waits for more samples
    /// (and is dropped at the end, as on the desktop).
    public mutating func append(_ samples: [Float]) {
        pending.append(contentsOf: samples.lazy.map(Double.init))
        let complete = pending.count / hop
        guard complete > 0 else { return }
        levels.append(contentsOf: pendingLevels(hops: complete))
        pending.removeFirst(complete * hop)
    }

    /// Band energy (dB) of the first `hops` complete hops waiting in `pending`.
    private func pendingLevels(hops: Int) -> [Double] {
        let columns = 2 * bandBins.count
        // A band above Nyquist has no energy, like numpy's sum over an empty selection.
        guard columns > 0 else { return Array(repeating: 10 * log10(1e-10), count: hops) }
        var levels: [Double] = []
        levels.reserveCapacity(hops)
        var products = [Double](repeating: 0, count: min(hops, Self.hopsPerBlock) * columns)
        pending.withUnsafeBufferPointer { frames in
            products.withUnsafeMutableBufferPointer { out in
                for first in stride(from: 0, to: hops, by: Self.hopsPerBlock) {
                    let rows = min(Self.hopsPerBlock, hops - first)
                    // |rfft|² summed over the band = squared norm of each row of frames × basis.
                    vDSP_mmulD(frames.baseAddress! + first * hop, 1, basis, 1, out.baseAddress!, 1,
                               vDSP_Length(rows), vDSP_Length(columns), vDSP_Length(hop))
                    for row in 0..<rows {
                        var power = 0.0
                        vDSP_svesqD(out.baseAddress! + row * columns, 1, &power, vDSP_Length(columns))
                        levels.append(10 * log10(power + 1e-10))
                    }
                }
            }
        }
        return levels
    }

    /// Onset times in seconds from the first appended sample.
    public var onsets: [Double] { Self.onsets(levels: levels, hop: hop, config: config) }

    /// Onsets for a whole recording sampled at `config.sampleRate`.
    public static func onsets(samples: [Float], config: HitOnsetConfig = .init()) -> [Double] {
        var detector = HitOnsetDetector(config: config)
        detector.append(samples)
        return detector.onsets
    }

    /// Peaks of the hop-to-hop level rise above `riseDecibels`, kept at least
    /// `minIntervalSeconds` after the previous kept onset.
    static func onsets(levels: [Double], hop: Int, config: HitOnsetConfig) -> [Double] {
        guard levels.count >= 2 else { return [] }
        // np.diff(level, prepend=level[0]): the first hop never rises.
        let rise: [Double] = [0] + zip(levels.dropFirst(), levels).map { $0 - $1 }
        var onsets: [Double] = []
        for index in rise.indices where rise[index] > config.riseDecibels {
            // Peak of each rise, so one pop spread over two hops counts once.
            if index + 1 < rise.count, rise[index] < rise[index + 1] { continue }
            let time = Double(index * hop) / config.sampleRate
            if let last = onsets.last, time - last < config.minIntervalSeconds { continue }
            onsets.append(time)
        }
        return onsets
    }
}

/// Paddle-hit onsets found in a video's audio track, saved as `hits.json` in a run folder.
/// Desktop `stats.json` calls the same list `audio_hit_onsets_s`.
public struct AudioHits: Codable, Sendable, Equatable {
    public static let fileName = "hits.json"

    public let config: HitOnsetConfig
    /// Presentation time of the first decoded audio sample. Onsets include it, so they share
    /// the timeline of `FrameDetections.timeSeconds` and AVPlayer.
    public let startSeconds: Double
    /// Length of the decoded audio.
    public let durationSeconds: Double
    /// Hit times in seconds on the asset timeline, ascending.
    public let onsets: [Double]

    public init(config: HitOnsetConfig, startSeconds: Double, durationSeconds: Double, onsets: [Double]) {
        self.config = config
        self.startSeconds = startSeconds
        self.durationSeconds = durationSeconds
        self.onsets = onsets
    }

    /// The latest onset at or before `time`, if it is less than `window` seconds earlier.
    public func onset(before time: Double, within window: Double) -> Double? {
        var low = 0, high = onsets.count  // first onset after `time`
        while low < high {
            let mid = (low + high) / 2
            if onsets[mid] <= time { low = mid + 1 } else { high = mid }
        }
        guard low > 0, time - onsets[low - 1] < window else { return nil }
        return onsets[low - 1]
    }

    public static func detect(in video: URL, config: HitOnsetConfig = .init()) async throws -> AudioHits? {
        try await detect(in: AVURLAsset(url: video), config: config)
    }

    /// Decodes the audio as 16-bit mono PCM at `config.sampleRate`, as the desktop pipeline's
    /// FFmpeg call does, and finds hit onsets while streaming. Tracks are tried in order until
    /// one decodes. Nil when the asset has no audio track or no audio samples, which the
    /// desktop also treats as "no audio" (rallies then fall back to ball evidence).
    public static func detect(in asset: AVAsset, config: HitOnsetConfig = .init()) async throws -> AudioHits? {
        var failure: Error?
        for track in try await asset.loadTracks(withMediaType: .audio) {
            do {
                if let hits = try await decode(track, of: asset, config: config) { return hits }
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                failure = failure ?? error
            }
        }
        if let failure { throw failure }
        return nil
    }

    private static func decode(_ track: AVAssetTrack, of asset: AVAsset,
                               config: HitOnsetConfig) async throws -> AudioHits? {
        let reader = try AVAssetReader(asset: asset)
        // Audio that starts after the video sits behind an empty edit, which the reader fills
        // with digital silence; the rise out of it would read as a hit. FFmpeg skips it, so
        // read from the first real segment (onsets stay on the asset timeline).
        if let first = try await track.load(.segments).first(where: { !$0.isEmpty }),
           first.timeMapping.target.start > .zero {
            reader.timeRange = CMTimeRange(start: first.timeMapping.target.start, duration: .positiveInfinity)
        }
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: config.sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw AnalysisError.message("Unsupported audio format.") }
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? AnalysisError.message("Cannot decode audio.") }
        defer { reader.cancelReading() }
        var detector = HitOnsetDetector(config: config)
        var start: Double?
        var sampleCount = 0
        while let buffer = output.copyNextSampleBuffer() {
            try Task.checkCancellation()
            guard let block = CMSampleBufferGetDataBuffer(buffer) else { continue }
            let count = CMBlockBufferGetDataLength(block) / MemoryLayout<Int16>.size
            guard count > 0 else { continue }
            if start == nil {
                let time = CMSampleBufferGetPresentationTimeStamp(buffer).seconds
                start = time.isFinite ? time : 0
            }
            var pcm = [Int16](repeating: 0, count: count)
            let status = pcm.withUnsafeMutableBytes {
                CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: $0.count, destination: $0.baseAddress!)
            }
            guard status == kCMBlockBufferNoErr else { throw AnalysisError.message("Cannot read decoded audio.") }
            detector.append(pcm.map { Float($0) / 32768 })
            sampleCount += count
        }
        guard reader.status == .completed else { throw reader.error ?? AnalysisError.message("Audio decoding stopped.") }
        guard sampleCount > 0, let start else { return nil }
        return AudioHits(config: config, startSeconds: start, durationSeconds: Double(sampleCount) / config.sampleRate,
                         onsets: detector.onsets.map { start + $0 })
    }
}
