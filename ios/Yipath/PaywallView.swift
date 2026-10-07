import StoreKit
import SwiftUI

/// The subscription sheet. Apple requires it to state the price and period, say that the
/// subscription renews automatically and how to cancel, and link the terms and privacy policy.
struct PaywallView: View {
    @Environment(AppState.self) private var appState
    @Environment(SubscriptionManager.self) private var subscriptions
    @Environment(\.dismiss) private var dismiss
    @State private var selectedID: String?

    private var selected: Product? {
        subscriptions.products.first { $0.id == selectedID } ?? subscriptions.products.last
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 22) {
                    VStack(spacing: 10) {
                        Text("继续让先生为你排盘")
                            .songti(28, relativeTo: .title, weight: .bold)
                            .foregroundStyle(Palette.ink)
                            .multilineTextAlignment(.center)
                        Text(statusLine)
                            .songti(15, relativeTo: .subheadline)
                            .foregroundStyle(Palette.inkSoft)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        benefit("每日「宜」「忌」与行动安排")
                        benefit("每周总览，提前安排节奏")
                        benefit("八字、星座与 MBTI 综合解读")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)

                    if subscriptions.products.isEmpty {
                        if subscriptions.hasLoadedProducts {
                            Button("重新加载") { Task { await subscriptions.loadProducts() } }
                                .accessibilityIdentifier("reloadProducts")
                        } else {
                            ProgressView().padding(.vertical, 30)
                        }
                    } else {
                        VStack(spacing: 12) {
                            ForEach(subscriptions.products) { product in
                                ProductRow(product: product, isSelected: product.id == selected?.id)
                                    .onTapGesture { selectedID = product.id }
                            }
                        }
                    }

                    if let message = subscriptions.message {
                        Text(message).font(.footnote).foregroundStyle(Palette.seal).multilineTextAlignment(.center)
                    }

                    Button {
                        if let product = selected { Task { await subscriptions.purchase(product) } }
                    } label: {
                        HStack {
                            Spacer()
                            if subscriptions.isWorking { ProgressView().tint(.white) } else { Text("订阅").songti(18, weight: .bold) }
                            Spacer()
                        }
                        .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(selected == nil || subscriptions.isWorking)
                    .accessibilityIdentifier("subscribe")

                    Button("恢复购买") { Task { await subscriptions.restore() } }
                        .disabled(subscriptions.isWorking)
                        .accessibilityIdentifier("restore")

                    VStack(spacing: 8) {
                        Text(Copy.renewalTerms)
                        if Copy.termsURL != nil || Copy.privacyURL != nil {
                            HStack(spacing: 16) {
                                if let url = Copy.termsURL { Link("服务条款", destination: url) }
                                if let url = Copy.privacyURL { Link("隐私政策", destination: url) }
                            }
                        }
                    }
                    .font(.footnote)
                    .foregroundStyle(Palette.inkSoft)
                    .multilineTextAlignment(.center)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 20)
            }
            .background(Palette.paper.ignoresSafeArea())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } }
            }
            .navigationBarTitleDisplayMode(.inline)
        }
        .task { await subscriptions.loadProducts() }
    }

    private var statusLine: String {
        guard let e = appState.entitlement else { return "订阅后可继续使用全部内容。" }
        switch e.status {
        case .trial: return "免费试用至 \(Self.dayText(e.trialEndsAt))"
        case .subscribed: return "已订阅，有效期至 \(Self.dayText(e.expiresAt ?? e.trialEndsAt))"
        case .expired: return "免费试用已结束"
        }
    }

    private func benefit(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("·").foregroundStyle(Palette.seal).songti(20, weight: .bold)
            Text(text).songti(17).foregroundStyle(Palette.ink)
        }
    }

    static func dayText(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.dateFormat = "M月d日"
        return f.string(from: date)
    }
}

private struct ProductRow: View {
    let product: Product
    let isSelected: Bool

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(product.displayName).songti(18, weight: .bold).foregroundStyle(Palette.ink)
                Text(product.description).songti(13, relativeTo: .footnote).foregroundStyle(Palette.inkSoft)
            }
            Spacer()
            Text("\(product.displayPrice) / \(periodText)")
                .songti(17, weight: .bold)
                .foregroundStyle(Palette.seal)
        }
        .padding(16)
        .background(Palette.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(isSelected ? Palette.seal : Palette.line, lineWidth: isSelected ? 2 : 1))
        .contentShape(RoundedRectangle(cornerRadius: 14))
        .accessibilityIdentifier("product-\(product.id)")
    }

    private var periodText: String {
        switch product.subscription?.subscriptionPeriod.unit {
        case .day: return "天"
        case .week: return "周"
        case .month: return "月"
        case .year: return "年"
        default: return ""
        }
    }
}
