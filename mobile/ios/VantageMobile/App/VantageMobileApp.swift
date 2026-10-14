import SwiftUI
import UniformTypeIdentifiers

@main
struct VantageMobileApp: App {
    var body: some Scene { WindowGroup { ContentView() } }
}

struct ContentView: View {
    @State private var importing = false
    @State private var running = false
    @State private var progress = 0.0
    @State private var message = "Choose a short court video to test on-device detection."
    @State private var result: AnalysisResult?
    @State private var job: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 20) {
                Text("Detector prototype").font(.title2.bold())
                Text("Video stays on this iPhone. This first build measures detections; tracking and match stats come next.")
                Button("Import video") { importing = true }.disabled(running)
                if running {
                    ProgressView(value: progress)
                    Button("Cancel", role: .cancel) { job?.cancel() }
                }
                Text(message)
                if let result {
                    ShareLink("Export timestamped detections", item: result.file)
                }
                Spacer()
            }
            .padding()
            .navigationTitle("Vantage")
            .fileImporter(isPresented: $importing, allowedContentTypes: [.movie]) { selection in
                switch selection {
                case .failure(let error): message = error.localizedDescription
                case .success(let url): run(url)
                }
            }
        }
    }

    @MainActor private func run(_ url: URL) {
        guard let model = Bundle.main.url(forResource: "VantageDetector", withExtension: "mlmodelc") else {
            message = "Missing model. Add the exported VantageDetector.mlpackage to the app target."
            return
        }
        running = true
        progress = 0
        result = nil
        message = "Analyzing…"
        job = Task {
            let access = url.startAccessingSecurityScopedResource()
            defer {
                if access { url.stopAccessingSecurityScopedResource() }
                running = false
            }
            do {
                let analyzed = try await VideoAnalyzer().analyze(video: url, model: model) { value in
                    await MainActor.run { progress = value }
                }
                result = analyzed
                message = "\(analyzed.frames) frames processed. Ball detected in \(analyzed.ballFrames) frames. Average detector time: \(Int(analyzed.averageMilliseconds)) ms/frame (includes warmup)."
            } catch is CancellationError {
                message = "Analysis cancelled."
            } catch {
                message = error.localizedDescription
            }
        }
    }
}
