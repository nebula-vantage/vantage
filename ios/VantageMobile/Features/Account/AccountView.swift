import SwiftUI
import VantageKit

/// Your profile, your password, where your games are saved, and Sign out. Opens as a sheet from
/// the initials button in the Games header.
struct AccountView: View {
    let accounts: AccountStore
    /// Called once Sign out has ended the session on disk (`AccountStore.endSession()`). The Games
    /// screen closes this sheet first and shows Sign in once it's gone.
    let signOut: () -> Void

    private enum Field: Hashable { case name, email, currentPassword, newPassword }
    /// What to scroll into view above the keyboard: a field with its error under it, or the
    /// messages under a section's button.
    private enum Anchor: Hashable {
        case field(Field), profileStatus, passwordStatus, signOut

        /// A field goes to the top, so its error shows beneath it; messages go to the bottom, so
        /// their button stays in view above them.
        var edge: UnitPoint {
            if case .field = self { return .top }
            return .bottom
        }
    }

    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var name: String
    @State private var email: String
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var errors: [Field: String] = [:]
    @State private var profileError: String?
    @State private var passwordError: String?
    /// Name and email as last saved; "Profile saved." shows until either field changes.
    @State private var savedProfile: [String]?
    /// "Password changed." shows until either password field is typed in again.
    @State private var passwordChanged = false
    @State private var changingPassword = false
    /// Counts finished password changes. `changingPassword` alone can't say when one ends: while
    /// locked out it fails before the busy state is ever drawn, so it never visibly changes.
    @State private var passwordChangesFinished = 0
    /// Where the keyboard was when Change password started; it goes back there afterwards.
    @State private var focusBeforeChange: Field?
    @State private var signOutError: String?
    @FocusState private var focus: Field?
    @State private var reveal: Anchor?

    init(accounts: AccountStore, signOut: @escaping () -> Void) {
        self.accounts = accounts
        self.signOut = signOut
        _name = State(initialValue: accounts.profile?.name ?? "")
        _email = State(initialValue: accounts.profile?.email ?? "")
    }

    /// Compares the values as they'd be stored (trimmed, the email lowercased), as the web does, so
    /// a trailing space doesn't count as a change. An invalid name counts, so its error can show.
    private var profileChanged: Bool {
        ((try? AccountValidation.name(name)) ?? name) != accounts.profile?.name
            || AccountValidation.normalizedEmail(email) != accounts.profile?.email
    }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Spacing.xl) {
                        header
                        profileSection
                        passwordSection
                        storageSection
                        signOutSection
                    }
                    .padding(.horizontal, Theme.Spacing.l)
                    .padding(.vertical, Theme.Spacing.l)
                }
                .scrollDismissesKeyboard(.interactively)
                #if DEBUG
                .debugScrollAnchor("account")
                #endif
                .onChange(of: reveal) { _, anchor in
                    guard let anchor else { return }
                    reveal = nil
                    // On the next turn, once the keyboard has made room to scroll that far.
                    Task { withAnimation { proxy.scrollTo(anchor, anchor: anchor.edge) } }
                }
            }
            .background(Theme.Colors.background)
            .navigationTitle("Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .disabled(changingPassword)
                }
            }
        }
        // A password change can't be left halfway: Done, Sign out and swiping down wait for it.
        .interactiveDismissDisabled(changingPassword)
        .onChange(of: name) { errors[.name] = nil; profileError = nil }
        .onChange(of: email) { errors[.email] = nil; profileError = nil }
        .onChange(of: currentPassword) { errors[.currentPassword] = nil; passwordError = nil }
        .onChange(of: newPassword) { errors[.newPassword] = nil; passwordError = nil }
        // Once the password fields are enabled again (a disabled field can't take focus), the
        // keyboard goes to the field with an error, or back where it was, and the outcome scrolls
        // into view above it.
        .onChange(of: passwordChangesFinished) {
            if let field = [Field.currentPassword, .newPassword].first(where: { errors[$0] != nil }) {
                focus = field
                reveal = .field(field)
            } else {
                focus = focusBeforeChange
                reveal = .passwordStatus
            }
            focusBeforeChange = nil
        }
    }

    private var header: some View {
        // The avatar sits beside the name and email; at accessibility sizes it moves above them so
        // they keep the full width. Neither is ever cut off: a long name or email wraps.
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Theme.Spacing.m))
            : AnyLayout(HStackLayout(alignment: .center, spacing: Theme.Spacing.l))
        return layout {
            InitialsAvatar(initials: accounts.profile?.initials ?? "?", large: true)
                // Stops growing before it crowds out the name.
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Theme.Spacing.xxs) {
                Text(accounts.profile?.name ?? "")
                    .font(Theme.Fonts.heading)
                    .tracking(Theme.Fonts.headingTracking)
                    .foregroundStyle(Theme.Colors.ink)
                // An email too long for one line breaks after the @ (a zero-width space) rather than
                // mid-domain.
                Text((accounts.profile?.email ?? "").replacingOccurrences(of: "@", with: "@\u{200B}"))
                    .font(Theme.Fonts.callout)
                    .foregroundStyle(Theme.Colors.inkSecondary)
                    .accessibilityLabel(accounts.profile?.email ?? "")
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }

    private var profileSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.l) {
            sectionTitle("Profile")
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
                    .submitLabel(.done)
                    .focused($focus, equals: .email)
                    .onSubmit(saveProfile)
            }
            .id(Anchor.field(.email))
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                Button("Save changes", action: saveProfile)
                    .buttonStyle(.secondary)
                    .disabled(!profileChanged)
                if let profileError { FormMessage(profileError) }
                if savedProfile == [name, email] { FormMessage("Profile saved.", color: Theme.Colors.positive) }
            }
            .id(Anchor.profileStatus)
        }
        .card()
    }

    private var passwordSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.l) {
            sectionTitle("Password")
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                FormField("Current password", error: errors[.currentPassword], focus: $focus,
                          equals: .currentPassword) {
                    PasswordField(label: "Current password", text: $currentPassword, contentType: .password,
                                  focus: $focus, field: .currentPassword)
                        .submitLabel(.next)
                        .onSubmit { focus = .newPassword }
                }
                .id(Anchor.field(.currentPassword))
                FormField("New password", error: errors[.newPassword], focus: $focus, equals: .newPassword) {
                    PasswordField(label: "New password", prompt: "At least 8 characters", text: $newPassword,
                                  contentType: .newPassword, focus: $focus, field: .newPassword)
                        .submitLabel(.done)
                        .onSubmit(changePassword)
                }
                .id(Anchor.field(.newPassword))
            }
            .disabled(changingPassword)
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                Button("Change password", action: changePassword)
                    .buttonStyle(.secondary)
                    .disabled(changingPassword || currentPassword.isEmpty || newPassword.isEmpty)
                if let passwordError { FormMessage(passwordError) }
                if passwordChanged && currentPassword.isEmpty && newPassword.isEmpty {
                    FormMessage("Password changed.", color: Theme.Colors.positive)
                }
            }
            .id(Anchor.passwordStatus)
        }
        .card()
    }

    private var storageSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            sectionTitle("Where your games live")
            StatusNote("Your account and games are saved on this iPhone. Videos are analyzed on the device.")
        }
        .card()
    }

    private var signOutSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Button("Sign out", action: endSession)
                .buttonStyle(.secondary)
                .disabled(changingPassword)
            if let signOutError { FormMessage(signOutError) }
        }
        .id(Anchor.signOut)
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title)
            .font(Theme.Fonts.title)
            .foregroundStyle(Theme.Colors.ink)
            .accessibilityAddTraits(.isHeader)
    }

    private func saveProfile() {
        guard profileChanged else { return }
        profileError = nil
        let checks: [(Field, String?)] = [
            (.name, FormFeedback.error { try AccountValidation.name(name) }),
            (.email, FormFeedback.error { try AccountValidation.email(email) }),
        ]
        for (field, error) in checks { errors[field] = error }
        if let invalid = checks.first(where: { $0.1 != nil }) {
            focus = invalid.0
            reveal = .field(invalid.0)
            FormFeedback.announce(invalid.1)
            return
        }
        do {
            try accounts.updateProfile(name: name, email: email)
            // Show the values as stored: trimmed, and the email lowercased.
            name = accounts.profile?.name ?? name
            email = accounts.profile?.email ?? email
            savedProfile = [name, email]
            focus = nil
            FormFeedback.announce("Profile saved.")
        } catch {
            profileError = error.localizedDescription
            FormFeedback.announce(profileError)
        }
        reveal = .profileStatus
    }

    private func changePassword() {
        guard !changingPassword, !currentPassword.isEmpty, !newPassword.isEmpty else { return }
        passwordError = nil
        passwordChanged = false
        errors[.currentPassword] = nil
        errors[.newPassword] = nil
        // The new password's length first, as the web page checks it before asking the server.
        if let message = FormFeedback.error({ try AccountValidation.password(newPassword) }) {
            errors[.newPassword] = message
            focus = .newPassword
            reveal = .field(.newPassword)
            FormFeedback.announce(message)
            return
        }
        // The password fields are locked while it runs; `onChange(of: passwordChangesFinished)`
        // puts the keyboard back.
        focusBeforeChange = focus
        focus = nil
        changingPassword = true
        Task {
            defer {
                changingPassword = false
                passwordChangesFinished += 1
            }
            do {
                try await accounts.changePassword(current: currentPassword, new: newPassword)
                currentPassword = ""
                newPassword = ""
                passwordChanged = true
                focusBeforeChange = nil
                FormFeedback.announce("Password changed.")
            } catch let error as AccountError {
                switch error {
                case .wrongCurrentPassword: errors[.currentPassword] = error.message
                case .invalidPassword: errors[.newPassword] = error.message
                // Including the lockout ("Too many attempts. Wait a minute and try again."), which
                // wrong current passwords share with sign-in.
                default: passwordError = error.message
                }
                FormFeedback.announce(error.message)
            } catch {
                passwordError = error.localizedDescription
                FormFeedback.announce(passwordError)
            }
        }
    }

    /// Ends the session on disk while the sheet is still open, so a failure can say so here; the
    /// Games screen then closes the sheet and shows Sign in.
    private func endSession() {
        signOutError = nil
        do {
            try accounts.endSession()
        } catch {
            signOutError = error.localizedDescription
            reveal = .signOut
            FormFeedback.announce(signOutError)
            return
        }
        signOut()
    }
}
