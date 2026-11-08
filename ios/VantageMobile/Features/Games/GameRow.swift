import SwiftUI
import UIKit
import VantageKit

/// A finished game in the games list, laid out as the web's game cards: a cover (the video's
/// thumbnail, or a court drawing without one) with the sport and the length, then the date, the
/// name and what was measured. Rally and shot counts come from `stats.json`, so they're left out
/// until the engine writes it. Goes in an unpadded card (`.card(padded: false)`) so the cover
/// reaches its edges.
struct GameRow: View {
    let run: AnalysisRun
    let stats: GameStats?
    /// The frame saved when the video was imported (`RunStore.thumbnailURL(for:)`); may not exist.
    let thumbnail: URL
    /// The game's video (`RunStore.videoURL(for:)`), to make a sharper thumbnail from when the saved
    /// one is too small for the cover.
    let video: URL

    @State private var image: UIImage?
    /// The cover's width once laid out, in points; the picture is decoded at the cover's size.
    @State private var coverWidth: CGFloat = 0
    @Environment(\.displayScale) private var displayScale
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    /// The cover's size on screen, in pixels.
    private var coverPixels: CGSize {
        CGSize(width: coverWidth * displayScale, height: Theme.Size.gameCover * displayScale)
    }

    /// What was measured ("12 rallies · 87 shots · 62% ball tracked"), or nil when nothing was.
    private var summary: String? {
        let parts = [
            (stats?.measured?.rallyCount).map { Format.count($0, "rally", "rallies") },
            (stats?.measured?.shotCount).map { Format.count($0, "shot", "shots") },
            run.ballTrackedFraction(with: stats).map { "\(Format.percent($0)) ball tracked" },
        ].compactMap(\.self)
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            cover
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(Format.analyzedDate(run.createdAt))
                        .font(Theme.Fonts.callout)
                        .foregroundStyle(Theme.Colors.inkSecondary)
                    // Two lines, except at accessibility sizes, where that's only a word or two.
                    Text(run.sourceName)
                        .font(Theme.Fonts.title)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                }
                if let summary { StatusNote(summary) }
                footer
            }
            .padding(Theme.Spacing.l)
        }
        .task(id: coverPixels) {
            guard coverWidth > 0 else { return }
            // A cancelled load (scrolled away) keeps whatever picture is already showing.
            if let cover = await RunStore.coverImage(for: run, thumbnail: thumbnail, video: video, size: coverPixels) {
                image = cover
            }
        }
    }

    private var cover: some View {
        // The picture fills a fixed height, as on the web, and is cropped to it.
        Theme.Colors.videoBackground
            .frame(height: Theme.Size.gameCover)
            .onGeometryChange(for: CGFloat.self) { $0.size.width.rounded() } action: { coverWidth = $0 }
            .overlay {
                if let image {
                    Image(uiImage: image).resizable().scaledToFill().accessibilityHidden(true)
                } else {
                    CourtMotif().padding(.top, Theme.Spacing.xxl)
                }
            }
            .clipped()
            .overlay(alignment: .topLeading) {
                Text("Pickleball")
                    .monoLabel(Theme.Colors.headingOnDark)
                    .shadowOverPhoto()
                    .padding(Theme.Spacing.l)
            }
            .overlay(alignment: .bottomTrailing) {
                Text(Format.duration(run.durationSeconds))
                    .monoLabel(Theme.Colors.headingOnDark)
                    .monospacedDigit()
                    .padding(.horizontal, Theme.Spacing.s)
                    .padding(.vertical, Theme.Spacing.xs)
                    .background(Theme.Colors.scrim, in: .rect(cornerRadius: Theme.Radius.badge))
                    .padding(Theme.Spacing.m)
            }
            // Labels over the picture stop growing before they cover it.
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
    }

    /// The web's footer has "Replay + coaching" on the left; the iPhone has no coaching yet.
    private var footer: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            Rectangle().fill(Theme.Colors.hairline).frame(height: Theme.Size.hairline)
            HStack(spacing: Theme.Spacing.xs) {
                Spacer()
                Text("Open game")
                Image(systemName: "arrow.right").accessibilityHidden(true)
            }
            .font(Theme.Fonts.fieldLabel)
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
    let missing = URL(filePath: "/nonexistent/thumbnail.jpg")
    let noVideo = URL(filePath: "/nonexistent/video.mov")
    ScrollView {
        VStack(spacing: Theme.Spacing.m) {
            Button {} label: { GameRow(run: run, stats: .sample, thumbnail: missing, video: noVideo) }.buttonStyle(.card(padded: false))
            Button {} label: { GameRow(run: run, stats: nil, thumbnail: missing, video: noVideo) }.buttonStyle(.card(padded: false))
            Button {} label: { GameRow(run: old, stats: nil, thumbnail: missing, video: noVideo) }.buttonStyle(.card(padded: false))
        }
        .padding(Theme.Spacing.l)
    }
    .background(Theme.Colors.background)
}
