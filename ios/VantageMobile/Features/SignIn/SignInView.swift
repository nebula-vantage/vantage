import SwiftUI
import VantageKit

/// An account exists and you're signed out: sign in with the account's email filled in.
struct SignInView: View {
    let accounts: AccountStore

    private enum Field: Hashable { case email, password }
    /// What to scroll into view after a failed attempt: the email field with its message, or the
    /// banner above the fields.
    private enum Anchor: Hashable { case banner, email }

    @State private var email: String
    @State private var password = ""
    @State private var emailError: String?
    @State private var formError: String?
    @State private var busy = false
    /// Counts finished attempts. `busy` alone can't say when one ends: while locked out it fails
    /// before the busy state is ever drawn, so it never visibly changes.
    @State private var attempts = 0
    @State private var confirmingReset = false
    @FocusState private var focus: Field?
    /// Scrolled to the top, so its message stays above the keyboard, as on Create account.
    @State private var reveal: Anchor?

    init(accounts: AccountStore) {
        self.accounts = accounts
        var email = accounts.profile?.email ?? ""
        #if DEBUG
        // UI check hook: `-email <value>` starts with another email, so `-email alex@ -password
        // pickleball -submitForm` shows the email error.
        if let value = LaunchHooks.takeValue(after: "-email") { email = value }
        #endif
        _email = State(initialValue: email)
    }

    private var canSubmit: Bool {
        !busy && !email.trimmingCharacters(in: .whitespaces).isEmpty && !password.isEmpty
    }

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
        .onChange(of: email) { formError = nil; emailError = nil }
        .onChange(of: password) { formError = nil }
        // As on the web, a failed sign-in puts the keyboard back in Password so you can try again:
        // once the fields are enabled again, as a disabled field can't take focus. The banner
        // saying why scrolls into view above it.
        .onChange(of: attempts) {
            guard formError != nil else { return }
            focus = .password
            reveal = .banner
        }
        #if DEBUG
        .task { submitForUICheck() }
        #endif
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
            FormHeader(eyebrow: "Welcome back", title: "Sign in to Vantage",
                       message: accounts.profile.map { "Pick up where you left off, \($0.firstName)." }
                           ?? "Pick up where you left off.")
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                if let formError { FormErrorBanner(formError).id(Anchor.banner) }
                FormField("Email", error: emailError, focus: $focus, equals: .email) {
                    TextField("Email", text: $email, prompt: .prompt("you@example.com"))
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .focused($focus, equals: .email)
                        .onSubmit { focus = .password }
                }
                .id(Anchor.email)
                FormField("Password", error: nil, focus: $focus, equals: .password) {
                    PasswordField(label: "Password", text: $password, contentType: .password,
                                  focus: $focus, field: .password)
                        .submitLabel(.go)
                        .onSubmit(submit)
                } accessory: {
                    Button("Forgot password?") { confirmingReset = true }
                        .buttonStyle(.text)
                        // A local account can't be recovered, so this resets it and keeps the games.
                        .confirmationDialog("Reset your account?", isPresented: $confirmingReset,
                                            titleVisibility: .visible) {
                            Button("Reset account", role: .destructive, action: resetAccount)
                        } message: {
                            Text("""
                                This removes the account from this iPhone so you can create a new one. \
                                Your games stay on this iPhone.
                                """)
                        }
                }
            }
            .disabled(busy)
            Button(busy ? "Signing in…" : "Sign in", action: submit)
                .buttonStyle(.primary)
                .disabled(!canSubmit)
        }
    }

    private func submit() {
        guard canSubmit else { return }
        formError = nil
        // As on the web, a malformed email is sent nowhere, so it can't count as a wrong attempt.
        if let message = FormFeedback.error({ try AccountValidation.email(email) }) {
            emailError = message
            focus = .email
            reveal = .email
            FormFeedback.announce(message)
            return
        }
        focus = nil
        busy = true
        Task {
            defer {
                busy = false
                attempts += 1
            }
            do {
                try await accounts.signIn(email: email, password: password)
            } catch {
                formError = error.localizedDescription
                FormFeedback.announce(formError)
            }
        }
    }

    private func resetAccount() {
        do {
            try accounts.resetAccount()
        } catch {
            formError = error.localizedDescription
            reveal = .banner
            FormFeedback.announce(formError)
        }
    }

    #if DEBUG
    /// UI check hooks: `-password <value>` fills in the password and `-submitForm` signs in on
    /// launch, so `-seedSignedOut -password wrong-password -submitForm` shows the error state.
    /// `-forgotPassword` opens the reset confirmation. Each fires once per launch.
    private func submitForUICheck() {
        if let value = LaunchHooks.takeValue(after: "-password") { password = value }
        if LaunchHooks.take("-submitForm") { submit() }
        if LaunchHooks.take("-forgotPassword") { confirmingReset = true }
    }
    #endif
}
