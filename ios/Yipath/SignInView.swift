import AuthenticationServices
import CryptoKit
import SwiftUI

/// The first screen for a new user: Sign in with Apple. Apple gives us a signed identity token;
/// the server verifies it and creates (or finds) the account. We ask for no name or email.
struct SignInView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.colorScheme) private var colorScheme
    @State private var nonce = ""
    @State private var isWorking = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            VStack(spacing: 12) {
                Text("易行")
                    .songti(56, relativeTo: .largeTitle, weight: .bold)
                    .foregroundStyle(Palette.ink)
                Text("把决定交给先生，把心力留给要紧的事。")
                    .songti(16, relativeTo: .subheadline)
                    .foregroundStyle(Palette.inkSoft)
                    .multilineTextAlignment(.center)
            }
            Spacer()

            if let notice = appState.notice {
                Text(notice).font(.footnote).foregroundStyle(Palette.seal).multilineTextAlignment(.center)
            }

            SignInWithAppleButton(.signIn) { request in
                // A fresh random nonce per attempt. Apple puts its hash in the token, and the
                // server checks it, so a captured token can't be replayed.
                nonce = Self.randomNonce()
                request.requestedScopes = []
                request.nonce = Self.sha256Hex(nonce)
            } onCompletion: { result in
                handle(result)
            }
            .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
            .frame(height: 52)
            .disabled(isWorking)
            .accessibilityIdentifier("appleSignIn")

            #if DEBUG
            Button("开发者：不登录，直接试用") { Task { await appState.demoOnboard() } }
                .font(.footnote)
                .accessibilityIdentifier("demoSignIn")
            #endif

            if let errorMessage {
                Text(errorMessage).font(.footnote).foregroundStyle(Palette.seal).multilineTextAlignment(.center)
            }
            Text(Copy.disclaimer)
                .font(.footnote)
                .foregroundStyle(Palette.inkSoft)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 24)
        .background(Palette.paper.ignoresSafeArea())
    }

    private func handle(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            // Closing the Apple sheet is not an error worth showing.
            if (error as? ASAuthorizationError)?.code != .canceled {
                errorMessage = "登录没有完成，请重试。"
            }
        case .success(let authorization):
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let data = credential.identityToken,
                  let token = String(data: data, encoding: .utf8) else {
                errorMessage = "登录没有完成，请重试。"
                return
            }
            let nonce = self.nonce
            isWorking = true
            errorMessage = nil
            Task {
                defer { isWorking = false }
                do {
                    try await appState.signIn(identityToken: token, nonce: nonce)
                } catch {
                    errorMessage = (error as? LocalizedError)?.errorDescription ?? "登录没有完成，请重试。"
                }
            }
        }
    }

    // MARK: Nonce helpers (internal so tests can reach them)

    static func randomNonce(length: Int = 32) -> String {
        let charset = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-._")
        var bytes = [UInt8](repeating: 0, count: length)
        precondition(SecRandomCopyBytes(kSecRandomDefault, length, &bytes) == errSecSuccess, "random bytes unavailable")
        return String(bytes.map { charset[Int($0) % charset.count] })
    }

    static func sha256Hex(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
