//
//  SettingsView.swift
//  ZoomNotesApp
//
//  Native macOS settings window — sidebar + tabbed content.
//  Mirrors LMA's SettingsView structure, adapted for Zoom Notes config schema.
//

import SwiftUI
import AppKit

// MARK: - Navigation model

private struct NavItem: Identifiable {
    let id: String
    let label: String
    let icon: String
}

private let navItems: [NavItem] = [
    NavItem(id: "output",   label: "Output",      icon: "square.and.arrow.up"),
    NavItem(id: "advanced", label: "Advanced",    icon: "gearshape.2"),
]

// MARK: - Root view

struct SettingsView: View {
    var onSave: (() -> Void)? = nil
    @StateObject private var vm = SettingsViewModel()
    @EnvironmentObject var appState: AppState
    @State private var selectedTab: String = "output"

    var body: some View {
        HStack(spacing: 0) {
            // ── Sidebar ──────────────────────────────────────────────────
            VStack(alignment: .leading, spacing: 2) {
                Text("Settings")
                    .font(.headline)
                    .padding(.horizontal, 16)
                    .padding(.top, 20)
                    .padding(.bottom, 10)

                ForEach(navItems) { item in
                    SidebarRow(item: item, isSelected: selectedTab == item.id)
                        .onTapGesture { selectedTab = item.id }
                }

                Spacer()

                if appState.engineStartupSettled && !appState.isEngineRunning {
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
                        Text("Engine offline").font(.caption2).foregroundColor(.secondary)
                    }
                    .padding(.horizontal, 14)
                    .padding(.bottom, 14)
                }
            }
            .frame(width: 168)
            .background(.background.opacity(0.6))

            Divider()

            // ── Content ──────────────────────────────────────────────────
            VStack(spacing: 0) {
                ScrollView {
                    Group {
                        switch selectedTab {
                        case "output":   OutputTab(vm: vm)
                        default:         AdvancedTab(vm: vm)
                        }
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 4)
                }

                Divider()

                // ── Footer save bar ───────────────────────────────────────
                HStack {
                    if let e = vm.error {
                        Image(systemName: "xmark.circle.fill").foregroundColor(.red)
                        Text(e).font(.caption).foregroundColor(.red).lineLimit(1)
                    }
                    Spacer()
                    if vm.saveSuccess {
                        Text("Saved ✓").foregroundColor(.green).font(.callout)
                    }
                    Button(vm.isSaving ? "Saving…" : "Save") {
                        Task { await vm.saveConfig() }
                    }
                    .disabled(vm.isSaving)
                    .buttonStyle(.borderedProminent)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
        }
        .frame(minWidth: 640, idealWidth: 640, minHeight: 560, idealHeight: 600)
        .task {
            vm.onSave = onSave
            await vm.loadConfig()
        }
    }
}

// MARK: - Sidebar row

private struct SidebarRow: View {
    let item: NavItem
    let isSelected: Bool

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: item.icon)
                .frame(width: 20, height: 20)
                .foregroundColor(isSelected ? .accentColor : .secondary)
            Text(item.label)
                .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: 7)
                .fill(isSelected ? Color.accentColor.opacity(0.12) : Color.clear)
        )
        .padding(.horizontal, 6)
        .contentShape(Rectangle())
        .onHover { inside in
            if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
        }
    }
}

// MARK: - Output Tab

private struct OutputTab: View {
    @ObservedObject var vm: SettingsViewModel

    var body: some View {
        Form {
            Section("Save Location") {
                HStack {
                    TextField("Transcripts folder", text: $vm.config.transcriptsDir)
                    Button("Browse…") { browse { path in
                        if let path { vm.config.transcriptsDir = path }
                    }}
                }
                .help("Absolute path where transcript files are saved")
            }

            Section("Folder Structure") {
                Picker("Date subfolders", selection: $vm.config.subfolderPattern) {
                    Text("None — all files in one folder").tag("none")
                    Text("By day — YYYY-MM-DD/").tag("day")
                    Text("By month — YYYY-MM/").tag("month")
                }
            }

            Section("Filename Patterns") {
                TextField("Transcript filename", text: $vm.config.transcriptFilenamePattern)
                    .help("Tokens: {title} = meeting title   {date} = YYYY-MM-DD")
                Text("{title} = meeting title   {date} = YYYY-MM-DD")
                    .font(.caption).foregroundColor(.secondary)
            }

            Section("Frontmatter") {
                FrontmatterPropertiesSection(vm: vm)
            }
        }
        .formStyle(.grouped)
    }

    private func browse(completion: @escaping (String?) -> Void) {
        let p = NSOpenPanel()
        p.canChooseFiles = false
        p.canChooseDirectories = true
        p.canCreateDirectories = true
        p.prompt = "Choose"
        completion(p.runModal() == .OK ? p.url?.path : nil)
    }
}

// MARK: - Advanced Tab

private struct AdvancedTab: View {
    @ObservedObject var vm: SettingsViewModel

    var body: some View {
        Form {
            Section("Polling") {
                Picker("Poll interval", selection: $vm.config.pollIntervalSecs) {
                    Text("2 seconds").tag(2)
                    Text("5 seconds (default)").tag(5)
                    Text("10 seconds").tag(10)
                    Text("15 seconds").tag(15)
                }
                Picker("Idle threshold", selection: $vm.config.idleThresholdSecs) {
                    Text("30 seconds").tag(30)
                    Text("60 seconds").tag(60)
                    Text("90 seconds (default)").tag(90)
                    Text("120 seconds").tag(120)
                    Text("180 seconds").tag(180)
                }
                Text("Transcripts are saved after no new speech is detected for this long.")
                    .font(.caption).foregroundColor(.secondary)
            }

            Section("WAL Prefixes") {
                TextField("Transcript DB prefix", text: $vm.config.transcriptDbPrefix)
                    .font(.system(.body, design: .monospaced))
                    .help("Folder prefix for the transcript IndexedDB (default: 1CB477F679D6)")
                TextField("Blocks DB prefix", text: $vm.config.blocksDbPrefix)
                    .font(.system(.body, design: .monospaced))
                    .help("Folder prefix for the blocks/title IndexedDB (default: DDEC8414E29A)")
                Text("Update these only if Zoom changes its IndexedDB folder names.")
                    .font(.caption).foregroundColor(.secondary)
            }

            Section("Blocked Meeting IDs") {
                VStack(alignment: .leading, spacing: 6) {
                    TextEditor(text: Binding(
                        get: { vm.config.blockedMeetingIds.joined(separator: "\n") },
                        set: { raw in
                            vm.config.blockedMeetingIds = raw
                                .components(separatedBy: "\n")
                                .map { $0.trimmingCharacters(in: .whitespaces) }
                                .filter { !$0.isEmpty }
                        }
                    ))
                    .font(.system(size: 11, design: .monospaced))
                    .frame(height: 80)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Color.secondary.opacity(0.3), lineWidth: 1)
                    )
                    Text("One meeting ID per line. Copy IDs from the `meeting_id:` field in any transcript.")
                        .font(.caption).foregroundColor(.secondary)
                }
                .padding(.vertical, 4)
            }


        }
        .formStyle(.grouped)
    }
}

// MARK: - Frontmatter Properties Section

private struct FrontmatterPropertyRow: Identifiable {
    let id: UUID
    var key: String
    var value: String

    init(key: String = "", value: String = "") {
        self.id = UUID()
        self.key = key
        self.value = value
    }

    init(from dict: [String: String]) {
        self.id = UUID()
        self.key = dict["key"] ?? ""
        self.value = dict["value"] ?? ""
    }

    var asDict: [String: String] { ["key": key, "value": value] }
}

private struct FrontmatterPropertiesSection: View {
    @ObservedObject var vm: SettingsViewModel
    @State private var rows: [FrontmatterPropertyRow] = []
    @State private var showRawYaml = false

    private var extraYaml: Binding<String> {
        Binding(
            get: { vm.config.extraFrontmatterYaml },
            set: { vm.config.extraFrontmatterYaml = $0 }
        )
    }

    private func syncToConfig() {
        vm.config.customFrontmatterProperties = rows.map(\.asDict)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Custom properties added to every transcript's YAML frontmatter.")
                .font(.caption).foregroundColor(.secondary)

            ForEach($rows) { $row in
                HStack(spacing: 6) {
                    TextField("key", text: $row.key)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 12))
                        .frame(width: 120)
                        .onChange(of: row.key) { _ in syncToConfig() }

                    Text(":").foregroundColor(.secondary).font(.system(size: 12))

                    TextField("value", text: $row.value)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 12))
                        .onChange(of: row.value) { _ in syncToConfig() }

                    Menu {
                        Button("{title}") { row.value += "{title}"; syncToConfig() }
                        Button("{date}")  { row.value += "{date}";  syncToConfig() }
                    } label: {
                        Image(systemName: "chevron.down.circle")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                    .menuStyle(.borderlessButton)
                    .frame(width: 20)
                    .help("Insert token")

                    Button {
                        rows.removeAll { $0.id == row.id }
                        syncToConfig()
                    } label: {
                        Image(systemName: "minus.circle.fill")
                            .foregroundColor(.red)
                            .font(.system(size: 13))
                    }
                    .buttonStyle(.plain)
                }
            }

            Button {
                rows.append(FrontmatterPropertyRow())
                syncToConfig()
            } label: {
                Label("Add property", systemImage: "plus.circle")
                    .font(.system(size: 12))
            }
            .buttonStyle(.plain)
            .foregroundColor(.accentColor)

            Text("Tokens: {title} = meeting title   {date} = YYYY-MM-DD")
                .font(.system(size: 10)).foregroundColor(.secondary)

            Divider()

            Toggle("Include raw YAML block (advanced)", isOn: $showRawYaml)
                .font(.system(size: 12))

            if showRawYaml {
                TextEditor(text: extraYaml)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(minHeight: 80)
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.3)))
                Text("Appended after the structured properties above. Tokens work here too.")
                    .font(.system(size: 10)).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
        .onAppear {
            rows = vm.config.customFrontmatterProperties.map { FrontmatterPropertyRow(from: $0) }
            showRawYaml = !vm.config.extraFrontmatterYaml.isEmpty
        }
        .onChange(of: vm.config.customFrontmatterProperties) { newProps in
            let currentDicts = rows.map(\.asDict)
            if currentDicts != newProps {
                rows = newProps.map { FrontmatterPropertyRow(from: $0) }
            }
        }
    }
}

// MARK: - Preview

#Preview {
    SettingsView().environmentObject(AppState())
}
