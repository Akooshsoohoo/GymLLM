import SwiftUI

/// A new routine, or one being changed: a name and blocks written the way you'd
/// log them, with ___ where a number goes. Mirrors templates/routine_edit.html.
struct RoutineEditView: View {
    private struct Block: Identifiable, Hashable {
        let id = UUID()
        var block = RoutineBlock()
    }

    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var back
    /// Nil for a new routine.
    let id: Int?

    @State private var name = ""
    @State private var blocks: [Block] = [Block()]
    @State private var loaded = false
    @State private var saving = false
    @State private var error: String?
    @FocusState private var focus: UUID?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BackLink(title: "Routines")
                Text(id == nil ? "New routine" : "Edit routine")
                    .font(.head(30, relativeTo: .largeTitle))
                    .tracking(-0.6)
                    .foregroundStyle(Palette.ink)
                if loaded {
                    form
                } else if let error {
                    ErrorBanner(message: error)
                    Button("Try again") { Task { await load() } }
                        .buttonStyle(.pill(.white))
                } else {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 40)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom, spacing: 0) { if loaded { saveBar } }
        .task { await load() }
        .disabled(saving)
    }

    @ViewBuilder
    private var form: some View {
        FormField(label: "Name", text: $name, prompt: "Push day", limit: 60)
        (Text("Write each block the way you'd log it. Put ")
            + Text("___").font(.text(14, .bold, relativeTo: .subheadline)).foregroundStyle(Palette.ink)
            + Text(" where a number goes and fill it in while you train. Any line still showing ___ when you finish is skipped."))
            .font(.text(14, relativeTo: .subheadline))
            .foregroundStyle(Palette.ink2)
            .fixedSize(horizontal: false, vertical: true)

        ForEach(Array(blocks.enumerated()), id: \.element.id) { index, item in
            blockCard($blocks[index], at: index)
        }
        Button {
            let block = Block()
            blocks.append(block)
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
        .disabled(blocks.count >= 20)
    }

    private func blockCard(_ item: Binding<Block>, at index: Int) -> some View {
        let number = index + 1
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                TextField(
                    "", text: item.block.name,
                    prompt: Text("Block name (optional)").foregroundStyle(Palette.muted2)
                )
                .font(.text(15, .semibold))
                .foregroundStyle(Palette.ink)
                .accessibilityLabel("Block \(number) name")
                .onChange(of: item.wrappedValue.block.name) { _, new in
                    if new.count > 40 { item.wrappedValue.block.name = String(new.prefix(40)) }
                }
                tool("arrow.up", "Move block \(number) up", disabled: index == 0) {
                    blocks.swapAt(index, index - 1)
                }
                tool("arrow.down", "Move block \(number) down", disabled: index == blocks.count - 1) {
                    blocks.swapAt(index, index + 1)
                }
                Button("Remove") {
                    blocks.remove(at: index)
                    if blocks.isEmpty { blocks = [Block()] }
                }
                .buttonStyle(LinkButtonStyle(color: Palette.muted2, size: 13))
                .padding(.leading, 6)
                .accessibilityLabel("Remove block \(number)")
            }
            TextField(
                "", text: item.block.body,
                prompt: Text("Bench press 185 lbs, 3 sets of ___").foregroundStyle(Palette.muted2),
                axis: .vertical
            )
            .lineLimit(3...)
            .font(.text(17))
            .foregroundStyle(Palette.ink)
            .autocorrectionDisabled()
            .focused($focus, equals: item.wrappedValue.id)
            .accessibilityLabel("Block \(number), what to do")
            .onChange(of: item.wrappedValue.block.body) { _, new in
                if new.count > 4000 { item.wrappedValue.block.body = String(new.prefix(4000)) }
            }
        }
        .card(radius: 20, padding: 16)
    }

    private func tool(_ symbol: String, _ label: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button {
            withAnimation(.easeOut(duration: 0.15)) { action() }
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(disabled ? Palette.disabled : Palette.ink2)
                .frame(width: 32, height: 32)
                .background(Palette.field, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(label)
    }

    private var saveBar: some View {
        VStack(spacing: 10) {
            if let error { ErrorBanner(message: error) }
            Button(action: save) {
                if saving { ProgressView().tint(Palette.onPrimary) } else { Text("Save routine") }
            }
            .buttonStyle(.pill(.primary, height: 56, fill: true))
            .disabled(name.trimmed.isEmpty || saving)
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

    private func load() async {
        guard !loaded else { return }
        guard let id else {
            loaded = true
            return
        }
        do {
            let routine: Routine = try await app.api.get("/routines/\(id)")
            name = routine.name
            blocks = routine.blocks.isEmpty ? [Block()] : routine.blocks.map { Block(block: $0) }
            error = nil
            loaded = true
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func save() {
        focus = nil
        saving = true
        error = nil
        let body = RoutineRequest(name: name.trimmed, blocks: blocks.map(\.block))
        Task {
            do {
                if let id {
                    let _: Routine = try await app.api.put("/routines/\(id)", body)
                } else {
                    let _: Routine = try await app.api.post("/routines", body)
                }
                back()
            } catch let failure {
                error = app.message(for: failure)
            }
            saving = false
        }
    }
}
