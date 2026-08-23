import Foundation
import FoundationModels

enum LandlordError: Error, CustomStringConvertible {
    case unavailable(String, code: Int32)
    case generation(String)

    var description: String {
        switch self {
        case .unavailable(let why, _): return why
        case .generation(let why): return "generation failed: \(why)"
        }
    }

    var exitCode: Int32 {
        switch self {
        case .unavailable(_, let code): return code
        case .generation: return 4
        }
    }
}

/// Availability, reported so that the remediation is obvious.
///
/// Three distinct states with three different answers, and users hit all of them:
/// nothing can be done about ineligible hardware, a disabled toggle is a settings
/// change, and a downloading model just needs time. Collapsing them into "unavailable"
/// sends someone to the wrong place. Each gets its own exit code so the Python bridge
/// can branch without parsing prose.
enum Availability {
    static func check() -> LandlordError? {
        switch SystemLanguageModel.default.availability {
        case .available:
            return nil
        case .unavailable(.deviceNotEligible):
            return .unavailable(
                "device_not_eligible: this Mac cannot run Apple Intelligence. "
                + "Landlord will use the template renderer instead.", code: 10)
        case .unavailable(.appleIntelligenceNotEnabled):
            return .unavailable(
                "apple_intelligence_not_enabled: switch it on in System Settings > "
                + "Apple Intelligence & Siri.", code: 11)
        case .unavailable(.modelNotReady):
            return .unavailable(
                "model_not_ready: the model is still downloading. Try again shortly.",
                code: 12)
        case .unavailable(let other):
            return .unavailable("unavailable: \(other)", code: 13)
        @unknown default:
            return .unavailable("unavailable: unrecognised availability state", code: 13)
        }
    }
}

struct Narrator {
    /// The rules that keep the model to its job.
    ///
    /// "Never restate a numeric value" is the one that matters and the one it breaks:
    /// Phase 0 found it quotes figures back regardless. It stays because it reduces
    /// the habit, but it is not what makes the output safe -- the numeric-integrity
    /// gate on the Python side is. Instructions discourage; the gate enforces.
    static let instructions = """
        You write short factual summaries of computational structural-biology results \
        for working scientists who are not necessarily structural biologists.

        Rules, in order of importance:
        1. Narrate only the facts supplied in the JSON. Never introduce a protein, \
        ligand, interaction, or structure that is not present in it.
        2. Never compute, infer, derive, or restate a numeric value. The judgements \
        have already been made: fields such as interpretation, rank and verdict are \
        conclusions to report, not evidence to re-weigh.
        3. If ligands_omitted is greater than zero, say how many ligands were left out.
        4. Report flags plainly. A flagged target is not a successful one.
        5. British English. No hedging, no marketing, no exclamation marks.
        """

    /// One block in, one summary out.
    ///
    /// A fresh session per target, deliberately. A shared session would carry one
    /// target's context into the next, and on a matrix campaign -- the same ligand
    /// against the same receptor in three pocket conditions -- that is exactly the
    /// circumstance in which a model starts describing the previous target.
    /// The window covers instructions, the serialised schema, the prompt and the
    /// output together, and only the last of those was unbounded. One target failed
    /// with "Content contains 4090 tokens, which exceeds the maximum allowed context
    /// size of 4096" and then succeeded on a retry with the same input, which is the
    /// signature of a generation that sometimes runs long rather than a prompt that is
    /// always too big. Capping the output removes the variance.
    ///
    /// 600 is the plan's own output budget. A target summary that needs more than that
    /// is not a summary.
    static let maxOutputTokens = 600

    /// How many ligands the block carries, so the schema can demand exactly that many
    /// notes. An apo target has none, and must not be asked for one.
    static func ligandCount(in json: String) -> Int {
        struct Peek: Decodable { let ligands: [AnyCodable]? }
        struct AnyCodable: Decodable { init(from d: Decoder) throws {} }
        guard let data = json.data(using: .utf8),
              let peek = try? JSONDecoder().decode(Peek.self, from: data) else { return 0 }
        return peek.ligands?.count ?? 0
    }

    static func verdict(in json: String) -> String {
        struct Peek: Decodable { let recommendation: String? }
        guard let data = json.data(using: .utf8),
              let peek = try? JSONDecoder().decode(Peek.self, from: data) else { return "" }
        return peek.recommendation ?? ""
    }

    static func narrate(factBlockJSON: String, includeSchema: Bool = true
                        ) async throws -> (TargetSummary, Double) {
        let started = Date()
        let session = LanguageModelSession(instructions: instructions)
        do {
            let schema = try SummarySchema.make(ligandCount: ligandCount(in: factBlockJSON))
            let response = try await session.respond(
                to: "Summarise this target.\n\n" + factBlockJSON,
                schema: schema,
                includeSchemaInPrompt: includeSchema,
                options: GenerationOptions(maximumResponseTokens: maxOutputTokens))
            var summary = try TargetSummary(from: response.content)
            // Copied from the block, not generated: a deterministic judgement Python
            // already made, so the model is never given the chance to disagree with it.
            summary.recommendation = verdict(in: factBlockJSON)
            return (summary, Date().timeIntervalSince(started))
        } catch {
            throw LandlordError.generation("\(error)")
        }
    }
}
