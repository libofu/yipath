import SwiftUI

@main
struct YipathApp: App {
    // `@State` keeps these objects alive for the whole life of the app.
    @State private var appState: AppState
    @State private var subscriptions: SubscriptionManager

    init() {
        let state = AppState()
        _appState = State(initialValue: state)
        _subscriptions = State(initialValue: SubscriptionManager(appState: state))
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appState)   // makes these available to every view below
                .environment(subscriptions)
                .tint(Palette.seal)
        }
    }
}

/// Decides which world to show: sign-in / onboarding for a new user, the tabs for a returning one.
struct RootView: View {
    @Environment(AppState.self) private var appState
    @Environment(SubscriptionManager.self) private var subscriptions
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        // `@Bindable` lets us pass a two-way binding to a property of an @Observable object.
        @Bindable var state = appState

        ZStack {
            Palette.paper.ignoresSafeArea()
            if appState.isOnboarded {
                MainTabView()
            } else {
                OnboardingView()
            }
        }
        .sheet(isPresented: $state.showPaywall) { PaywallView() }
        // Runs when the user becomes signed in/out, and again each time the app comes to the front:
        // refresh what the server says about access, and pass any renewal on to the server.
        .task(id: "\(appState.stage)-\(scenePhase)") {
            if appState.stage == .needsProfile { await appState.restoreProfileIfPossible() }
            guard appState.isOnboarded, scenePhase == .active else { return }
            subscriptions.start()
            await appState.refreshEntitlement()
            await subscriptions.syncCurrentEntitlements()
        }
        #if DEBUG
        .task {
            if CommandLine.arguments.contains("-yipath-demo"), !appState.isOnboarded {
                await appState.demoOnboard()
            }
        }
        #endif
    }
}

struct MainTabView: View {
    @State private var selection = MainTabView.initialTab

    var body: some View {
        TabView(selection: $selection) {
            ReadingScreen(period: .today)
                .tabItem { Label("今日", systemImage: "sun.max") }
                .tag(0)
            ReadingScreen(period: .week)
                .tabItem { Label("本周", systemImage: "calendar") }
                .tag(1)
            SettingsView()
                .tabItem { Label("我的", systemImage: "person") }
                .tag(2)
        }
    }

    /// Developer shortcut (launch arguments `-yipath-tab 1`): open on another tab.
    private static var initialTab: Int {
        #if DEBUG
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "-yipath-tab"), i + 1 < args.count, let n = Int(args[i + 1]) { return n }
        #endif
        return 0
    }
}
