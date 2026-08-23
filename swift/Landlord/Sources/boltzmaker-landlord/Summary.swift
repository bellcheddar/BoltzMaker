import Foundation
import FoundationModels

/// What the model is allowed to produce, as a schema built at run time.
///
/// The plan called for `@Generable` structs. That macro needs the
/// `FoundationModelsMacros` compiler plugin, which ships with Xcode and **not** with
/// the CommandLineTools -- so using it would make a 15 GB Xcode install a build
/// dependency for a binary whose entire selling point is that it ships no weights.
///
/// `DynamicGenerationSchema` is the framework's own answer to this. The schema is
/// assembled at run time and handed to `respond(to:schema:)`, and decoding is
/// constrained by it exactly as it would be by the macro: this is the same guided
/// generation, described a different way. What is lost is compile-time field typing,
/// which `TargetSummary.init(from:)` below puts back by hand.
///
/// `anyOf` is the important part. `recommendation` is a closed set of three, and a
/// model asked for a verdict in free text will eventually write "proceed with
/// caution" -- neither of two things a caller can branch on. Constrained by `anyOf`,
/// the other answers are unemittable rather than merely discouraged.
enum SummarySchema {
    static let verdicts = ["proceed", "caution", "discard"]

    /// Built per target, not once.
    ///
    /// `ligandCount` is the reason this is a function of the block rather than a
    /// constant. Fixing the array to exactly the number of ligands supplied makes
    /// omission impossible instead of merely discouraged -- the first run returned an
    /// empty `ligandNotes` for a target that plainly had a ligand, and a schema
    /// permitting 0 to 8 elements is a schema that permits that.
    static func make(ligandCount: Int) throws -> GenerationSchema {
        // Leaves are `type: String.self`, not objects with no properties. The
        // properties-based initialiser builds an *object*, so a field declared that
        // way constrains the model to emit `{}` -- which is exactly what happened on
        // the first run: a correct verdict beside three empty strings, no error
        // anywhere, because an empty object is a valid instance of an empty object.
        let text = DynamicGenerationSchema(type: String.self)

        let ligandNotes = DynamicGenerationSchema(
            arrayOf: DynamicGenerationSchema(type: String.self),
            minimumElements: ligandCount, maximumElements: ligandCount)


        let root = DynamicGenerationSchema(
            name: "TargetSummary",
            description: "A short factual summary of one predicted target.",
            properties: [
                .init(name: "confidence",
                      description: """
                          Two sentences on how well determined this structure is, and \
                          what that means for someone deciding whether to trust it. Do \
                          not restate the numeric scores.
                          """,
                      schema: text),
                .init(name: "ligandNotes",
                      description: """
                          One sentence per ligand, in the order supplied, naming the \
                          ligand and what its contacts and predicted potency show. If a \
                          pose comparison is supplied, say plainly whether the \
                          prediction reproduced the experimental structure.
                          """,
                      schema: ligandNotes),
                .init(name: "caveat",
                      description: """
                          One sentence naming the single largest caveat, drawn from the \
                          flags. If there are no flags and nothing is amiss, say so \
                          briefly rather than inventing a concern.
                          """,
                      schema: text),
            ])

        return try GenerationSchema(root: root, dependencies: [])
    }
}

/// The typed view of what came back, reconstructed from `GeneratedContent`.
struct TargetSummary: Codable {
    var confidence: String
    var ligandNotes: [String]
    var recommendation: String
    var caveat: String

    init(from content: GeneratedContent) throws {
        confidence = (try? content.value(String.self, forProperty: "confidence")) ?? ""
        ligandNotes = (try? content.value([String].self, forProperty: "ligandNotes")) ?? []
        caveat = (try? content.value(String.self, forProperty: "caveat")) ?? ""
        // Not generated. The block carries it, computed in Python from the pose
        // verdict, the flags and the confidence band. See FactBlock.recommendation.
        recommendation = ""
    }
}

/// The envelope written to disk: the summary plus what produced it.
///
/// Provenance is not decoration. A summary that turns out to be wrong has to be
/// traceable to the block it came from, and a campaign mixing model-written and
/// template-written summaries must say which is which rather than leaving a reader to
/// guess from the prose.
struct SummaryEnvelope: Codable {
    var targetId: String
    var summary: TargetSummary
    var generatedBy: String
    var elapsedSeconds: Double
}
