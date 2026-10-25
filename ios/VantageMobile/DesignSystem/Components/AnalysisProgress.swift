import SwiftUI

/// Progress of an on-device analysis: a bar and "Analyzing · 62%". A nil `fraction` means the
/// analysis hasn't started yet (the video is still being copied) and reads "Preparing…".
struct AnalysisProgressView: View {
    let fraction: Double?

    private var clamped: Double? { fraction.map { min(1, max(0, $0)) } }

    var body: some View {
        ProgressView(value: clamped) {
            EmptyView()
        } currentValueLabel: {
            Text(clamped.map { "Analyzing · \(Format.percent($0))" } ?? "Preparing…")
        }
        .progressViewStyle(BarProgressStyle())
    }
}

private struct BarProgressStyle: ProgressViewStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Capsule()
                .fill(Theme.Colors.track)
                .frame(height: Theme.Size.progressBar)
                .overlay(alignment: .leading) {
                    GeometryReader { proxy in
                        Capsule()
                            .fill(Theme.Colors.ink)
                            .frame(width: proxy.size.width * (configuration.fractionCompleted ?? 0))
                    }
                }
            if let label = configuration.currentValueLabel {
                label
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
                    .monospacedDigit()
            }
        }
    }
}

#Preview {
    VStack(spacing: Theme.Spacing.m) {
        AnalysisProgressView(fraction: nil).card()
        AnalysisProgressView(fraction: 0).card()
        AnalysisProgressView(fraction: 0.62).card()
        AnalysisProgressView(fraction: 1).card()
        AnalysisProgressView(fraction: 1.4).card()
    }
    .padding(Theme.Spacing.l)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
