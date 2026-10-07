import SwiftUI

/// The form's working copy of a profile. Kept separate from `Profile` because the
/// controls need slightly different shapes (a Date for time, a String for "no MBTI").
struct ProfileDraft {
    var birthDate: Date
    var knowsBirthTime: Bool
    var birthTime: Date           // only the hour and minute are used
    var mbti: String              // "" means not provided

    static let earliestBirthDate: Date = {
        var c = DateComponents(year: 1920, month: 1, day: 1)
        c.calendar = Calendar(identifier: .gregorian)
        return c.date ?? .distantPast
    }()

    /// A reasonable starting point: 1995-06-15 at noon.
    init() {
        var c = DateComponents(year: 1995, month: 6, day: 15, hour: 12, minute: 0)
        c.calendar = Calendar.current
        birthDate = c.date ?? Date()
        birthTime = c.date ?? Date()
        knowsBirthTime = false
        mbti = ""
    }

    init(from profile: Profile) {
        let cal = Calendar.current
        birthDate = profile.birthDate
        knowsBirthTime = profile.birthHour != nil
        var c = DateComponents(year: 2000, month: 1, day: 1, hour: profile.birthHour ?? 12, minute: profile.birthMinute)
        c.calendar = cal
        birthTime = c.date ?? Date()
        mbti = profile.mbti ?? ""
    }

    func toProfile() -> Profile {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: birthTime)
        return Profile(
            birthDate: birthDate,
            birthHour: knowsBirthTime ? parts.hour : nil,
            birthMinute: knowsBirthTime ? (parts.minute ?? 0) : 0,
            mbti: mbti.isEmpty ? nil : mbti
        )
    }
}

/// The form fields, shared by onboarding and "edit profile".
struct ProfileFormFields: View {
    @Binding var draft: ProfileDraft

    var body: some View {
        // Section = a grouped block in a Form. The text after `header:` is its heading.
        Section {
            DatePicker(
                "出生日期",
                selection: $draft.birthDate,
                in: ProfileDraft.earliestBirthDate...Date(),
                displayedComponents: .date
            )
            .environment(\.locale, Locale(identifier: "zh_CN"))
            .accessibilityIdentifier("birthDate")

            Toggle("知道出生时辰", isOn: $draft.knowsBirthTime)
                .accessibilityIdentifier("knowsTime")
            if draft.knowsBirthTime {
                DatePicker("出生时间", selection: $draft.birthTime, displayedComponents: .hourAndMinute)
                    .environment(\.locale, Locale(identifier: "zh_CN"))
            }
        } header: {
            Text("八字")
        } footer: {
            Text("时辰越准，排盘越细；不确定可以不填。")
        }
        .listRowBackground(Palette.card)

        Section {
            Picker("MBTI", selection: $draft.mbti) {
                Text("不填写").tag("")
                ForEach(allMBTITypes, id: \.self) { Text($0).tag($0) }
            }
            .accessibilityIdentifier("mbti")
        } header: {
            Text("性格（可选）")
        } footer: {
            Text("只用来调整建议的说法与节奏。")
        }
        .listRowBackground(Palette.card)
    }
}
