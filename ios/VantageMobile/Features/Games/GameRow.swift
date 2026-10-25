import SwiftUI
import VantageKit

/// A finished game in the games list. Rally and shot counts come from `stats.json`, so they
/// read "—" until the engine writes it.
struct GameRow: View {
    let run: AnalysisRun
    let stats: GameStats?

    private var summary: String {
        let tracked = stats?.quality.ballTrackedFraction ?? run.trackedBallFraction
        return [
            Format.count(stats?.rallyCount, "rally", "rallies"),
            Format.count(stats?.shotCount, "shot", "shots"),
            "\(Format.percent(tracked)) ball tracked",
        ].joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            HStack {
                Text("Pickleball · Uploaded").monoLabel()
                Spacer()
                Text(Format.duration(run.durationSeconds)).monoLabel().monospacedDigit()
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(run.sourceName).font(Theme.Fonts.title).lineLimit(2)
                Text(Format.gameDate(run.createdAt))
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
            }
            HStack(spacing: Theme.Spacing.m) {
                Text(summary).font(Theme.Fonts.headline).monospacedDigit()
                Spacer()
                Image(systemName: "chevron.right")
                    .font(Theme.Fonts.headline)
                    .foregroundStyle(Theme.Colors.inkTertiary)
            }
        }
    }
}

#Preview {
    let run = AnalysisRun(
        id: UUID(), createdAt: .now, sourceName: "IMG_4821.MOV", videoFileName: "video.mov",
        frames: 4_800, ballFrames: 3_400, trackedBallFrames: 2_976, averageMilliseconds: 21,
        width: 1920, height: 1080, durationSeconds: 2_292)
    let old = AnalysisRun(
        id: UUID(), createdAt: .now.addingTimeInterval(-9 * 86_400),
        sourceName: "Saturday doubles at the community centre, second session.mov", videoFileName: "video.mov",
        frames: 900, ballFrames: 300, averageMilliseconds: 24, width: 1920, height: 1080, durationSeconds: 45)
    ScrollView {
        VStack(spacing: Theme.Spacing.m) {
            Button {} label: { GameRow(run: run, stats: .sample) }.buttonStyle(.card)
            Button {} label: { GameRow(run: run, stats: nil) }.buttonStyle(.card)
            Button {} label: { GameRow(run: old, stats: nil) }.buttonStyle(.card)
        }
        .padding(Theme.Spacing.l)
    }
    .background(Theme.Colors.background)
}
