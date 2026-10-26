import SwiftUI

enum PlayerSide: CaseIterable, Identifiable {
    case you, opponent

    var id: Self { self }
    var title: String { self == .you ? "You" : "Opponent" }
    var color: Color { self == .you ? Theme.Colors.accent : Theme.Colors.opponent }
}

/// The You/Opponent switch from the game screen mockup. VoiceOver sees a standard picker.
struct PlayerToggle: View {
    @Binding var selection: PlayerSide

    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        // Side by side normally; stacked at accessibility sizes so "Opponent" isn't broken mid-word.
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(spacing: Theme.Spacing.xs))
            : AnyLayout(HStackLayout(spacing: Theme.Spacing.xs))
        layout {
            ForEach(PlayerSide.allCases) { side in
                Button { selection = side } label: { segment(side) }
                    .buttonStyle(.plain)
            }
        }
        .padding(Theme.Spacing.xs)
        .background(Theme.Colors.track, in: .rect(cornerRadius: Theme.Radius.card, style: .continuous))
        .animation(.snappy(duration: 0.2), value: selection)
        .accessibilityRepresentation {
            Picker("Player", selection: $selection) {
                ForEach(PlayerSide.allCases) { side in Text(side.title).tag(side) }
            }
        }
    }

    private func segment(_ side: PlayerSide) -> some View {
        let selected = selection == side
        return HStack(spacing: Theme.Spacing.s) {
            Circle().fill(side.color).frame(width: Theme.Size.dot, height: Theme.Size.dot)
            Text(side.title)
        }
        .font(Theme.Fonts.headline)
        .foregroundStyle(selected ? Theme.Colors.ink : Theme.Colors.inkSecondary)
        .frame(maxWidth: .infinity, minHeight: Theme.Size.minTouch)
        .background {
            if selected {
                RoundedRectangle(cornerRadius: Theme.Radius.segment, style: .continuous).fill(Theme.Colors.surface)
            }
        }
        .contentShape(.rect)
    }
}

#Preview {
    @Previewable @State var side = PlayerSide.you
    VStack(spacing: Theme.Spacing.l) {
        PlayerToggle(selection: $side)
        PlayerToggle(selection: .constant(.opponent))
        PlayerToggle(selection: $side).dynamicTypeSize(.accessibility2)
    }
    .padding(Theme.Spacing.l)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
