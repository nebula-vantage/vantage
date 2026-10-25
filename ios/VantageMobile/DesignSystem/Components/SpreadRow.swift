import SwiftUI

/// Leading content and a trailing value on one line ("Games … 5 GAMES"). At accessibility text
/// sizes the two stack instead, so neither gets squeezed into broken words.
struct SpreadRow<Leading: View, Trailing: View>: View {
    var alignment: VerticalAlignment = .center
    @ViewBuilder let leading: Leading
    @ViewBuilder let trailing: Trailing

    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Theme.Spacing.xs))
            : AnyLayout(HStackLayout(alignment: alignment, spacing: Theme.Spacing.m))
        layout {
            leading.frame(maxWidth: .infinity, alignment: .leading)
            trailing
        }
    }
}

#Preview {
    VStack(spacing: Theme.Spacing.m) {
        ForEach([DynamicTypeSize.large, .accessibility3], id: \.self) { size in
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                SpreadRow(alignment: .firstTextBaseline) {
                    Text("Games").font(Theme.Fonts.display)
                } trailing: {
                    Text("5 games").monoLabel()
                }
                SpreadRow {
                    Text("Pickleball · Uploaded").monoLabel()
                } trailing: {
                    Text("0:38:12").monoLabel()
                }
            }
            .card()
            .dynamicTypeSize(size)
        }
    }
    .padding(Theme.Spacing.l)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
