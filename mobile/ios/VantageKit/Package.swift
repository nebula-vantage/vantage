// swift-tools-version:6.0
// Platform-independent Vantage logic shared by the iPhone app and Mac tools:
// detection records, Core ML detector, video analysis, ball tracking, and playback timeline.
// Test on a Mac with: swift test (from this directory).
import PackageDescription

let package = Package(
    name: "VantageKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [
        .library(name: "VantageKit", targets: ["VantageKit"]),
        .executable(name: "vantage-analyze", targets: ["vantage-analyze"]),
    ],
    targets: [
        .target(name: "VantageKit"),
        // Mac CLI: run the same on-device analysis on a video and write detections JSONL.
        .executableTarget(name: "vantage-analyze", dependencies: ["VantageKit"]),
        .testTarget(name: "VantageKitTests", dependencies: ["VantageKit"], resources: [.copy("Fixtures")]),
    ],
    swiftLanguageModes: [.v5]
)
