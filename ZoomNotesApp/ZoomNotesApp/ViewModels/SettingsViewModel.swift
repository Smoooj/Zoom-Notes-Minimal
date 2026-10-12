//
//  SettingsViewModel.swift
//  ZoomNotesApp
//
//  Loads and saves local transcript preferences.
//

import Foundation
import Combine

@MainActor
class SettingsViewModel: ObservableObject {
    @Published var config: ZoomNotesConfig = ZoomNotesConfig()
    @Published var isLoading = false
    @Published var isSaving = false
    @Published var error: String?
    @Published var saveSuccess = false

    /// Called after a successful save so the caller can signal the engine.
    var onSave: (() -> Void)?

    func loadConfig() async {
        isLoading = true
        error = nil
        config = loadConfig_()
        isLoading = false
    }

    func saveConfig() async {
        guard !isSaving else { return }
        isSaving = true
        error = nil
        saveSuccess = false

        do {
            try saveConfig_(config)
            saveSuccess = true
            onSave?()
            Task {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                await MainActor.run { self.saveSuccess = false }
            }
        } catch {
            self.error = "Save failed: \(error.localizedDescription)"
        }
        isSaving = false
    }

}

// Avoid name collision with the free functions in ZoomNotesConfig.swift
private func loadConfig_() -> ZoomNotesConfig { loadConfig() }
private func saveConfig_(_ cfg: ZoomNotesConfig) throws { try saveConfig(cfg) }
