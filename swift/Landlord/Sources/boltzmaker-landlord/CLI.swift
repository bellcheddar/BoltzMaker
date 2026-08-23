import Foundation

// Diagnostics go to stderr, payload to stdout. A caller redirecting stdout to a file
// must get JSON and nothing else, or the Python bridge has to guess where the data
// starts.
func note(_ line: String) {
    FileHandle.standardError.write(Data((line + "\n").utf8))
}

func die(_ error: LandlordError) -> Never {
    note("boltzmaker-landlord: \(error)")
    exit(error.exitCode)
}

func usage() -> Never {
    note("""
        boltzmaker-landlord check
        boltzmaker-landlord narrate --in <factblock.json> [--out <summary.json>]
        boltzmaker-landlord batch   --in-dir <facts/> --out-dir <summaries/> [--concurrency N]
        boltzmaker-landlord reduce  --in <reduce-input.json> [--out <campaign.json>]
        """)
    exit(64)
}

func flag(_ name: String, _ args: [String]) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

let encoder: JSONEncoder = {
    let e = JSONEncoder()
    e.outputFormatting = [.prettyPrinted, .sortedKeys]
    return e
}()

@main
struct Landlord {
    static func main() async {
        // Narration must never slow a folding campaign down. Utility QoS is the
        // enforcement of INV-4: the OS deprioritises this process against anything
        // the user is actually waiting on.
        //
        // Set through the pthread API rather than `Thread.current.qualityOfService`,
        // which is unavailable from an async context. Not backgroundQoS: that also
        // throttles I/O hard, and this process writes a file per target.
        pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0)

        let args = Array(CommandLine.arguments.dropFirst())
        guard let command = args.first else { usage() }

        switch command {
        case "check":
            if let problem = Availability.check() { die(problem) }
            print("available")

        case "narrate":
            guard let input = flag("--in", args) else { usage() }
            if let problem = Availability.check() { die(problem) }
            let json = (try? String(contentsOfFile: input, encoding: .utf8)) ?? ""
            guard !json.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                note("boltzmaker-landlord: \(input) is empty or unreadable"); exit(66)
            }
            do {
                let (summary, elapsed) = try await Narrator.narrate(factBlockJSON: json)
                let envelope = SummaryEnvelope(
                    targetId: targetId(from: json, fallback: input),
                    summary: summary, generatedBy: "foundation-models",
                    elapsedSeconds: elapsed)
                let data = try encoder.encode(envelope)
                if let out = flag("--out", args) {
                    try data.write(to: URL(fileURLWithPath: out))
                    note("wrote \(out) in \(String(format: "%.2f", elapsed))s")
                } else {
                    FileHandle.standardOutput.write(data)
                }
            } catch let error as LandlordError {
                die(error)
            } catch {
                die(.generation("\(error)"))
            }

        case "reduce":
            guard let input = flag("--in", args) else { usage() }
            if let problem = Availability.check() { die(problem) }
            let json = (try? String(contentsOfFile: input, encoding: .utf8)) ?? ""
            do {
                let (summary, elapsed) = try await Narrator.reduce(inputJSON: json)
                let envelope = CampaignEnvelope(summary: summary,
                                                generatedBy: "foundation-models",
                                                elapsedSeconds: elapsed)
                let data = try encoder.encode(envelope)
                if let out = flag("--out", args) {
                    try data.write(to: URL(fileURLWithPath: out))
                    note("wrote \(out) in \(String(format: "%.2f", elapsed))s")
                } else {
                    FileHandle.standardOutput.write(data)
                }
            } catch let error as LandlordError {
                die(error)
            } catch {
                die(.generation("\(error)"))
            }

        case "batch":
            guard let inDir = flag("--in-dir", args), let outDir = flag("--out-dir", args)
            else { usage() }
            if let problem = Availability.check() { die(problem) }
            let concurrency = max(1, min(8, Int(flag("--concurrency", args) ?? "2") ?? 2))
            await runBatch(inDir: inDir, outDir: outDir, concurrency: concurrency)

        default:
            usage()
        }
    }

    /// Pulled out of the block rather than the filename, so a summary can always be
    /// matched back to the target it describes even if files are renamed.
    static func targetId(from json: String, fallback: String) -> String {
        struct Peek: Decodable { let target_id: String? }
        if let data = json.data(using: .utf8),
           let peek = try? JSONDecoder().decode(Peek.self, from: data),
           let id = peek.target_id { return id }
        return URL(fileURLWithPath: fallback).deletingPathExtension().lastPathComponent
    }

    /// Batch is the primary interface, not a convenience.
    ///
    /// Phase 0 measured roughly 4 to 5 seconds of process and session startup per
    /// target against 5 to 19 seconds of actual inference, so narrating a campaign one
    /// subprocess at a time spends a third of its time starting up. Concurrency then
    /// helps again on top: a single decode stream leaves most of the ANE idle.
    static func runBatch(inDir: String, outDir: String, concurrency: Int) async {
        let fm = FileManager.default
        try? fm.createDirectory(atPath: outDir, withIntermediateDirectories: true)
        let names = ((try? fm.contentsOfDirectory(atPath: inDir)) ?? [])
            .filter { $0.hasSuffix(".json") }.sorted()
        guard !names.isEmpty else { note("no .json fact blocks in \(inDir)"); exit(66) }

        let started = Date()
        var done = 0, failed = 0

        await withTaskGroup(of: (String, Bool).self) { group in
            var next = 0
            func submit() {
                guard next < names.count else { return }
                let name = names[next]; next += 1
                group.addTask {
                    let path = (inDir as NSString).appendingPathComponent(name)
                    let json = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
                    do {
                        let (summary, elapsed) = try await Narrator.narrate(factBlockJSON: json)
                        let envelope = SummaryEnvelope(
                            targetId: targetId(from: json, fallback: name),
                            summary: summary, generatedBy: "foundation-models",
                            elapsedSeconds: elapsed)
                        let out = (outDir as NSString)
                            .appendingPathComponent((name as NSString).deletingPathExtension + ".summary.json")
                        try encoder.encode(envelope).write(to: URL(fileURLWithPath: out))
                        note("OK      \(name)  \(String(format: "%.2f", elapsed))s")
                        return (name, true)
                    } catch {
                        // One target failing is not the campaign failing. Record it,
                        // let the Python side fall back to the template for this one,
                        // and carry on with the rest.
                        note("FAILED  \(name)  \(error)")
                        return (name, false)
                    }
                }
            }
            for _ in 0..<concurrency { submit() }
            for await (_, ok) in group {
                if ok { done += 1 } else { failed += 1 }
                submit()
            }
        }

        let elapsed = Date().timeIntervalSince(started)
        note("batch: \(done) written, \(failed) failed, "
             + "\(String(format: "%.1f", elapsed))s total, "
             + "\(String(format: "%.1f", elapsed / Double(max(names.count, 1))))s per target")
        if done == 0 { exit(4) }
    }
}
