import SwiftUI
import UIKit

/// A sentence-case label, the field, and its error underneath, as on the web forms. The field
/// carries the same label for VoiceOver (`TextField(label, text:, prompt:)`), so the visible one is
/// hidden, and reads its error as a hint, as the web's `aria-describedby`. `accessory` sits at the
/// end of the label row (Sign in's "Forgot password?"). `focus` and `value` are the form's
/// `@FocusState` and this field's case in it, as given to the field's own `.focused(_:equals:)`:
/// focused, the box draws the web's focus border and ring, and tapping anywhere in the box puts the
/// keyboard in the field, not just on its line of text.
struct FormField<Field: View, Accessory: View>: View {
    let label: String
    let error: String?
    let focused: Bool
    let takeFocus: () -> Void
    @ViewBuilder let field: Field
    @ViewBuilder let accessory: Accessory

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.isEnabled) private var isEnabled

    init<Value: Hashable>(_ label: String, error: String?, focus: FocusState<Value?>.Binding, equals value: Value,
                          @ViewBuilder field: () -> Field, @ViewBuilder accessory: () -> Accessory) {
        self.label = label
        self.error = error
        focused = focus.wrappedValue == value
        takeFocus = { focus.wrappedValue = value }
        self.field = field()
        self.accessory = accessory()
    }

    var body: some View {
        // At accessibility sizes the accessory moves under the label instead of crowding it.
        let labelRow = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 0))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: Theme.Spacing.m))
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            labelRow {
                Text(label)
                    .font(Theme.Fonts.fieldLabel)
                    .foregroundStyle(Theme.Colors.ink)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityHidden(true)
                // A link's 44-point touch area reaches into the gaps above and below rather than
                // pushing the field down; at accessibility sizes its text is that tall anyway.
                accessory
                    .padding(.vertical, dynamicTypeSize.isAccessibilitySize ? 0 : -Theme.Spacing.s)
            }
            field
                .fieldBox(invalid: error != nil, focused: focused, onTap: isEnabled ? takeFocus : nil)
                .accessibilityHint(error ?? "")
            if let error { FormMessage(error) }
        }
    }
}

extension FormField where Accessory == EmptyView {
    init<Value: Hashable>(_ label: String, error: String?, focus: FocusState<Value?>.Binding, equals value: Value,
                          @ViewBuilder field: () -> Field) {
        self.init(label, error: error, focus: focus, equals: value, field: field) { EmptyView() }
    }
}

/// A field error ("Enter a valid email address."), or a confirmation ("Profile saved.") in
/// `Theme.Colors.positive`.
struct FormMessage: View {
    let text: String
    let color: Color

    init(_ text: String, color: Color = Theme.Colors.error) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(Theme.Fonts.footnote)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// An error that belongs to the whole form ("That email and password don't match."), in a tinted
/// box above the fields, as the web's `.form-error`.
struct FormErrorBanner: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
        Text(text)
            .font(Theme.Fonts.footnote)
            .foregroundStyle(Theme.Colors.error)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.vertical, Theme.Spacing.m)
            .background(Theme.Colors.errorSurface, in: shape)
            .overlay { shape.strokeBorder(Theme.Colors.errorLine, lineWidth: Theme.Size.hairline) }
    }
}

/// A password field with a Show/Hide toggle. Takes the form's focus binding so Return can move
/// into it and focus survives the toggle. The toggle sits in front of the field box, so tapping it
/// toggles rather than focusing.
struct PasswordField<Focus: Hashable>: View {
    let label: String
    var prompt: String = ""
    @Binding var text: String
    /// `.password` to sign in, `.newPassword` to set one.
    let contentType: UITextContentType
    let focus: FocusState<Focus?>.Binding
    let field: Focus

    @State private var revealed = false

    var body: some View {
        HStack(spacing: Theme.Spacing.s) {
            Group {
                if revealed {
                    TextField(label, text: $text, prompt: .prompt(prompt))
                } else {
                    SecureField(label, text: $text, prompt: .prompt(prompt))
                }
            }
            .textContentType(contentType)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .focused(focus, equals: field)

            Button(revealed ? "Hide" : "Show") {
                let wasFocused = focus.wrappedValue == field
                revealed.toggle()
                // The swapped-in field starts unfocused; give it the keyboard back.
                if wasFocused { Task { focus.wrappedValue = field } }
            }
            .font(Theme.Fonts.fieldLabel)
            .foregroundStyle(Theme.Colors.inkSecondary)
            .padding(.horizontal, Theme.Spacing.m)
            .frame(minWidth: Theme.Size.minTouch, minHeight: Theme.Size.minTouch)
            .contentShape(.rect)
            .buttonStyle(.plain)
            // "Show password", "Show current password": which field it reveals, as on the web.
            .accessibilityLabel("\(revealed ? "Hide" : "Show") \(label.lowercased())")
        }
    }
}

extension Text {
    /// A text field's placeholder ("you@example.com"), in the web's placeholder grey rather than
    /// the system's lighter one.
    static func prompt(_ text: String) -> Text {
        Text(text).foregroundStyle(Theme.Colors.placeholder)
    }
}

/// Helpers the account forms share.
enum FormFeedback {
    /// The message for the rule `check` breaks, or nil when it passes.
    static func error(_ check: () throws -> Any) -> String? {
        do {
            _ = try check()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    /// Reads a message aloud for VoiceOver, which doesn't notice text appearing elsewhere on screen.
    static func announce(_ message: String?) {
        guard let message else { return }
        AccessibilityNotification.Announcement(message).post()
    }
}

extension View {
    #if DEBUG
    /// UI check hook: `-scrollToBottom` opens `screen`'s scroll view at its end, for screenshots of
    /// what's below the fold, the first time it's shown.
    func debugScrollAnchor(_ screen: String) -> some View {
        defaultScrollAnchor(LaunchHooks.holds("-scrollToBottom", on: screen) ? .bottom : nil)
            .onDisappear { LaunchHooks.finish("-scrollToBottom", on: screen) }
    }
    #endif

    /// The box around a text field: white with a hairline, as on the web. Focused, the border turns
    /// ink with a soft teal ring just outside it; with an error, the border is the error colour.
    /// `onTap` gets the taps the field itself doesn't: above and below its line of text, and in the
    /// padding.
    func fieldBox(invalid: Bool = false, focused: Bool = false, onTap: (() -> Void)? = nil) -> some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
        let border = invalid ? Theme.Colors.error : focused ? Theme.Colors.ink : Theme.Colors.hairline
        // The web's outline sits 1px outside the border, so the ring's corners are that much rounder.
        let ringInset = Theme.Size.focusRing + Theme.Size.hairline
        return font(Theme.Fonts.callout)
            .foregroundStyle(Theme.Colors.ink)
            .padding(.leading, Theme.Spacing.l)
            .padding(.trailing, Theme.Spacing.xs)
            .frame(minHeight: Theme.Size.field)
            .background {
                if let onTap {
                    shape.fill(Theme.Colors.surface).contentShape(shape).onTapGesture(perform: onTap)
                } else {
                    shape.fill(Theme.Colors.surface)
                }
            }
            .overlay { shape.strokeBorder(border, lineWidth: Theme.Size.hairline) }
            .background {
                if focused {
                    RoundedRectangle(cornerRadius: Theme.Radius.control + ringInset, style: .continuous)
                        .strokeBorder(Theme.Colors.focusRing, lineWidth: Theme.Size.focusRing)
                        .padding(-ringInset)
                }
            }
    }
}

#Preview {
    @Previewable @State var name = "Alex Rivera"
    @Previewable @State var password = ""
    @Previewable @FocusState var focus: Int?
    VStack(spacing: Theme.Spacing.l) {
        FormErrorBanner("That email and password don't match.")
        FormField("Name", error: nil, focus: $focus, equals: 0) {
            TextField("Name", text: $name, prompt: .prompt("Your name")).focused($focus, equals: 0)
        }
        FormField("Email", error: "Enter a valid email address.", focus: $focus, equals: 1) {
            TextField("Email", text: .constant("alex@"), prompt: .prompt("you@example.com")).focused($focus, equals: 1)
        }
        FormField("Password", error: nil, focus: $focus, equals: 2) {
            PasswordField(label: "Password", prompt: "At least 8 characters", text: $password,
                          contentType: .newPassword, focus: $focus, field: 2)
        } accessory: {
            Button("Forgot password?") {}.buttonStyle(.text)
        }
    }
    .padding(Theme.Spacing.xl)
    .frame(maxHeight: .infinity)
    .background(Theme.Colors.background)
}
