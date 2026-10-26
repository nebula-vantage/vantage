import SwiftUI
import VantageKit

/// One analyzed game: the video with overlays, then its stats. Stats come from `stats.json`;
/// until the engine writes it they read "—", except the ball-tracked share the analyzer measures.
struct GameDetailView: View {
    let run: AnalysisRun
    let store: RunStore

    @State private var side = PlayerSide.you
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        let stats = store.stats(for: run)
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
                header
                GameVideoCard(run: run, videoURL: store.videoURL(for: run), detectionsURL: store.detectionsURL(for: run),
                              trackedFraction: run.ballTrackedFraction(with: stats))
                playerSection
                matchSection(stats)
                bouncesSection(stats)
                notes(stats)
            }
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.bottom, Theme.Spacing.xl)
        }
        .background(Theme.Colors.background)
        .navigationTitle(run.sourceName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(removing: .title)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink(value: GameRoute.debugPlayback(run)) {
                    Label("Debug playback", systemImage: "ladybug")
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text("Pickleball · \(Format.gameDate(run.createdAt))").monoLabel()
            Text(run.sourceName)
                .font(Theme.Fonts.display)
                .foregroundStyle(Theme.Colors.ink)
                .lineLimit(3)
                .accessibilityAddTraits(.isHeader)
        }
    }

    /// Per-player stats need player identification, which the analyzer doesn't do yet, so both
    /// sides read "—" for now.
    private var playerSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            PlayerToggle(selection: $side)
            grid([
                StatTile(label: "Shots", value: Format.missing),
                StatTile(label: "Avg speed", value: Format.missing, unit: Format.kmh),
                StatTile(label: "Distance", value: Format.missing, unit: Format.metres),
            ], columns: 3)
            Text("Per-player stats need the app to tell players apart, which isn't available yet.")
                .font(Theme.Fonts.callout)
                .foregroundStyle(Theme.Colors.inkTertiary)
        }
    }

    private func matchSection(_ stats: GameStats?) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            Text("Match · both players").monoLabel()
            grid([
                StatTile(label: "Rallies", value: Format.count(stats?.rallyCount)),
                StatTile(label: "Avg rally", value: Format.decimal(stats?.averageShotsPerRally), unit: "shots"),
                StatTile(label: "Longest", value: Format.count(stats?.longestRally), unit: "shots"),
                StatTile(label: "Shots", value: Format.count(stats?.shotCount)),
                StatTile(label: "Avg speed", value: Format.speed(stats?.averageBallSpeedKmh), unit: Format.kmh),
                StatTile(label: "Tracked", value: Format.percent(run.ballTrackedFraction(with: stats)),
                         unit: "of frames"),
            ], columns: 3)
        }
    }

    private func bouncesSection(_ stats: GameStats?) -> some View {
        let bounces: [Bounce] = stats?.bounces ?? []
        return VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            Text("Bounces").monoLabel()
            grid([
                StatTile(label: "In", value: Format.count(stats?.inCount)),
                StatTile(label: "Out", value: Format.count(stats?.outCount)),
            ], columns: 2)
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                CourtDiagram(court: stats?.court ?? .pickleball) { geometry in
                    ForEach(Array(bounces.enumerated()), id: \.offset) { _, bounce in
                        LandingDot(call: bounce.call, uncertain: bounce.nearBoundary)
                            .position(geometry.point(bounce.court))
                    }
                }
                .frame(maxWidth: Theme.Size.courtMaxWidth)
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Landing spots")
                .accessibilityValue(stats == nil ? "Not measured" : "\(stats!.inCount) in, \(stats!.outCount) out")
                HStack(spacing: Theme.Spacing.l) {
                    legendItem("In") { LandingDot(call: .inBounds, uncertain: false) }
                    legendItem("Out") { LandingDot(call: .out, uncertain: false) }
                    legendItem("Close call") { LandingDot(call: .inBounds, uncertain: true) }
                }
                .accessibilityHidden(true)
            }
            .card()
        }
    }

    @ViewBuilder
    private func notes(_ stats: GameStats?) -> some View {
        let lines: [String] = stats?.quality.warnings
            ?? ["Rally, speed and bounce stats aren't computed on iPhone yet."]
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            ForEach(lines, id: \.self) { line in
                Text(line)
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkTertiary)
            }
        }
    }

    private func legendItem(_ title: String, @ViewBuilder mark: () -> some View) -> some View {
        HStack(spacing: Theme.Spacing.xs) {
            mark()
            Text(title).font(Theme.Fonts.callout).foregroundStyle(Theme.Colors.inkSecondary)
        }
    }

    /// Tiles in rows of `columns` sharing a height; one per row at accessibility text sizes.
    private func grid(_ tiles: [StatTile], columns: Int) -> some View {
        let perRow = typeSize.isAccessibilitySize ? 1 : columns
        let rows: [[StatTile]] = stride(from: 0, to: tiles.count, by: perRow).map { start in
            Array(tiles[start..<min(start + perRow, tiles.count)])
        }
        return Grid(horizontalSpacing: Theme.Spacing.m, verticalSpacing: Theme.Spacing.m) {
            ForEach(rows.indices, id: \.self) { row in
                GridRow {
                    ForEach(rows[row].indices, id: \.self) { column in rows[row][column] }
                }
            }
        }
    }
}

/// A bounce on the court diagram: filled when in, a ring when out, half-filled when it's a close
/// call either way.
private struct LandingDot: View {
    let call: Bounce.Call
    let uncertain: Bool

    private var fill: Color {
        if uncertain { return Theme.Colors.accent.opacity(0.4) }
        return call == .inBounds ? Theme.Colors.accent : Theme.Colors.surface
    }

    var body: some View {
        Circle()
            .fill(fill)
            .stroke(Theme.Colors.accent, lineWidth: Theme.Size.hairline * 2)
            .frame(width: Theme.Size.landingDot, height: Theme.Size.landingDot)
    }
}
