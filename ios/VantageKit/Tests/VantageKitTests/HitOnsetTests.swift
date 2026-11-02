import AVFoundation
import Foundation
import XCTest
@testable import VantageKit

/// Replays 16-bit audio through the Swift detector and requires the band levels and onsets the
/// desktop `pipeline/vantage/audio.py` produced from the same samples.
/// Regenerate fixtures with tools/coreml/make_hit_fixtures.py.
final class HitOnsetParityTests: XCTestCase {
    struct Fixture: Decodable {
        let name: String
        /// Rate of the samples, passed to the desktop `hit_onsets(samples, rate, config)`.
        let rate: Double
        let config: HitOnsetConfig
        let hop: Int
        let onsets: [Double]
        /// Python's float32 levels, rounded to 4 decimals.
        let levels: [Double]
        let pcm_s16le_base64: String

        var samples: [Float] {
            let data = Data(base64Encoded: pcm_s16le_base64) ?? Data()
            return data.withUnsafeBytes { raw in
                (0..<raw.count / 2).map {
                    Float(Int16(littleEndian: raw.loadUnaligned(fromByteOffset: 2 * $0, as: Int16.self))) / 32768
                }
            }
        }

        /// The desktop settings at this fixture's sample rate.
        var detectorConfig: HitOnsetConfig {
            var config = config
            config.sampleRate = rate
            return config
        }
    }

    static func fixtures() throws -> [Fixture] {
        let folder = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures", withExtension: nil))
        let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("hits-") }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        return try files.map { try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: $0)) }
    }

    func testFixturesPresent() throws {
        XCTAssertGreaterThanOrEqual(try Self.fixtures().count, 2)
    }

    /// The Swift defaults must equal the desktop config.py values the fixtures were made with.
    func testDefaultConfigMatchesDesktop() throws {
        for fixture in try Self.fixtures() {
            XCTAssertEqual(fixture.config, HitOnsetConfig(), "config drift vs desktop (\(fixture.name))")
        }
    }

    func testLevelsMatchPython() throws {
        for fixture in try Self.fixtures() {
            var detector = HitOnsetDetector(config: fixture.detectorConfig)
            XCTAssertEqual(detector.hop, fixture.hop, fixture.name)
            detector.append(fixture.samples)
            XCTAssertEqual(detector.levels.count, fixture.levels.count, fixture.name)
            let worst = zip(detector.levels, fixture.levels).map { abs($0 - $1) }.max() ?? .infinity
            // Python computes in float32 and the fixture rounds to 1e-4 dB.
            XCTAssertLessThan(worst, 1e-3, "\(fixture.name): largest level difference \(worst) dB")
        }
    }

    func testOnsetsMatchPythonExactly() throws {
        for fixture in try Self.fixtures() {
            let onsets = HitOnsetDetector.onsets(samples: fixture.samples, config: fixture.detectorConfig)
            XCTAssertEqual(onsets, fixture.onsets, fixture.name)
        }
    }

    /// Decoded audio arrives in buffers of any size; hops must not depend on where they split.
    func testChunkedAppendMatchesOneShot() throws {
        let fixture = try XCTUnwrap(Self.fixtures().first)
        let samples = fixture.samples
        var whole = HitOnsetDetector(config: fixture.detectorConfig)
        whole.append(samples)
        for chunk in [1, 37, 80, 1024] {
            var streamed = HitOnsetDetector(config: fixture.detectorConfig)
            for start in stride(from: 0, to: samples.count, by: chunk) {
                streamed.append(Array(samples[start..<min(start + chunk, samples.count)]))
            }
            XCTAssertEqual(streamed.levels.count, whole.levels.count, "chunk \(chunk)")
            // Accelerate may round a one-row multiply differently from a 600-row one.
            let worst = zip(streamed.levels, whole.levels).map { abs($0 - $1) }.max() ?? 0
            XCTAssertLessThan(worst, 1e-9, "chunk \(chunk)")
            XCTAssertEqual(streamed.onsets, whole.onsets, "chunk \(chunk)")
        }
    }
}

final class HitOnsetDetectorTests: XCTestCase {
    private func config(rate: Double, hopSeconds: Double = 0.005) -> HitOnsetConfig {
        var config = HitOnsetConfig()
        config.sampleRate = rate
        config.hopSeconds = hopSeconds
        return config
    }

    /// Expected bins from np.fft.rfftfreq(hop, 1 / rate) with the inclusive 1-6 kHz band.
    func testBandBinsMatchNumpy() {
        XCTAssertEqual(HitOnsetDetector(config: config(rate: 16000)).bandBins, Array(5...30))
        XCTAssertEqual(HitOnsetDetector(config: config(rate: 22050)).bandBins, Array(5...29))  // bin 30 is 6013 Hz
        XCTAssertEqual(HitOnsetDetector(config: config(rate: 48000)).bandBins, Array(5...30))
        XCTAssertEqual(HitOnsetDetector(config: config(rate: 8000)).bandBins, Array(5...20))  // stops at Nyquist
    }

    func testHopRoundsHalfToEvenLikePython() {
        XCTAssertEqual(config(rate: 16000).hop, 80)
        XCTAssertEqual(config(rate: 44100).hop, 220)  // 220.5
        XCTAssertEqual(config(rate: 5, hopSeconds: 0.5).hop, 2)  // 2.5
        XCTAssertEqual(config(rate: 7, hopSeconds: 0.5).hop, 4)  // 3.5
    }

    func testTooShortHasNoOnsets() {
        for count in [0, 10, 80, 159] {
            XCTAssertEqual(HitOnsetDetector.onsets(samples: Array(repeating: 0.5, count: count)), [], "\(count) samples")
        }
    }

    func testOnsetLookupForPlayback() {
        let hits = AudioHits(config: .init(), startSeconds: 0, durationSeconds: 3, onsets: [1.0, 2.0, 2.1])
        XCTAssertNil(hits.onset(before: 0.5, within: 0.2))
        XCTAssertEqual(hits.onset(before: 1.0, within: 0.2), 1.0)
        XCTAssertEqual(hits.onset(before: 1.15, within: 0.2), 1.0)
        XCTAssertNil(hits.onset(before: 1.25, within: 0.2))
        XCTAssertEqual(hits.onset(before: 2.05, within: 0.2), 2.0)
        XCTAssertEqual(hits.onset(before: 2.15, within: 0.2), 2.1)
        XCTAssertNil(AudioHits(config: .init(), startSeconds: 0, durationSeconds: 1, onsets: [])
            .onset(before: 1, within: 0.2))
    }

    /// End to end through AVFoundation: 48 kHz stereo, resampled and downmixed by the reader.
    func testFindsPopsInAnAudioFile() async throws {
        let pops = [0.5, 1.25, 2.0]
        let url = try Self.writeAudio(seconds: 3, pops: pops)
        defer { try? FileManager.default.removeItem(at: url) }
        let detected = try await AudioHits.detect(in: url)
        let hits = try XCTUnwrap(detected)
        XCTAssertEqual(hits.config, HitOnsetConfig())
        XCTAssertEqual(hits.startSeconds, 0, accuracy: 1e-6)
        XCTAssertEqual(hits.durationSeconds, 3, accuracy: 0.01)
        XCTAssertEqual(hits.onsets.count, pops.count, "\(hits.onsets)")
        for (found, expected) in zip(hits.onsets, pops) {
            XCTAssertEqual(found, expected, accuracy: 0.011)
        }
    }

    /// Audio that starts after the video (an empty edit) is read from where it starts: no hit
    /// at the jump out of the reader's zero-filled lead-in, and onsets on the asset timeline.
    func testAudioStartingLateHasNoHitWhereItStarts() async throws {
        let pops = [0.5, 1.25, 2.0]
        let url = try Self.writeAudio(seconds: 3, pops: pops)
        defer { try? FileManager.default.removeItem(at: url) }
        let source = AVURLAsset(url: url)
        let sourceTracks = try await source.loadTracks(withMediaType: .audio)
        let audio = try XCTUnwrap(sourceTracks.first)
        let duration = try await source.load(.duration)
        let composition = AVMutableComposition()
        let track = try XCTUnwrap(composition.addMutableTrack(withMediaType: .audio,
                                                              preferredTrackID: kCMPersistentTrackID_Invalid))
        try track.insertTimeRange(CMTimeRange(start: .zero, duration: duration), of: audio, at: .zero)
        track.insertEmptyTimeRange(CMTimeRange(start: .zero, duration: CMTime(value: 1, timescale: 2)))
        let detected = try await AudioHits.detect(in: composition)
        let hits = try XCTUnwrap(detected)
        XCTAssertEqual(hits.startSeconds, 0.5, accuracy: 0.01)
        XCTAssertEqual(hits.onsets.count, pops.count, "\(hits.onsets)")
        for (found, expected) in zip(hits.onsets, pops) {
            XCTAssertEqual(found, expected + 0.5, accuracy: 0.011)
        }
    }

    func testAssetWithoutAudioHasNoHits() async throws {
        let hits = try await AudioHits.detect(in: AVMutableComposition())
        XCTAssertNil(hits)
    }

    /// Court-like noise with paddle pops (10 ms bursts decaying over 2.5 ms), written as a
    /// 48 kHz stereo file.
    private static func writeAudio(seconds: Double, pops: [Double]) throws -> URL {
        let rate = 48000.0
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2))
        let frames = AVAudioFrameCount(seconds * rate)
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames))
        buffer.frameLength = frames
        var random = SplitMix64(seed: 7)
        var signal = (0..<Int(frames)).map { _ in Float(random.uniform() * 0.017) }
        for time in pops {
            let start = Int(time * rate)
            for n in 0..<Int(0.01 * rate) where start + n < signal.count {
                signal[start + n] += Float(random.uniform() * 0.6 * exp(-Double(n) / (0.0025 * rate)))
            }
        }
        for channel in 0..<2 {
            let samples = try XCTUnwrap(buffer.floatChannelData?[channel])
            for (index, value) in signal.enumerated() { samples[index] = value }
        }
        let url = FileManager.default.temporaryDirectory.appending(path: "hits-\(UUID().uuidString).caf")
        let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: rate,
                                       AVNumberOfChannelsKey: 2, AVLinearPCMBitDepthKey: 32,
                                       AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false]
        let file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        try file.write(from: buffer)
        file.close()
        return url
    }
}

/// Deterministic noise for test signals.
private struct SplitMix64 {
    var state: UInt64
    init(seed: UInt64) { state = seed }
    /// Uniform in [-1, 1).
    mutating func uniform() -> Double {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        z ^= z >> 31
        return Double(z >> 11) / Double(1 << 52) - 1
    }
}
