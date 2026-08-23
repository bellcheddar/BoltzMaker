import Foundation
import FoundationModels

/// The reduce stage: many per-target summaries in, one campaign summary out.
///
/// Kept deliberately narrower than the map stage. A campaign summary that tries to
/// mention every target is just the map output concatenated, which is what the reader
/// already has; what is wanted is the shape of the campaign, so the schema asks for a
/// short overview, a handful of findings and the caveats -- and caps them.
enum CampaignSchema {
    /// Only the prose. `keyFindings` used to be generated and is now supplied by
    /// Python: every campaign-level finding is a tally, and asked to compose them the
    /// model misattributed two of four -- naming the caution count as discards, and
    /// the flagged count as the confidence count. Both figures were in its input, so
    /// the numeric gate passed them. It checks that a number was supplied, not that it
    /// was attached to the right noun.
    static func make() throws -> GenerationSchema {
        let text = DynamicGenerationSchema(type: String.self)

        let root = DynamicGenerationSchema(
            name: "CampaignSummary",
            description: "A short factual overview of a whole prediction campaign.",
            properties: [
                .init(name: "overview",
                      description: """
                          Two or three sentences of plain narrative framing: what this \
                          campaign tested and what shape the results take. The tallies \
                          are given to you as finished sentences in key_findings -- do \
                          not restate, recount or reattribute them, and prefer to write \
                          no figures at all.
                          """,
                      schema: text),
                .init(name: "caveats",
                      description: """
                          One or two sentences on what limits these results, in \
                          qualitative terms. Do not restate any tally; key_findings \
                          already carries the counts.
                          """,
                      schema: text),
            ])
        return try GenerationSchema(root: root, dependencies: [])
    }
}

struct CampaignSummary: Codable {
    var overview: String
    var caveats: String

    init(from content: GeneratedContent) throws {
        overview = (try? content.value(String.self, forProperty: "overview")) ?? ""
        caveats = (try? content.value(String.self, forProperty: "caveats")) ?? ""
    }
}

struct CampaignEnvelope: Codable {
    var summary: CampaignSummary
    var generatedBy: String
    var elapsedSeconds: Double
}

extension Narrator {
    static let campaignInstructions = """
        You write a short factual overview of a computational structural-biology \
        campaign, for working scientists.

        Rules, in order of importance:
        1. Use only the supplied statistics and target summaries. Never introduce a \
        protein, ligand, number, or finding that is not in them.
        2. Never compute or re-count anything. The tallies are given; report them.
        3. Say plainly how many targets were flagged or marked discard. A campaign \
        with failures is not a successful one.
        4. Prefer what holds across several targets to what is true of one.
        5. British English. No hedging, no marketing.
        """

    static func reduce(inputJSON: String) async throws -> (CampaignSummary, Double) {
        let started = Date()
        let session = LanguageModelSession(instructions: campaignInstructions)
        do {
            let response = try await session.respond(
                to: "Summarise this campaign.\n\n" + inputJSON,
                schema: try CampaignSchema.make(),
                options: GenerationOptions(maximumResponseTokens: maxOutputTokens))
            return (try CampaignSummary(from: response.content),
                    Date().timeIntervalSince(started))
        } catch {
            throw LandlordError.generation("\(error)")
        }
    }
}
