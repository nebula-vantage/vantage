import SwiftUI
import VantageKit

/// First launch, or after a reset: create the one account on this iPhone.
struct CreateAccountView: View {
    let accounts: AccountStore

    private enum Field: Hashable, CaseIterable { case name, email, password }
    /// What to scroll into view: a field with its error, or the banner above the fields.
    private enum Anchor: Hashable { case banner, field(Field) }

    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var errors: [Field: String] = [:]
    @State private var formError: String?
    @State private var busy = false
    @FocusState private var focus: Field?
    /// Scrolled to the top, so its message stays above the keyboard, as on Sign in.
    @State private var reveal: Anchor?

    var body: some View {
        AuthScreen {
            ScrollViewReader { proxy in
                form
                    .onChange(of: reveal) { _, anchor in
                        guard let anchor else { return }
                        reveal = nil
                        // On the next turn, once the keyboard has made room to scroll that far.
                        Task { withAnimation { proxy.scrollTo(anchor, anchor: .top) } }
                    }
            }
        }
        .onChange(of: name) { errors[.name] = nil }
        .onChange(of: email) { errors[.email] = nil }
        .onChange(of: password) { errors[.password] = nil }
        // A field error from `createAccount` moves the keyboard there once the fields are enabled
        // again, as a disabled field can't take focus. An error for the whole form (it couldn't be
        // saved) scrolls its banner into view instead.
        .onChange(of: busy) { _, busy in
            guard !busy else { return }
            if let field = Field.allCases.first(where: { errors[$0] != nil }) {
                focus = field
                reveal = .field(field)
            } else if formError != nil {
                reveal = .banner
            }
        }
        #if DEBUG
        .task { submitForUICheck() }
        #endif
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
            FormHeader(eyebrow: "Get started", title: "Create your account",
                       message: "Your games, replays and coaching, in one place.")
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                if let formError { FormErrorBanner(formError).id(Anchor.banner) }
                FormField("Name", error: errors[.name], focus: $focus, equals: .name) {
                    TextField("Name", text: $name, prompt: .prompt("Your name"))
                        .textContentType(.name)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .focused($focus, equals: .name)
                        .onSubmit { focus = .email }
                }
                .id(Anchor.field(.name))
                FormField("Email", error: errors[.email], focus: $focus, equals: .email) {
                    TextField("Email", text: $email, prompt: .prompt("you@example.com"))
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .focused($focus, equals: .email)
                        .onSubmit { focus = .password }
                }
                .id(Anchor.field(.email))
                FormField("Password", error: errors[.password], focus: $focus, equals: .password) {
                    PasswordField(label: "Password", prompt: "At least 8 characters", text: $password,
                                  contentType: .newPassword, focus: $focus, field: .password)
                        .submitLabel(.join)
                        .onSubmit(submit)
                }
                .id(Anchor.field(.password))
            }
            .disabled(busy)
            Button(busy ? "Creating account…" : "Create account", action: submit)
                .buttonStyle(.primary)
                .disabled(busy)
        }
    }

    private func submit() {
        guard !busy else { return }
        formError = nil
        let checks: [(Field, String?)] = [
            (.name, FormFeedback.error { try AccountValidation.name(name) }),
            (.email, FormFeedback.error { try AccountValidation.email(email) }),
            (.password, FormFeedback.error { try AccountValidation.password(password) }),
        ]
        for (field, error) in checks { errors[field] = error }
        // As on the web, the keyboard comes up in the first field to fix.
        if let invalid = checks.first(where: { $0.1 != nil }) {
            focus = invalid.0
            reveal = .field(invalid.0)
            FormFeedback.announce(invalid.1)
            return
        }
        focus = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                try await accounts.createAccount(name: name, email: email, password: password)
            } catch let error as AccountError {
                switch error {
                case .invalidName: errors[.name] = error.message
                case .invalidEmail: errors[.email] = error.message
                case .invalidPassword: errors[.password] = error.message
                default: formError = error.message
                }
                FormFeedback.announce(error.message)
            } catch {
                formError = error.localizedDescription
                FormFeedback.announce(formError)
            }
        }
    }

    #if DEBUG
    /// UI check hook: `-submitForm` submits on launch, once, so an empty form shows its errors.
    private func submitForUICheck() {
        if LaunchHooks.take("-submitForm") { submit() }
    }
    #endif
}
