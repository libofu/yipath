import StoreKit

/// Everything to do with buying the subscription, using StoreKit 2.
///
/// StoreKit handles the purchase itself (Apple's payment sheet). Our part is to hand every
/// signed transaction it produces to our server (`appState.submitTransaction`), which checks
/// that Apple signed it and records when the subscription runs out. The server, not the app,
/// decides who has access.
@MainActor
@Observable
final class SubscriptionManager {
    /// Must match the product ids in App Store Connect (and in StoreKit/Yipath.storekit for testing).
    static let productIDs = ["com.libofu.yipath.monthly", "com.libofu.yipath.yearly"]

    private(set) var products: [Product] = []
    /// True once a product fetch has finished, successfully or not (so the paywall can stop spinning).
    private(set) var hasLoadedProducts = false
    private(set) var isWorking = false
    var message: String?

    private let appState: AppState
    private var updatesTask: Task<Void, Never>?

    init(appState: AppState) {
        self.appState = appState
    }

    /// Starts listening for purchases that finish outside the paywall: renewals, purchases
    /// approved later ("Ask to Buy"), or ones made on another device.
    func start() {
        guard updatesTask == nil else { return }
        updatesTask = Task { [weak self] in
            for await result in Transaction.updates {
                await self?.handle(result)
            }
        }
    }

    func loadProducts() async {
        message = nil
        do {
            products = try await Product.products(for: Self.productIDs).sorted { $0.price < $1.price }
            if products.isEmpty { message = "暂时无法获取订阅信息，请稍后再试。" }
        } catch {
            message = "暂时无法获取订阅信息，请稍后再试。"
        }
        hasLoadedProducts = true
    }

    func purchase(_ product: Product) async {
        isWorking = true
        message = nil
        defer { isWorking = false }
        do {
            switch try await product.purchase() {
            case .success(let verification):
                guard case .verified(let transaction) = verification else {
                    message = "无法验证这笔购买。"
                    return
                }
                try await appState.submitTransaction(verification.jwsRepresentation)
                await transaction.finish()   // only after our server accepted it
            case .userCancelled:
                break
            case .pending:
                message = "购买正在等待确认（可能需要家长批准）。"
            @unknown default:
                break
            }
        } catch {
            message = (error as? LocalizedError)?.errorDescription ?? "购买未完成，请稍后再试。"
        }
    }

    /// "恢复购买": ask the App Store for this Apple ID's purchases, then tell our server.
    func restore() async {
        isWorking = true
        message = nil
        defer { isWorking = false }
        do {
            try await AppStore.sync()
        } catch {
            message = "无法恢复购买，请稍后再试。"
            return
        }
        await syncCurrentEntitlements()
        if appState.entitlement?.status != .subscribed {
            message = "没有找到可恢复的订阅。"
        }
    }

    /// Sends the server the newest active subscription this Apple ID has. Called at launch and
    /// when the app comes to the front, so renewals reach the server even if the paywall is never opened.
    func syncCurrentEntitlements() async {
        var newest: (expires: Date, jws: String)?
        for await result in Transaction.currentEntitlements {
            guard case .verified(let transaction) = result, Self.productIDs.contains(transaction.productID) else { continue }
            let expires = transaction.expirationDate ?? .distantPast
            if newest == nil || expires > newest!.expires { newest = (expires, result.jwsRepresentation) }
        }
        if let newest { try? await appState.submitTransaction(newest.jws) }
    }

    private func handle(_ result: VerificationResult<Transaction>) async {
        guard case .verified(let transaction) = result, Self.productIDs.contains(transaction.productID) else { return }
        do {
            try await appState.submitTransaction(result.jwsRepresentation)
            await transaction.finish()
        } catch {
            // Not finished on purpose: StoreKit will deliver it again, so a flaky network can't lose a purchase.
        }
    }
}
