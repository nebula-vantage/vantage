import SwiftUI

@main
struct VantageMobileApp: App {
    @State private var store: RunStore
    @State private var importer: RunImporter

    init() {
        let store = RunStore()
        _store = State(initialValue: store)
        _importer = State(initialValue: RunImporter(store: store))
    }

    var body: some Scene {
        WindowGroup { RunListView(store: store, importer: importer) }
    }
}
