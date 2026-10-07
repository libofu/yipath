import SwiftUI

/// One screen for both "今日" and "本周": only the `period` differs.
struct ReadingScreen: View {
    let period: Period
    @Environment(AppState.self) private var appState

    private var state: LoadState<Reading> { appState.readings[period] ?? .idle }

    var body: some View {
        ScrollView {
            VStack(spacing: 22) {
                switch state {
                case .idle, .loading:
                    LoadingView()
                case .failed(let message):
                    FailureView(message: message) { Task { await appState.load(period, force: true) } }
                case .loaded(let reading):
                    ReadingContent(period: period, reading: reading)
                }
                Text(Copy.disclaimer)
                    .font(.footnote)
                    .foregroundStyle(Palette.inkSoft)
                    .multilineTextAlignment(.center)
                    .padding(.top, 8)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 24)
        }
        .background(Palette.paper.ignoresSafeArea())
        // `.task` runs when the screen appears (and is cancelled if it disappears).
        .task { await appState.load(period) }
        // Pull down to reload; handy after a failure or when a new day has begun.
        .refreshable { await appState.load(period, force: true) }
    }
}

// MARK: - Loaded content

private struct ReadingContent: View {
    let period: Period
    let reading: Reading

    var body: some View {
        VStack(spacing: 20) {
            VStack(spacing: 14) {
                Text(dateLine)
                    .songti(15, relativeTo: .subheadline)
                    .foregroundStyle(Palette.inkSoft)
                SealLabel(text: period.title)
                Text(reading.theme)
                    .songti(34, relativeTo: .largeTitle, weight: .bold)
                    .foregroundStyle(Palette.ink)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("theme")
            }
            .padding(.vertical, 8)

            AdviceCard(kind: .work, card: reading.work)
            AdviceCard(kind: .life, card: reading.life)
            AdviceCard(kind: .avoid, card: reading.avoid)
        }
    }

    /// "十月七日 周三" for today; "本周 10月5日 – 10月11日" for the week.
    private var dateLine: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        switch period {
        case .today:
            f.dateFormat = "M月d日 EEEE"
            return f.string(from: Date())
        case .week:
            var cal = Calendar(identifier: .gregorian)
            cal.firstWeekday = 2   // weeks run Monday to Sunday, like the backend
            let start = cal.dateInterval(of: .weekOfYear, for: Date())?.start ?? Date()
            let end = cal.date(byAdding: .day, value: 6, to: start) ?? start
            f.dateFormat = "M月d日"
            return "\(f.string(from: start)) – \(f.string(from: end))"
        }
    }
}

/// The three kinds of card, with their label and color.
enum CardKind {
    case work, life, avoid

    var label: String {
        switch self {
        case .work: return "宜 · 事业"
        case .life: return "宜 · 起居"
        case .avoid: return "忌"
        }
    }
    var color: Color { self == .avoid ? Palette.seal : Palette.jade }
}

private struct AdviceCard: View {
    let kind: CardKind
    let card: Card

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(kind.label)
                .songti(14, relativeTo: .footnote, weight: .bold)
                .foregroundStyle(kind.color)
                .padding(.horizontal, 10)
                .padding(.vertical, 3)
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(kind.color, lineWidth: 1))

            Text(card.action)
                .songti(19, relativeTo: .body)
                .foregroundStyle(Palette.ink)
                .lineSpacing(6)
                .fixedSize(horizontal: false, vertical: true)   // let long text wrap instead of truncating

            Text(card.reason)
                .songti(14, relativeTo: .footnote)
                .foregroundStyle(Palette.inkSoft)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(Palette.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Palette.line, lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

/// A small red "seal" stamp, like the chop on a scroll.
private struct SealLabel: View {
    let text: String
    var body: some View {
        Text(text)
            .songti(15, relativeTo: .subheadline, weight: .bold)
            .foregroundStyle(.white)
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .background(Palette.seal, in: RoundedRectangle(cornerRadius: 4))
    }
}

// MARK: - Loading and failure

private struct LoadingView: View {
    var body: some View {
        VStack(spacing: 16) {
            ProgressView()
            Text("先生正在为你排盘……")
                .songti(17)
                .foregroundStyle(Palette.inkSoft)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 120)
        .accessibilityIdentifier("loading")
    }
}

private struct FailureView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Text(message)
                .songti(17)
                .foregroundStyle(Palette.ink)
                .multilineTextAlignment(.center)
            Button("重试", action: retry)
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 100)
        .accessibilityIdentifier("failure")
    }
}
