//
//  ZoomNotesConfig.swift
//  ZoomNotesApp
//
//  Swift mirror of zoom_config.py's ZoomNotesConfig dataclass.
//  Reads/writes ~/Library/Application Support/zoom-notes/settings.json
//  directly; old model-related keys are ignored.
//

import Foundation

// MARK: - Config struct

struct ZoomNotesConfig: Codable {

    var transcriptsDir: String = "\(NSHomeDirectory())/Desktop/Meeting Notes/Transcripts"

    var subfolderPattern: String = "day"
    var transcriptFilenamePattern: String = "{title} \u{2014} transcript"


    var customFrontmatterProperties: [[String: String]] = []
    var extraFrontmatterYaml: String = ""

    var pollIntervalSecs: Int = 5
    var idleThresholdSecs: Int = 90

    var transcriptDbPrefix: String = "1CB477F679D6"
    var blocksDbPrefix: String = "DDEC8414E29A"


    var diagnostics: Bool = false

    var blockedMeetingIds: [String] = []

    enum CodingKeys: String, CodingKey {
        case transcriptsDir = "transcripts_dir"
        case subfolderPattern = "subfolder_pattern"
        case transcriptFilenamePattern = "transcript_filename_pattern"
        case customFrontmatterProperties = "custom_frontmatter_properties"
        case extraFrontmatterYaml = "extra_frontmatter_yaml"
        case pollIntervalSecs = "poll_interval_secs"
        case idleThresholdSecs = "idle_threshold_secs"
        case transcriptDbPrefix = "transcript_db_prefix"
        case blocksDbPrefix = "blocks_db_prefix"
        case diagnostics
        case blockedMeetingIds = "blocked_meeting_ids"
    }
}

// MARK: - Resilient decoding
//
// Decode each field independently, falling back to its default when the key
// is missing or malformed. The synthesized decoder is all-or-nothing: a
// single missing key throws, `loadConfig()` swallows the error and returns
// `ZoomNotesConfig()`, and EVERY setting — including the user's notes/
// transcripts directories — silently resets to defaults. That fired whenever
// a new app version added a setting the user's existing settings.json didn't
// have yet, which is how saved output paths got reset to ~/Desktop. Defining
// `init(from:)` in an extension keeps the synthesized memberwise/default
// initializer, so `ZoomNotesConfig()` still supplies the per-field defaults.
extension ZoomNotesConfig {
    init(from decoder: Decoder) throws {
        let defaults = ZoomNotesConfig()
        // A settings.json that isn't even a JSON object is the only fatal
        // case; anything else degrades to per-field defaults.
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init()
        transcriptsDir = (try? c.decodeIfPresent(String.self, forKey: .transcriptsDir)) ?? nil ?? defaults.transcriptsDir
        subfolderPattern = (try? c.decodeIfPresent(String.self, forKey: .subfolderPattern)) ?? nil ?? defaults.subfolderPattern
        transcriptFilenamePattern = (try? c.decodeIfPresent(String.self, forKey: .transcriptFilenamePattern)) ?? nil ?? defaults.transcriptFilenamePattern
        customFrontmatterProperties = (try? c.decodeIfPresent([[String: String]].self, forKey: .customFrontmatterProperties)) ?? nil ?? defaults.customFrontmatterProperties
        extraFrontmatterYaml = (try? c.decodeIfPresent(String.self, forKey: .extraFrontmatterYaml)) ?? nil ?? defaults.extraFrontmatterYaml
        pollIntervalSecs = (try? c.decodeIfPresent(Int.self, forKey: .pollIntervalSecs)) ?? nil ?? defaults.pollIntervalSecs
        idleThresholdSecs = (try? c.decodeIfPresent(Int.self, forKey: .idleThresholdSecs)) ?? nil ?? defaults.idleThresholdSecs
        transcriptDbPrefix = (try? c.decodeIfPresent(String.self, forKey: .transcriptDbPrefix)) ?? nil ?? defaults.transcriptDbPrefix
        blocksDbPrefix = (try? c.decodeIfPresent(String.self, forKey: .blocksDbPrefix)) ?? nil ?? defaults.blocksDbPrefix
        diagnostics = (try? c.decodeIfPresent(Bool.self, forKey: .diagnostics)) ?? nil ?? defaults.diagnostics
        blockedMeetingIds = (try? c.decodeIfPresent([String].self, forKey: .blockedMeetingIds)) ?? nil ?? defaults.blockedMeetingIds
    }
}

// MARK: - File paths

private let configDir: URL = {
    let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
    return appSupport.appendingPathComponent("zoom-notes")
}()

private let configFile: URL = configDir.appendingPathComponent("settings.json")

// MARK: - Load / Save

func loadConfig() -> ZoomNotesConfig {
    guard FileManager.default.fileExists(atPath: configFile.path),
          let data = try? Data(contentsOf: configFile) else {
        return ZoomNotesConfig()
    }
    let decoder = JSONDecoder()
    return (try? decoder.decode(ZoomNotesConfig.self, from: data)) ?? ZoomNotesConfig()
}

func saveConfig(_ cfg: ZoomNotesConfig) throws {
    try FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let data = try encoder.encode(cfg)
    try data.write(to: configFile, options: .atomic)
}
