import Foundation

/// Makes game covers again from their videos, for games imported when thumbnails were too small
/// for the cover. One video at a time, and at most once per game per launch: cards asking for the
/// same game share one job, a job no card is waiting for any more is cancelled (and can run again
/// later), and a game whose job finished isn't remade until the next launch, whether or not it
/// worked. `forget(_:)` stops the work for a game being deleted, so nothing is written into its
/// folder while it's removed.
actor ThumbnailRefresher {
    private struct Job {
        let id: Int
        let task: Task<Bool, Never>
        /// Cards waiting for it; when the last one goes away (scrolled off), the job is cancelled.
        var waiters = 0
    }

    private var jobs: [UUID: Job] = [:]
    private var lastJobID = 0
    /// The job queued last, which the next one waits for.
    private var last: Task<Bool, Never>?
    /// Games whose job finished this launch, written or not.
    private var tried: Set<UUID> = []
    /// Games being deleted.
    private var forgotten: Set<UUID> = []

    /// Writes a new thumbnail for game `run` from its video. Returns whether it did.
    func refresh(_ run: UUID, video: URL, thumbnail: URL) async -> Bool {
        guard !tried.contains(run), !forgotten.contains(run) else { return false }
        var job = jobs[run].flatMap { $0.task.isCancelled ? nil : $0 } ?? enqueue(run, video: video, thumbnail: thumbnail)
        job.waiters += 1
        jobs[run] = job
        return await withTaskCancellationHandler {
            await job.task.value
        } onCancel: {
            Task { await self.leave(run, job: job.id) }
        }
    }

    /// Stops the work for a game that's being deleted. Once this returns, nothing more is written
    /// into its folder.
    func forget(_ run: UUID) {
        forgotten.insert(run)
        jobs[run]?.task.cancel()
    }

    private func enqueue(_ run: UUID, video: URL, thumbnail: URL) -> Job {
        lastJobID += 1
        let id = lastJobID
        let previous = last
        let task = Task.detached(priority: .userInitiated) {
            await self.perform(run, job: id, after: previous, video: video, thumbnail: thumbnail)
        }
        last = task
        return Job(id: id, task: task)
    }

    private func perform(_ run: UUID, job: Int, after previous: Task<Bool, Never>?, video: URL,
                         thumbnail: URL) async -> Bool {
        // One video at a time.
        _ = await previous?.value
        var wrote = false
        if !Task.isCancelled, !forgotten.contains(run) {
            let data = await RunStore.makeThumbnail(for: video)
            // Checked again right before the write, with no suspension in between, so a game
            // `forget(_:)` has seen is never written to.
            if !Task.isCancelled, !forgotten.contains(run) {
                // Not tried again this launch even when it worked: the new cover can still be
                // smaller than the video's decoded frames (non-square pixels), and its cards would
                // keep asking.
                tried.insert(run)
                if let data, (try? data.write(to: thumbnail, options: .atomic)) != nil { wrote = true }
            }
        }
        if jobs[run]?.id == job { jobs[run] = nil }
        return wrote
    }

    private func leave(_ run: UUID, job: Int) {
        guard var entry = jobs[run], entry.id == job else { return }
        entry.waiters -= 1
        jobs[run] = entry
        if entry.waiters == 0 { entry.task.cancel() }
    }
}
