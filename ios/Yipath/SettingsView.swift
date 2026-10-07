import SwiftUI

/// The "我的" tab: shows the profile, lets the user edit it, and holds the fine print.
struct SettingsView: View {
    @Environment(AppState.self) private var appState
    @Environment(SubscriptionManager.self) private var subscriptions
    @State private var showingEditor = false
    @State private var showingSignOutConfirm = false
    @State private var showingDeleteConfirm = false
    @State private var showingManageSubscriptions = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                if let profile = appState.profile {
                    Section("我的八字资料") {
                        row("出生日期", Self.dateText(profile.birthDate))
                        row("出生时间", Self.timeText(profile))
                        row("MBTI", profile.mbti ?? "未填写")
                        Button("修改资料") { showingEditor = true }
                            .accessibilityIdentifier("editProfile")
                    }
                    .listRowBackground(Palette.card)
                }

                Section("订阅") {
                    row("状态", Self.subscriptionText(appState.entitlement))
                    if appState.entitlement?.status == .subscribed {
                        Button("管理订阅") { showingManageSubscriptions = true }
                    } else {
                        Button("订阅") { appState.showPaywall = true }
                            .accessibilityIdentifier("settingsSubscribe")
                    }
                    Button("恢复购买") { Task { await subscriptions.restore() } }
                    if let message = subscriptions.message {
                        Text(message).font(.footnote).foregroundStyle(Palette.inkSoft)
                    }
                }
                .listRowBackground(Palette.card)

                Section("说明") {
                    Text(Copy.disclaimer).font(.footnote).foregroundStyle(Palette.inkSoft)
                    Text("字体：思源宋体（Noto Serif SC），SIL Open Font License 1.1。").font(.footnote).foregroundStyle(Palette.inkSoft)
                    row("版本", Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "-")
                }
                .listRowBackground(Palette.card)

                Section {
                    Button("退出登录") { showingSignOutConfirm = true }
                    Button("删除账号", role: .destructive) { showingDeleteConfirm = true }
                        .accessibilityIdentifier("deleteAccount")
                    if let errorMessage {
                        Text(errorMessage).font(.footnote).foregroundStyle(Palette.seal)
                    }
                } header: {
                    Text("账号")
                } footer: {
                    Text("删除账号会永久清除你在服务器上的资料与记录，无法恢复。订阅需在 Apple ID 的订阅设置中另行取消。")
                }
                .listRowBackground(Palette.card)
            }
            .scrollContentBackground(.hidden)
            .background(Palette.paper.ignoresSafeArea())
            .navigationTitle("我的")
            .sheet(isPresented: $showingEditor) { ProfileEditor() }
            .manageSubscriptionsSheet(isPresented: $showingManageSubscriptions)
            .confirmationDialog("确定退出登录吗？", isPresented: $showingSignOutConfirm, titleVisibility: .visible) {
                Button("退出登录", role: .destructive) { appState.signOut() }
            }
            .confirmationDialog("确定永久删除账号吗？", isPresented: $showingDeleteConfirm, titleVisibility: .visible) {
                Button("删除账号", role: .destructive) {
                    Task {
                        do { try await appState.deleteAccount() }
                        catch { errorMessage = (error as? LocalizedError)?.errorDescription ?? "删除失败，请稍后再试。" }
                    }
                }
            } message: {
                Text("你的出生资料与所有记录将从服务器清除，无法恢复。")
            }
        }
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(value).foregroundStyle(Palette.inkSoft)
        }
    }

    static func subscriptionText(_ e: Entitlement?) -> String {
        guard let e else { return "—" }
        switch e.status {
        case .trial: return "试用中，至 \(PaywallView.dayText(e.trialEndsAt))"
        case .subscribed: return "已订阅，至 \(PaywallView.dayText(e.expiresAt ?? e.trialEndsAt))"
        case .expired: return "未订阅"
        }
    }

    static func dateText(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.dateFormat = "yyyy年M月d日"
        return f.string(from: date)
    }

    static func timeText(_ profile: Profile) -> String {
        guard let hour = profile.birthHour else { return "未填写" }
        return String(format: "%02d:%02d", hour, profile.birthMinute)
    }
}

/// The edit sheet: the same fields as onboarding, pre-filled.
struct ProfileEditor: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ProfileDraft()   // replaced with the saved profile in .onAppear
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                ProfileFormFields(draft: $draft)
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(Palette.seal) }
                }
            }
            .navigationTitle("修改资料")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { Task { await save() } }.disabled(isSaving)
                }
            }
            .onAppear {
                if let profile = appState.profile { draft = ProfileDraft(from: profile) }
            }
        }
    }

    private func save() async {
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            try await appState.updateProfile(draft.toProfile())
            dismiss()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? "保存失败，请稍后再试。"
        }
    }
}
