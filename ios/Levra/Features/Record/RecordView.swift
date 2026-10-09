import SwiftUI

/// The centre tab: record a workout as it happens, or get to the other ways of
/// logging one. Opens over the tabs; a recording keeps running when it is closed.
struct RecordFlow: View {
    enum Step: Hashable {
        case log
        /// `recorded` is true when the draft came from the recording.
        case review(ReviewDraft, recorded: Bool)
        case routines
        /// The editor: an existing routine, or nil for a new one.
        case routine(Int?)
    }

    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let store: HomeStore
    let onSaved: (SavedSession, Bool) -> Void

    @State private var path: [Step] = []

    var body: some View {
        NavigationStack(path: $path) {
            RecordView(store: store, close: { dismiss() }, go: { path.append($0) })
                .navigationDestination(for: Step.self) { step in
                    switch step {
                    case .log:
                        LogView(store: store, cancel: { dismiss() }) {
                            path.append(.review($0, recorded: false))
                        }
                    case let .review(draft, recorded):
                        ReviewView(draft: draft, cancel: { dismiss() }) { saved, first in
                            if recorded { app.recorder.discard() }
                            onSaved(saved, first)
                        }
                    case .routines:
                        RoutinesView(edit: { path.append(.routine($0)) }, started: { path = [] })
                    case let .routine(id):
                        RoutineEditView(id: id)
                    }
                }
        }
        .tint(Palette.you)
    }
}

/// Starts a recording from one of your routines: its blocks, ready to fill in.
@MainActor
func startRecording(from routine: RoutineRow, app: AppState) async throws {
    let full: Routine = try await app.api.get("/routines/\(routine.id)")
    app.recorder.start(
        owner: app.me?.email ?? "",
        routine: .init(id: full.id, name: full.name),
        blocks: full.blocks.map { Recording.Block(name: $0.name, text: $0.body) }
    )
}

/// Idle: one big record button, and your routines. Live: a timer and blocks of
/// notes you fill in as you train; Stop sends them to be read as one text.
/// Mirrors templates/record.html.
struct RecordView: View {
    @Environment(AppState.self) private var app
    let store: HomeStore
    let close: () -> Void
    let go: (RecordFlow.Step) -> Void

    @State private var routines: [RoutineRow]?
    @State private var error: String?
    @State private var starting: Int?
    @State private var finishing = false
    @State private var confirmingDiscard = false
    @State private var reading = false
    @State private var finishError: String?
    /// The block whose Remove was tapped once: it reads "Remove?" for a moment.
    @State private var removing: UUID?
    @FocusState private var focus: UUID?

    private var quota: Quota? { store.home?.quota ?? app.me?.quota }

    var body: some View {
        Group {
            if let recording = app.recording {
                live(recording)
            } else {
                idle
            }
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { Task { await loadRoutines() } }
        .task { if store.home == nil { await store.load(app: app) } }
    }

    private func loadRoutines() async {
        do {
            let list: RoutineList = try await app.api.get("/routines")
            routines = list.routines
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    // MARK: Idle

    private var idle: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Spacer()
                    Button("Close", action: close)
                        .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text(Days.label(Days.today(), long: true))
                        .font(.text(14, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                    Text(app.firstName.isEmpty ? "Ready when you are." : "Ready when you are, \(app.firstName).")
                        .font(.head(30, relativeTo: .largeTitle))
                        .tracking(-0.6)
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Hit record and jot things down as you train. Put it all in one block, or split it up however you like.")
                        .font(.text(15))
                        .foregroundStyle(Palette.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let error { ErrorBanner(message: error) }

                Button {
                    app.recorder.start(owner: app.me?.email ?? "")
                    focus = app.recording?.blocks.last?.id
                } label: {
                    VStack(spacing: 12) {
                        Circle()
                            .fill(Palette.you)
                            .frame(width: 96, height: 96)
                            .overlay { Circle().fill(Palette.onYou).frame(width: 34, height: 34) }
                        Text("Start workout")
                            .font(.head(19))
                            .foregroundStyle(Palette.ink)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Start workout")

                VStack(alignment: .leading, spacing: 10) {
                    Text("Already done?")
                        .font(.text(14, .medium, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                    HStack(spacing: 10) {
                        Button("Log a past workout") { go(.log) }
                        Button("Add manually") {
                            go(.review(.manual(app: app, firstLog: store.home?.hasLogged == false), recorded: false))
                        }
                    }
                    .buttonStyle(.pill(.ghost, height: 40))
                }

                routinesSection

                if let quota {
                    Text(quota.leftText)
                        .font(.text(13, .medium, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
    }

    private var routinesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead(title: "Routines") {
                Button("Manage routines") { go(.routines) }
                    .buttonStyle(LinkButtonStyle(color: Palette.muted))
            }
            if let routines, routines.isEmpty {
                HStack(spacing: 12) {
                    Text("No routines yet.")
                        .font(.text(15))
                        .foregroundStyle(Palette.muted)
                    Button("+ New routine") { go(.routine(nil)) }
                        .buttonStyle(.pill(.ghost, height: 36))
                }
            } else if let routines {
                VStack(spacing: 0) {
                    ForEach(Array(routines.enumerated()), id: \.element) { index, routine in
                        if index > 0 { Palette.line2.frame(height: 1) }
                        Button {
                            start(routine)
                        } label: {
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(routine.name)
                                        .font(.text(16, .semibold))
                                        .foregroundStyle(Palette.ink)
                                        .lineLimit(1)
                                    Text(routine.blocksText)
                                        .font(.text(13, relativeTo: .footnote))
                                        .foregroundStyle(Palette.muted)
                                }
                                Spacer(minLength: 8)
                                if starting == routine.id {
                                    ProgressView()
                                } else {
                                    Text("Start")
                                        .font(.text(14, .bold, relativeTo: .subheadline))
                                        .foregroundStyle(Palette.youInk)
                                }
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(starting != nil)
                        .accessibilityLabel("Start \(routine.name), \(routine.blocksText)")
                    }
                }
                .card(padding: 0)
            }
        }
    }

    private func start(_ routine: RoutineRow) {
        starting = routine.id
        Task {
            do {
                try await startRecording(from: routine, app: app)
                error = nil
            } catch let failure {
                error = app.message(for: failure)
            }
            starting = nil
        }
    }

    // MARK: Live

    private func live(_ recording: Recording) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Button(action: close) {
                        Label("Close", systemImage: "chevron.down").labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
                    .accessibilityHint("The workout keeps recording")
                    Spacer()
                    HStack(spacing: 8) {
                        Circle().fill(Palette.danger).frame(width: 9, height: 9)
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Text(Recording.clock(from: recording.startedAt, to: context.date))
                                .font(.head(19))
                                .monospacedDigit()
                                .foregroundStyle(Palette.ink)
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Workout time")
                }
                if let routine = recording.routine {
                    Text(routine.name)
                        .font(.head(26, relativeTo: .title))
                        .tracking(-0.5)
                        .foregroundStyle(Palette.ink)
                }

                ForEach(Array(recording.blocks.enumerated()), id: \.element.id) { index, block in
                    blockCard(block, number: index + 1)
                }
                Button {
                    let block = Recording.Block()
                    app.recorder.update { $0.blocks.append(block) }
                    focus = block.id
                } label: {
                    Text("+ Add a block")
                        .font(.text(15, .semibold))
                        .foregroundStyle(Palette.ink2)
                        .frame(maxWidth: .infinity)
                        .frame(height: 48)
                        .overlay {
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .strokeBorder(Palette.dashed, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) { liveBar }
        .sheet(isPresented: $finishing) { finishSheet(recording) }
        .confirmationDialog("Discard this workout?", isPresented: $confirmingDiscard, titleVisibility: .visible) {
            Button("Discard", role: .destructive) { app.recorder.discard() }
            Button("Keep going", role: .cancel) {}
        } message: {
            Text("The timer and everything you wrote will be thrown away.")
        }
    }

    private func blockCard(_ block: Recording.Block, number: Int) -> some View {
        let name = Binding(
            get: { block.name },
            set: { new in app.recorder.update { $0.blocks[id: block.id]?.name = String(new.prefix(40)) } }
        )
        let text = Binding(
            get: { block.text },
            set: { new in app.recorder.update { $0.blocks[id: block.id]?.text = new } }
        )
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                TextField("", text: name, prompt: Text("Block \(number)").foregroundStyle(Palette.muted2))
                    .font(.text(15, .semibold))
                    .foregroundStyle(Palette.ink)
                    .accessibilityLabel("Block \(number) name")
                Button(removing == block.id ? "Remove?" : "Remove") { remove(block) }
                    .buttonStyle(LinkButtonStyle(
                        color: removing == block.id ? Palette.dangerInk : Palette.muted2, size: 13
                    ))
                    .accessibilityLabel(removing == block.id ? "Remove block \(number)? Tap again" : "Remove block \(number)")
            }
            TextField(
                "", text: text,
                prompt: Text("Bench 185, 3 sets of 8. Then some pull ups…").foregroundStyle(Palette.muted2),
                axis: .vertical
            )
            .lineLimit(3...)
            .font(.text(18))
            .foregroundStyle(Palette.ink)
            .focused($focus, equals: block.id)
            .accessibilityLabel("Block \(number) notes")
        }
        .card(radius: 20, padding: 16)
    }

    /// Remove a block; one with writing in it asks first ("Remove?" for a few seconds).
    private func remove(_ block: Recording.Block) {
        if block.isWritten, removing != block.id {
            removing = block.id
            Task {
                try? await Task.sleep(for: .seconds(3))
                if removing == block.id { removing = nil }
            }
            return
        }
        removing = nil
        app.recorder.update {
            $0.blocks.removeAll { $0.id == block.id }
            if $0.blocks.isEmpty { $0.blocks = [.init()] }
        }
    }

    private var liveBar: some View {
        HStack(spacing: 16) {
            Button("Discard") { confirmingDiscard = true }
                .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 16))
                .padding(.horizontal, 8)
                .accessibilityLabel("Discard workout")
            Button {
                focus = nil
                finishError = nil
                finishing = true
            } label: {
                HStack(spacing: 10) {
                    RoundedRectangle(cornerRadius: 3, style: .continuous).frame(width: 14, height: 14)
                    Text("Stop")
                }
            }
            .buttonStyle(.pill(.primary, height: 56, fill: true))
            .accessibilityLabel("Stop")
        }
        .padding(.horizontal, Metrics.gutter)
        .padding(.top, 22)
        .padding(.bottom, 10)
        .background {
            LinearGradient(
                stops: [.init(color: Palette.bgClear, location: 0), .init(color: Palette.bg, location: 0.3)],
                startPoint: .top, endPoint: .bottom
            )
            .ignoresSafeArea(edges: .bottom)
        }
    }

    // MARK: Finish

    private func finishSheet(_ recording: Recording) -> some View {
        let built = recording.built
        let outOfLogs = quota?.left == 0
        return VStack(alignment: .leading, spacing: 14) {
            Text("Finish workout?")
                .font(.head(26, relativeTo: .title))
                .foregroundStyle(Palette.ink)
            (Text(Recording.duration(from: recording.startedAt)).font(.text(17, .bold)).foregroundStyle(Palette.ink)
                + Text(built.blocks > 1 ? " · \(built.blocks) blocks" : "").font(.text(17)).foregroundStyle(Palette.ink2))
            if let finishError { ErrorBanner(message: finishError) }
            if built.skipped > 0 {
                note("\(built.skipped) line\(built.skipped == 1 ? "" : "s") left blank, skipped.")
            }
            if built.blocks == 0 {
                note("Nothing written yet. Add what you did, then log it.")
            } else if outOfLogs, let quota {
                note("You've used today's \(quota.limit) free logs. Your notes stay here; come back tomorrow, or add this one by hand.")
            }
            VStack(spacing: 10) {
                Button {
                    logIt(recording, text: built.text)
                } label: {
                    if reading {
                        HStack(spacing: 8) {
                            ProgressView().tint(Palette.onYou)
                            Text("Reading your workout")
                        }
                    } else {
                        Text("Log it")
                    }
                }
                .buttonStyle(.pill(.you, height: 56, fill: true))
                .disabled(built.blocks == 0 || reading || outOfLogs)
                Button("Keep going") { finishing = false }
                    .buttonStyle(.pill(.white, height: 56, fill: true))
                    .disabled(reading)
            }
            .padding(.top, 4)
            Text(
                "You'll check it over before it's saved."
                    + (quota.map { " \($0.leftText)." } ?? "")
            )
            .font(.text(13, relativeTo: .footnote))
            .foregroundStyle(Palette.muted)
            .frame(maxWidth: .infinity)
        }
        .padding(Metrics.gutter)
        .padding(.top, 8)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .presentationDetents([.medium])
        .presentationBackground(Palette.bg)
        .interactiveDismissDisabled(reading)
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.text(14, relativeTo: .subheadline))
            .foregroundStyle(Palette.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func logIt(_ recording: Recording, text: String) {
        reading = true
        finishError = nil
        Task {
            do {
                let heard: ParseResult = try await app.api.post(
                    "/parse",
                    ParseRequest(text: text, weightUnit: app.weightUnit, routineName: recording.routine?.name)
                )
                finishing = false
                go(.review(ReviewDraft(heard), recorded: true))
            } catch let failure {
                finishError = app.message(for: failure)
            }
            reading = false
        }
    }
}

private extension Array where Element == Recording.Block {
    subscript(id id: UUID) -> Recording.Block? {
        get { first { $0.id == id } }
        set {
            guard let index = firstIndex(where: { $0.id == id }), let newValue else { return }
            self[index] = newValue
        }
    }
}
