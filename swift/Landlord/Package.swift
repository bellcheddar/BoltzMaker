// swift-tools-version: 6.2
import PackageDescription

// arm64 macOS only, deliberately. FoundationModels has no Intel path, and the whole
// point of the approach is that no model weights ship -- so there is nothing to build
// for a platform that cannot run the framework. Everywhere else, Landlord resolves to
// the Python template renderer and this package is simply not built.
let package = Package(
    name: "Landlord",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "boltzmaker-landlord", targets: ["boltzmaker-landlord"]),
    ],
    targets: [
        .executableTarget(name: "boltzmaker-landlord", path: "Sources/boltzmaker-landlord"),
    ]
)
