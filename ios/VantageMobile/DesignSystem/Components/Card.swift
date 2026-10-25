import SwiftUI

/// The raised white surface that holds a game, a tile or a group of stats.
struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
        content
            .padding(Theme.Spacing.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.Colors.surface, in: shape)
            .overlay { shape.strokeBorder(Theme.Colors.hairline, lineWidth: Theme.Size.hairline) }
            .contentShape(shape)
            .contentShape(.contextMenuPreview, shape)
    }
}

extension View {
    func card() -> some View { modifier(CardModifier()) }
}

#Preview {
    ScrollView {
        VStack(spacing: Theme.Spacing.m) {
            Text("Short").card()
            Text("A much longer line of text that wraps onto several lines inside the card to check padding.")
                .font(Theme.Fonts.body)
                .card()
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                Text("Pickleball · Uploaded").monoLabel()
                Text("IMG_4821.MOV").font(Theme.Fonts.title)
            }
            .card()
            Color.clear.frame(height: 0).card()
        }
        .padding(Theme.Spacing.l)
    }
    .background(Theme.Colors.background)
}
