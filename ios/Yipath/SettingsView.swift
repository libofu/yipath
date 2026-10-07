import SwiftUI

/// The "我的" tab: shows the profile, lets the user edit it, and holds the fine print.
struct SettingsView: View {
    @Environment(AppState.self) private var appState
    @State private var showingEditor = false
    @State private var showingSignOutConfirm = false

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

                Section("说明") {
                    Text(Copy.disclaimer).font(.footnote).foregroundStyle(Palette.inkSoft)
                    row("版本", Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "-")
                }
                .listRowBackground(Palette.card)

                Section {
                    Button("清除本机数据并重新起盘", role: .destructive) { showingSignOutConfirm = true }
                }
                .listRowBackground(Palette.card)
            }
            .scrollContentBackground(.hidden)
            .background(Palette.paper.ignoresSafeArea())
            .navigationTitle("我的")
            .sheet(isPresented: $showingEditor) { ProfileEditor() }
            .confirmationDialog("确定清除本机数据吗？", isPresented: $showingSignOutConfirm, titleVisibility: .visible) {
                Button("清除并重新起盘", role: .destructive) { appState.signOut() }
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
