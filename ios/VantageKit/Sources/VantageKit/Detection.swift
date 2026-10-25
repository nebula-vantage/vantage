import CoreGraphics
import Foundation

/// Vantage's canonical class IDs, used in every Detection and detections.jsonl regardless
/// of the model. They follow COCO numbering so runs made with the generic COCO model stay
/// valid; other models (e.g. a fine-tuned player/ball/paddle model) are mapped by class name.
public enum DetectionClass {
    public static let player = 0
    public static let ball = 32
    public static let paddle = 38  // COCO "tennis racket" is the proxy in generic models.
    public static let all: Set<Int> = [player, ball, paddle]

    /// Model class names accepted for each canonical class.
    static let aliases: [String: Int] = [
        "person": player, "player": player,
        "sports ball": ball, "ball": ball, "pickleball": ball,
        "tennis racket": paddle, "paddle": paddle,
    ]

    /// Maps model class indices to canonical IDs from an Ultralytics `names` metadata string,
    /// e.g. "{0: 'person', 1: 'bicycle', ...}". Classes without an alias are dropped.
    public static func canonicalMap(namesMetadata: String) -> [Int: Int] {
        let pattern = try! Regex(#"(\d+)\s*:\s*['"]([^'"]*)['"]"#)
        var map: [Int: Int] = [:]
        for match in namesMetadata.matches(of: pattern) {
            if let index = match[1].substring.flatMap({ Int($0) }),
               let name = match[2].substring, let canonical = aliases[name.lowercased()] {
                map[index] = canonical
            }
        }
        return map
    }
}

/// One raw detector output.
public struct Detection: Codable, Sendable, Hashable {
    public let classID: Int
    public let confidence: Double
    /// [x1, y1, x2, y2], top-left origin, pixels in the oriented source image.
    public let box: [Double]

    public init(classID: Int, confidence: Double, box: [Double]) {
        self.classID = classID
        self.confidence = confidence
        self.box = box
    }

    public var center: CGPoint { CGPoint(x: (box[0] + box[2]) / 2, y: (box[1] + box[3]) / 2) }
    public var rect: CGRect { CGRect(x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1]) }
}

/// One analyzed video frame; one JSON line in detections.jsonl.
public struct FrameDetections: Codable, Sendable {
    /// Source presentation timestamp (same timeline as AVPlayer).
    public let timeSeconds: Double
    /// Oriented frame size in pixels.
    public let width: Double
    public let height: Double
    public let inferenceMilliseconds: Double
    public let detections: [Detection]

    public init(timeSeconds: Double, width: Double, height: Double,
                inferenceMilliseconds: Double, detections: [Detection]) {
        self.timeSeconds = timeSeconds
        self.width = width
        self.height = height
        self.inferenceMilliseconds = inferenceMilliseconds
        self.detections = detections
    }

    public var balls: [Detection] { detections.filter { $0.classID == DetectionClass.ball } }
}

public enum AnalysisError: LocalizedError {
    case message(String)
    public var errorDescription: String? {
        switch self { case .message(let text): return text }
    }
}
