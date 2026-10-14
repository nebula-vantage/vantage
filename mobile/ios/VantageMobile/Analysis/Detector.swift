import CoreML
import Vision
import CoreImage
import Foundation

/// COCO class IDs used as proxies, matching the desktop pipeline's config.py.
enum DetectionClass {
    static let player = 0
    static let ball = 32
    static let paddle = 38  // "tennis racket"; a pickleball-paddle proxy.
    static let all: Set<Int> = [player, ball, paddle]
}

struct Detection: Codable, Sendable, Hashable {
    let classID: Int
    let confidence: Double
    // [x1, y1, x2, y2], top-left origin, pixels in the oriented source image.
    let box: [Double]

    var center: CGPoint { CGPoint(x: (box[0] + box[2]) / 2, y: (box[1] + box[3]) / 2) }
    var rect: CGRect { CGRect(x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1]) }
}

enum PrototypeError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let text): return text }
    }
}

/// Confined to the analyzer actor. Matches square Ultralytics letterboxing:
/// RGB input, 114 padding, centered rounded resize, no extra NMS for YOLO26.
final class Detector {
    private let request: VNCoreMLRequest
    private let context = CIContext()
    private let size: Int

    init(url: URL) throws {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .cpuAndNeuralEngine
        let model = try MLModel(contentsOf: url, configuration: configuration)
        guard let constraint = model.modelDescription.inputDescriptionsByName["image"]?.imageConstraint,
              constraint.pixelsWide == constraint.pixelsHigh else {
            throw PrototypeError.message("Expected a square image-input model.")
        }
        size = constraint.pixelsWide
        request = VNCoreMLRequest(model: try VNCoreMLModel(for: model))
        request.imageCropAndScaleOption = .scaleFill
    }

    func detect(_ image: CIImage) throws -> [Detection] {
        let width = image.extent.width, height = image.extent.height
        let gain = min(Double(size)/width, Double(size)/height)
        let resizedWidth = (width*gain).rounded(.toNearestOrEven)
        let resizedHeight = (height*gain).rounded(.toNearestOrEven)
        let left = ((Double(size)-resizedWidth)/2-0.1).rounded()
        let top = ((Double(size)-resizedHeight)/2-0.1).rounded()
        let bottom = Double(size)-resizedHeight-top
        let originAdjusted = image.transformed(by: .init(translationX: -image.extent.minX, y: -image.extent.minY))
        let resized = originAdjusted.transformed(by: .init(scaleX: resizedWidth/width, y: resizedHeight/height))
            .transformed(by: .init(translationX: left, y: bottom))
        let bounds = CGRect(x: 0, y: 0, width: size, height: size)
        let background = CIImage(color: CIColor(red: 114/255.0, green: 114/255.0, blue: 114/255.0)).cropped(to: bounds)
        guard let input = context.createCGImage(resized.composited(over: background), from: bounds) else {
            throw PrototypeError.message("Could not prepare video frame.")
        }
        try VNImageRequestHandler(cgImage: input, orientation: .up).perform([request])
        let arrays = (request.results as? [VNCoreMLFeatureValueObservation])?.compactMap { $0.featureValue.multiArrayValue } ?? []
        guard let output = arrays.first(where: { $0.shape.count == 3 && $0.shape[0].intValue == 1 && $0.shape[2].intValue == 6 }) else {
            throw PrototypeError.message("Expected YOLO26 NMS-free output [1, N, 6]. Re-export with mobile/export_model.py.")
        }
        var detections: [Detection] = []
        for row in 0..<output.shape[1].intValue {
            func value(_ column: Int) -> Double { output[[0, NSNumber(value: row), NSNumber(value: column)]].doubleValue }
            let values = (0..<6).map(value)
            guard values.allSatisfy({ $0.isFinite }), values[4] >= 0.10 else { continue }
            let cls = Int(values[5])
            guard DetectionClass.all.contains(cls) else { continue }
            let box = [max(0, min(width, (values[0]-left)/gain)),
                       max(0, min(height, (values[1]-top)/gain)),
                       max(0, min(width, (values[2]-left)/gain)),
                       max(0, min(height, (values[3]-top)/gain))]
            guard box[2] > box[0], box[3] > box[1] else { continue }
            detections.append(Detection(classID: cls, confidence: values[4], box: box))
        }
        return detections
    }
}
