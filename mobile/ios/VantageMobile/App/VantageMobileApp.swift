import SwiftUI

@main
struct VantageMobileApp: App {
    @State private var store = RunStore()

    var body: some Scene {
        WindowGroup { RunListView(store: store) }
    }
}
