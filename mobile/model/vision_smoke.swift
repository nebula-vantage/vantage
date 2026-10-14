// Build together with ios/Sources/Detector.swift on macOS; no Xcode required.
import CoreML
import CoreImage
import Foundation

@main
struct VisionSmoke {
    static func main() throws {
        guard CommandLine.arguments.count == 3 else {
            throw PrototypeError.message("Usage: vision-smoke model.mlpackage image.png")
        }
        let package = URL(fileURLWithPath: CommandLine.arguments[1])
        let compiled = try MLModel.compileModel(at: package)
        defer { try? FileManager.default.removeItem(at: compiled) }
        let detector = try Detector(url: compiled)
        guard let image = CIImage(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]),
                                  options: [.applyOrientationProperty: true]) else {
            throw PrototypeError.message("Cannot load image.")
        }
        let detections = try detector.detect(image)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        print(String(decoding: try encoder.encode(detections), as: UTF8.self))
    }
}
