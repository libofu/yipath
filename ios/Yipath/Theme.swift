import SwiftUI
import UIKit

/// The look of the app: warm paper, dark ink, a seal-red accent and a jade green,
/// like an almanac. Each color has a light and a dark variant, chosen automatically.
enum Palette {
    static let paper = Color(light: 0xF6EEDD, dark: 0x1A1714)      // page background
    static let card = Color(light: 0xFBF6EA, dark: 0x26211C)       // card background
    static let ink = Color(light: 0x2B2622, dark: 0xECE4D4)        // main text
    static let inkSoft = Color(light: 0x6B6258, dark: 0xA79D8E)    // secondary text
    static let seal = Color(light: 0xB3312B, dark: 0xD9534B)       // 印章红: 忌, buttons
    static let jade = Color(light: 0x3E6B5E, dark: 0x7FB5A4)       // 宜
    static let line = Color(light: 0xE0D4BC, dark: 0x3A332B)       // hairlines
}

extension Color {
    /// A color that switches between two hex values for light and dark mode.
    init(light: UInt32, dark: UInt32) {
        self = Color(UIColor { traits in
            UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

/// Serif text for headings and advice. The system's serif design uses a Songti-style face
/// for Chinese, so it needs no bundled font. It is a view modifier (not a plain Font)
/// so that `@ScaledMetric` can scale the size with the user's Dynamic Type setting.
private struct SerifText: ViewModifier {
    @ScaledMetric private var size: CGFloat
    private let weight: Font.Weight

    init(size: CGFloat, relativeTo style: Font.TextStyle, weight: Font.Weight) {
        _size = ScaledMetric(wrappedValue: size, relativeTo: style)
        self.weight = weight
    }

    func body(content: Content) -> some View {
        content.font(.system(size: size, weight: weight, design: .serif))
    }
}

extension View {
    /// Use like `.songti(19, relativeTo: .body, weight: .bold)`.
    func songti(_ size: CGFloat, relativeTo style: Font.TextStyle = .body, weight: Font.Weight = .regular) -> some View {
        modifier(SerifText(size: size, relativeTo: style, weight: weight))
    }
}

/// The disclaimer shown in the app. App Review and users both expect it to be visible.
enum Copy {
    static let disclaimer = "本应用内容仅供娱乐与自我反思，不构成医疗、投资、法律等专业建议。重要决定请咨询专业人士。"
}
