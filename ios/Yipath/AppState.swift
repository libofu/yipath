import SwiftUI

/// Where a screen's data stands. A screen switches on this to decide what to draw.
enum LoadState<Value> {
    case idle
    case loading
    case loaded(Value)
    case failed(String)
}

/// Which part of the app the user should be in.
enum Stage {
    case signedOut      // no login yet: show "Sign in with Apple"
    case needsProfile   // signed in, but hasn't entered birth details
    case ready          // show the tabs
}

/// The single place that holds "who is signed in" and "what we've loaded".
///
/// `@Observable` (iOS 17) makes SwiftUI redraw any view that read a property
/// when that property changes. `@MainActor` keeps all changes on the main thread,
/// which SwiftUI requires.
@MainActor
@Observable
final class AppState {
    private(set) var token: String?
    private(set) var profile: Profile?
    private(set) var entitlement: Entitlement?
    private(set) var readings: [Period: LoadState<Reading>] = [.today: .idle, .week: .idle]
    /// Shown on the sign-in screen after the app had to sign the user out.
    var notice: String?
    /// True while the subscription sheet should be on screen.
    var showPaywall = false

    private var loadedOn: [Period: String] = [:]   // which day each loaded reading belongs to
    private let api: APIClient
    private let reminders: ReminderScheduler

    /// iOS keeps Keychain items after an app is deleted, but removes UserDefaults. So this flag
    /// being absent means "fresh install": any token still in the Keychain is left over from a
    /// previous install and must not silently log the new install in.
    static let launchedBeforeKey = "yipath.launchedBefore"

    init(api: APIClient = .fromBundle(), reminders: ReminderScheduler = ReminderScheduler()) {
        self.api = api
        self.reminders = reminders
        if !UserDefaults.standard.bool(forKey: Self.launchedBeforeKey) {
            TokenStore.delete()
            UserDefaults.standard.set(true, forKey: Self.launchedBeforeKey)
        }
        token = TokenStore.load()
        profile = token == nil ? nil : ProfileStore.load()
        if token == nil { ProfileStore.delete() }   // a profile without a login is stale
    }

    var stage: Stage {
        if token == nil { return .signedOut }
        return profile == nil ? .needsProfile : .ready
    }

    var isOnboarded: Bool { stage == .ready }

    // MARK: Account

    /// Finishes "Sign in with Apple": swaps Apple's identity token for our login token, and
    /// restores the saved profile if this Apple ID has used the app before.
    func signIn(identityToken: String, nonce: String) async throws {
        let session = try await api.signInWithApple(identityToken: identityToken, nonce: nonce)
        TokenStore.save(session.token)
        token = session.token
        notice = nil
        resetReadings()
        if session.hasProfile, let saved = try? await api.profile(token: session.token) {
            ProfileStore.save(saved)
            profile = saved
        } else {
            ProfileStore.delete()
            profile = nil
        }
        await refreshEntitlement()
    }

    /// For a login that has no profile on this device (e.g. the app was closed before the form was
    /// saved): ask the server whether one exists. Without it the user just sees the form.
    func restoreProfileIfPossible() async {
        guard stage == .needsProfile, let token else { return }
        do {
            if let saved = try await api.profile(token: token) {
                ProfileStore.save(saved)
                profile = saved
                await refreshEntitlement()
            }
        } catch APIError.unauthorized {
            signOut(message: APIError.unauthorized.errorDescription)
        } catch {
            // offline or server trouble: stay on the form
        }
    }

    /// Saves the profile on the server and here. Used by onboarding (first save) and by editing.
    func updateProfile(_ newProfile: Profile) async throws {
        guard let token else { throw APIError.unauthorized }
        do {
            try await api.updateProfile(newProfile, token: token)
        } catch APIError.unauthorized {
            signOut(message: APIError.unauthorized.errorDescription)
            throw APIError.unauthorized
        }
        ProfileStore.save(newProfile)
        profile = newProfile
        resetReadings()   // the old readings were written for the old profile
        await refreshEntitlement()
    }

    /// Forgets the user on this device only (the server keeps the account).
    func signOut(message: String? = nil) {
        reminders.cancel()   // a signed-out phone should not keep nudging about readings
        TokenStore.delete()
        ProfileStore.delete()
        token = nil
        profile = nil
        entitlement = nil
        showPaywall = false
        notice = message
        resetReadings()
    }

    /// Erases the account on the server, then forgets it here. App Store rules require
    /// that an app which creates accounts lets the user delete them.
    func deleteAccount() async throws {
        guard let token else { return }
        do {
            try await api.deleteAccount(token: token)
        } catch APIError.unauthorized {
            // already gone on the server; fall through and clear the device
        }
        signOut()
    }

    // MARK: Subscription

    func refreshEntitlement() async {
        guard let token else { return }
        do {
            entitlement = try await api.subscriptionStatus(token: token)
        } catch APIError.unauthorized {
            signOut(message: APIError.unauthorized.errorDescription)
        } catch {
            // keep whatever we knew; the reading request will tell us if access ended
        }
    }

    /// Gives the server a signed transaction from StoreKit. If it checks out, unlocks the app.
    func submitTransaction(_ signedTransaction: String) async throws {
        guard let token else { throw APIError.unauthorized }
        let updated = try await api.verifyTransaction(signedTransaction, token: token)
        entitlement = updated
        if updated.isActive {
            showPaywall = false
            // readings that failed with "subscribe first" can be fetched now
            for (period, state) in readings { if case .failed = state { readings[period] = .idle } }
        }
    }

    // MARK: Readings

    /// Loads today's or this week's reading. Does nothing if we already have it for today,
    /// unless `force` is true (pull to refresh).
    func load(_ period: Period, force: Bool = false) async {
        guard let token else { return }
        let dayKey = DayFormat.formatter.string(from: Date())
        let current = readings[period] ?? .idle

        if case .loading = current { return }
        if !force, case .loaded = current, loadedOn[period] == dayKey { return }

        // While refreshing, keep showing what we have rather than flashing a spinner.
        var hadContent = false
        if case .loaded = current { hadContent = true } else { readings[period] = .loading }

        do {
            let reading = try await api.reading(period, on: Date(), token: token)
            readings[period] = .loaded(reading)
            loadedOn[period] = dayKey
        } catch APIError.unauthorized {
            signOut(message: APIError.unauthorized.errorDescription)
        } catch APIError.paymentRequired {
            // Trial over and not subscribed: show the paywall instead of the reading.
            readings[period] = .failed(APIError.paymentRequired.errorDescription ?? "")
            showPaywall = true
            await refreshEntitlement()
        } catch {
            if !hadContent {
                readings[period] = .failed((error as? LocalizedError)?.errorDescription ?? "出了点问题，请稍后再试。")
            }
        }
    }

    private func resetReadings() {
        readings = [.today: .idle, .week: .idle]
        loadedOn = [:]
    }

    #if DEBUG
    /// Developer shortcut for the simulator: an account with no Apple sign-in (the backend only
    /// allows this outside production), so the app can be tried without an Apple ID.
    func onboardAnonymously(_ profile: Profile) async throws {
        let token = try await api.createProfile(profile)
        TokenStore.save(token)
        ProfileStore.save(profile)
        self.token = token
        self.profile = profile
        notice = nil
        resetReadings()
        await refreshEntitlement()
    }

    /// Launch argument `-yipath-demo`: skip sign-in with a sample profile.
    func demoOnboard() async {
        var parts = DateComponents(year: 2000, month: 1, day: 1)
        parts.calendar = Calendar(identifier: .gregorian)
        let date = parts.date ?? Date()
        try? await onboardAnonymously(Profile(birthDate: date, birthHour: 12, birthMinute: 0, mbti: "ENFP"))
    }
    #endif
}
