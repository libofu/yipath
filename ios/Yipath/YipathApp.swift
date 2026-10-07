import SwiftUI

@main
struct YipathApp: App {
    // `@State` keeps the object alive for the whole life of the app.
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appState)   // makes `appState` available to every view below
                .tint(Palette.seal)
        }
    }
}

/// Decides which world to show: onboarding for a new user, the tabs for a returning one.
struct RootView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        ZStack {
            Palette.paper.ignoresSafeArea()
            if appState.isOnboarded {
                MainTabView()
            } else {
                OnboardingView()
            }
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
