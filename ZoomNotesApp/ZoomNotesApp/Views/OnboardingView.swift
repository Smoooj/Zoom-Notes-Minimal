//
//  OnboardingView.swift
//  ZoomNotesApp
//
//  First-launch welcome window. Shown once, dismissed to Settings or the menu bar.
//

import SwiftUI
import AppKit

struct OnboardingView: View {
    var onOpenSettings: () -> Void
    var onDismiss: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // ── Header ────────────────────────────────────────────────────────
            VStack(spacing: 16) {
                if let appIcon = NSImage(named: "AppIcon") {
                    Image(nsImage: appIcon)
                        .resizable()
                        .frame(width: 80, height: 80)
                        .cornerRadius(18)
                } else {
                    Image(systemName: "doc.text.fill")
                        .font(.system(size: 56))
                        .foregroundColor(.accentColor)
                }

                Text("Welcome to Zoom Notes")
                    .font(.largeTitle)
                    .fontWeight(.semibold)

                Text("Automatic meeting transcripts, saved on your Mac.")
                    .font(.title3)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.top, 48)
            .padding(.horizontal, 40)

            // ── Steps ─────────────────────────────────────────────────────────
            VStack(alignment: .leading, spacing: 20) {
                OnboardingStep(
                    number: "1",
                    title: "Lives in your menu bar",
                    detail: "Zoom Notes runs quietly in the background. Look for the icon in your menu bar — it turns blue when a meeting is in progress.",
                    icon: "menubar.rectangle"
                )
                OnboardingStep(
                    number: "2",
                    title: "Reads your Zoom transcript",
                    detail: "It reads the transcript captured by Zoom My Notes and preserves it as a local Markdown file.",
                    icon: "text.bubble"
                )
                OnboardingStep(
                    number: "3",
                    title: "Saves transcripts to your Desktop",
                    detail: "Transcripts appear in ~/Desktop/Meeting Notes/Transcripts/ automatically. You can change the folder and filenames in Settings.",
                    icon: "square.and.arrow.down"
                )
            }
            .padding(.top, 32)
            .padding(.horizontal, 48)

            // ── Privacy note ──────────────────────────────────────────────────
            HStack(spacing: 8) {
                Image(systemName: "lock.shield")
                    .foregroundColor(.secondary)
                    .font(.caption)
                Text("Zoom Notes saves transcripts locally and does not send them to any other service.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 48)
            .padding(.top, 24)

            // ── Buttons ───────────────────────────────────────────────────────
            HStack(spacing: 12) {
                Button("Not Now") {
                    onDismiss()
                }
                .buttonStyle(.plain)
                .foregroundColor(.secondary)

                Spacer()

                Button("Open Settings") {
                    onOpenSettings()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 40)
            .padding(.top, 28)
            .padding(.bottom, 36)
        }
        .frame(width: 520)
        .background(Color(NSColor.windowBackgroundColor))
    }
}

// MARK: - Step row

private struct OnboardingStep: View {
    let number: String
    let title: String
    let detail: String
    let icon: String

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(0.12))
                    .frame(width: 36, height: 36)
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundColor(.accentColor)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .fontWeight(.medium)
                Text(detail)
                    .font(.callout)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
