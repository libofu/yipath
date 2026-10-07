import SwiftUI

/// First-run screen: a few questions, then "起盘" (cast the chart).
struct OnboardingView: View {
    @Environment(AppState.self) private var appState
    @State private var draft = ProfileDraft()
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                // Header block with the name and the promise.
                Section {
                    VStack(spacing: 10) {
                        Text("易行")
                            .songti(48, relativeTo: .largeTitle, weight: .bold)
                            .foregroundStyle(Palette.ink)
                        Text("把决定交给先生，把心力留给要紧的事。")
                            .songti(15, relativeTo: .subheadline)
                            .foregroundStyle(Palette.inkSoft)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .listRowBackground(Color.clear)
                }

                if let notice = appState.notice {
                    Section { Text(notice).foregroundStyle(Palette.seal) }
                        .listRowBackground(Palette.card)
                }

                ProfileFormFields(draft: $draft)

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if isSubmitting { ProgressView().tint(.white) } else { Text("起盘").songti(18, weight: .bold) }
                            Spacer()
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isSubmitting)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                    .accessibilityIdentifier("submit")

                    if let errorMessage {
                        Text(errorMessage).font(.footnote).foregroundStyle(Palette.seal)
                    }
                } footer: {
                    Text(Copy.disclaimer)
                }
            }
            .scrollContentBackground(.hidden)   // let our paper color show through the Form
            .background(Palette.paper.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func submit() async {
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            try await appState.onboard(draft.toProfile())
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? "出了点问题，请稍后再试。"
        }
    }
}
