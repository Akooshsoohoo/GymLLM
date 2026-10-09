import SwiftUI

/// Your routines: start one, change it, delete it. Mirrors templates/routines.html.
struct RoutinesView: View {
    @Environment(AppState.self) private var app
    /// Open the editor on a routine, or on a new one (nil).
    let edit: (Int?) -> Void
    /// A recording was started from a routine: back to the recorder.
    let started: () -> Void

    @State private var routines: [RoutineRow]?
    @State private var error: String?
    @State private var deleting: RoutineRow?
    @State private var busy: Int?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BackLink(title: "Record")
                HStack(alignment: .firstTextBaseline) {
                    Text("Routines")
                        .font(.head(32, relativeTo: .largeTitle))
                        .foregroundStyle(Palette.ink)
                    Spacer(minLength: 8)
                    Button("New routine") { edit(nil) }
                        .buttonStyle(.pill(.primary, height: 40))
                }
                Text("A routine fills in the recorder for you. Start one and fill in the numbers as you train.")
                    .font(.text(15))
                    .foregroundStyle(Palette.ink2)
                    .fixedSize(horizontal: false, vertical: true)
                if let error { ErrorBanner(message: error) }

                if let routines, routines.isEmpty {
                    Text("No routines yet.")
                        .font(.text(15))
                        .foregroundStyle(Palette.muted)
                        .padding(.top, 8)
                } else if let routines {
                    ForEach(routines) { row($0) }
                } else if error == nil {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 40)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { Task { await load() } }
        .confirmationDialog(
            "Delete \(deleting?.name ?? "this routine")?",
            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
            titleVisibility: .visible, presenting: deleting
        ) { routine in
            Button("Delete", role: .destructive) { delete(routine) }
            Button("Keep it", role: .cancel) {}
        } message: { _ in
            Text("Workouts you already logged with it stay as they are.")
        }
    }

    private func row(_ routine: RoutineRow) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(routine.name)
                    .font(.head(19))
                    .foregroundStyle(Palette.ink)
                Text(routine.blocksText)
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            .accessibilityElement(children: .combine)
            HStack(spacing: 10) {
                // A recording already running always wins, as on the site.
                if app.recording == nil {
                    Button {
                        start(routine)
                    } label: {
                        if busy == routine.id { ProgressView().tint(Palette.onYou) } else { Text("Start") }
                    }
                    .buttonStyle(.pill(.you, height: 36))
                    .accessibilityLabel("Start \(routine.name)")
                }
                Button("Edit") { edit(routine.id) }
                    .buttonStyle(.pill(.ghost, height: 36))
                    .accessibilityLabel("Edit \(routine.name)")
                Spacer(minLength: 0)
                Button("Delete") { deleting = routine }
                    .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 14))
                    .accessibilityLabel("Delete \(routine.name)")
            }
            .disabled(busy != nil)
        }
        .card()
    }

    private func load() async {
        do {
            let list: RoutineList = try await app.api.get("/routines")
            routines = list.routines
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func start(_ routine: RoutineRow) {
        busy = routine.id
        Task {
            do {
                try await startRecording(from: routine, app: app)
                started()
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = nil
        }
    }

    private func delete(_ routine: RoutineRow) {
        busy = routine.id
        Task {
            do {
                let list: RoutineList = try await app.api.delete("/routines/\(routine.id)")
                routines = list.routines
                error = nil
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = nil
        }
    }
}
