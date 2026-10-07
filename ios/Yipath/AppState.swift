import SwiftUI

/// Where a screen's data stands. A screen switches on this to decide what to draw.
enum LoadState<Value> {
    case idle
    case loading
    case loaded(Value)
    case failed(String)
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
    private(set) var readings: [Period: LoadState<Reading>] = [.today: .idle, .week: .idle]
    /// Shown on the onboarding screen after the app had to sign the user out.
    var notice: String?

    private var loadedOn: [Period: String] = [:]   // which day each loaded reading belongs to
    private let api: APIClient

    init(api: APIClient = .fromBundle()) {
        self.api = api
        token = TokenStore.load()
        profile = ProfileStore.load()
        // A token without a profile (or the reverse) is unusable; start clean.
        if token == nil || profile == nil { token = nil; profile = nil }
    }

    var isOnboarded: Bool { token != nil && profile != nil }

    // MARK: Account

    func onboard(_ profile: Profile) async throws {
        let token = try await api.createProfile(profile)
        TokenStore.save(token)
        ProfileStore.save(profile)
        self.token = token
        self.profile = profile
        notice = nil
        resetReadings()
    }

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
    }

    /// Forgets the user on this device. (Their server-side record is left in place for now.)
    func signOut(message: String? = nil) {
        TokenStore.delete()
        ProfileStore.delete()
        token = nil
        profile = nil
        notice = message
        resetReadings()
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
    /// Developer shortcut (launch argument `-yipath-demo`): skip onboarding with a sample profile.
    func demoOnboard() async {
        var parts = DateComponents(year: 2000, month: 1, day: 1)
        parts.calendar = Calendar(identifier: .gregorian)
        let date = parts.date ?? Date()
        try? await onboard(Profile(birthDate: date, birthHour: 12, birthMinute: 0, mbti: "ENFP"))
    }
    #endif
}
