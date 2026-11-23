const scanForm = document.querySelector("#scan-form");
scanForm.addEventListener("submit", () => {
    const button = scanForm.querySelector("button");
    button.disabled = true;
    button.textContent = "Scanning…";
});

const conversionForm = document.querySelector("#conversion-form");
const queueButton = conversionForm?.querySelector("button");
const queueMessage = document.querySelector("#queue-message");
const pendingEmpty = document.querySelector("#pending-empty");
const choices = Array.from(conversionForm?.querySelectorAll(".track-choice") ?? []);
const jobsTable = document.querySelector("#jobs-table");
const jobsMessage = document.querySelector("#jobs-message");
const filmsTable = document.querySelector("#films-table");
const filmMessage = document.querySelector("#film-message");
const filmStatus = document.querySelector("#film-status");
const filmStatusHome = document.querySelector("#film-status-home");
const moveProgress = document.querySelector("#move-progress");
const moveBar = document.querySelector("#move-bar");
const movePercent = document.querySelector("#move-percent");
const moveBytes = document.querySelector("#move-bytes");
const filmCells = new Map();
let lastFilms;
let pendingAction = null;
let activeMove = false;
let lastServerMove;
const statCounters = document.querySelectorAll("[data-stat]");
const formatCount = new Intl.NumberFormat();
let lastJobs;
let refreshingJobs = false;
let submitting = false;

function selectedForQueue(choice) {
    return choice.value !== "" && !choice.closest("tr").hidden;
}

function updateButton() {
    queueButton.disabled = submitting || !choices.some(selectedForQueue);
}

function showPendingRows(pendingSources) {
    if (!conversionForm) return;
    const pending = new Set(pendingSources);
    let hasPending = false;
    for (const choice of choices) {
        const row = choice.closest("tr");
        row.hidden = !pending.has(row.dataset.source);
        hasPending ||= !row.hidden;
    }
    conversionForm.hidden = !hasPending;
    pendingEmpty.hidden = hasPending;
    updateButton();
}

const sizeNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const sizeUnits = ["B", "KiB", "MiB", "GiB", "TiB"];
function formatSize(bytes) {
    let unit = 0;
    while (bytes >= 1024 && unit < sizeUnits.length - 1) {
        bytes /= 1024;
        unit++;
    }
    return `${sizeNumber.format(bytes)} ${sizeUnits[unit]}`;
}

function positionFilmStatus(output) {
    filmStatus.dataset.output = output ?? "";
    const parent = filmCells.get(output) ?? filmStatusHome;
    if (filmStatus.parentElement !== parent) parent.append(filmStatus);
}

function updateFilmButtons() {
    for (const button of filmsTable.querySelectorAll("button")) {
        button.disabled = Boolean(pendingAction || activeMove);
    }
}

function isActiveMove(move) {
    return Boolean(move && move.phase !== "completed" && move.phase !== "failed");
}

function showMove(move) {
    const running = isActiveMove(move);
    if (activeMove !== running) {
        activeMove = running;
        updateFilmButtons();
    }
    if (!move && !moveProgress.hidden) filmMessage.textContent = "";
    moveProgress.hidden = !move || move.phase === "failed";
    if (!move) return;
    positionFilmStatus(move.output);
    const messages = {
        starting: `Starting move of ${move.output}…`,
        checking: `Checking ${move.output} before moving…`,
        copying: `Copying ${move.output} to the library…`,
        verifying: `Verifying the library copy of ${move.output}…`,
        finishing: `Finishing the move of ${move.output}…`,
        completed: `Moved ${move.output} to the library folder.`,
        failed: `Could not move ${move.output}. ${move.error}`,
    };
    const message = messages[move.phase];
    if (filmMessage.textContent !== message) filmMessage.textContent = message;
    if (typeof move.percent === "number") {
        moveBar.value = move.percent;
        movePercent.textContent = `${move.percent}%`;
    } else {
        moveBar.removeAttribute("value");
        movePercent.textContent = "";
    }
    moveBytes.textContent = move.total_bytes > 0
        ? `${formatSize(move.bytes_done)} of ${formatSize(move.total_bytes)} ${move.phase === "copying" ? "copied" : "verified"}`
        : "";
}

async function changeFilm(film, action) {
    if (pendingAction || activeMove) return;
    const deleting = action === "delete_original";
    const location = film.in_library ? "library folder" : "output folder";
    if (deleting && !window.confirm(
        `Permanently delete the original "${film.source}"?\n\nThe converted file "${film.output}" will stay in the ${location}.`
    )) return;
    pendingAction = { action, output: film.output };
    positionFilmStatus(film.output);
    showMove(deleting ? null : { output: film.output, phase: "starting" });
    if (deleting) filmMessage.textContent = "Verifying the original streams before deletion…";
    updateFilmButtons();
    try {
        const response = await fetch(filmsTable.dataset.url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, source: film.source, output: film.output }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "The file action failed.");
        if (deleting) {
            filmMessage.textContent = `Deleted original: ${film.source}. Converted file kept in the ${location}.`;
        } else {
            showMove({ output: film.output, phase: "completed", percent: 100 });
        }
    } catch (error) {
        showMove(null);
        filmMessage.textContent = error.message;
    } finally {
        pendingAction = null;
        updateFilmButtons();
        refreshJobs();
    }
}

function showConvertedFilms(films) {
    if (!filmsTable) return;
    const snapshot = JSON.stringify(films);
    if (snapshot === lastFilms) return;
    const rows = document.createDocumentFragment();
    filmCells.clear();
    for (const film of films) {
        const row = document.createElement("tr");
        row.insertCell().textContent = film.source ?? "Original absent";
        const converted = row.insertCell();
        converted.textContent = film.output;
        const location = document.createElement("small");
        location.textContent = [film.in_output && "Output folder", film.in_library && "Library folder"].filter(Boolean).join(" · ");
        converted.append(location);
        const actions = document.createElement("div");
        actions.className = "film-actions";
        function addButton(label, action) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = label;
            button.className = action === "delete_original" ? "delete-original" : "";
            button.disabled = Boolean(pendingAction || activeMove);
            button.addEventListener("click", () => changeFilm(film, action));
            actions.append(button);
        }
        if (film.in_output) addButton("Move output to library", "move");
        if (film.source !== null) addButton("Delete original", "delete_original");
        const cell = row.insertCell();
        cell.append(actions);
        filmCells.set(film.output, cell);
        rows.append(row);
    }
    filmsTable.tBodies[0].replaceChildren(rows);
    positionFilmStatus(filmStatus.dataset.output);
    filmsTable.hidden = films.length === 0;
    document.querySelector("#films-empty").hidden = films.length > 0;
    lastFilms = snapshot;
}

async function refreshJobs() {
    if (refreshingJobs) return;
    refreshingJobs = true;
    try {
        const response = await fetch(jobsTable.dataset.url, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const { jobs, stats, pending_sources: pendingSources, converted_films: films, move_progress: move } = await response.json();
        for (const counter of statCounters) {
            counter.textContent = formatCount.format(stats[counter.dataset.stat]);
        }
        showPendingRows(pendingSources);
        showConvertedFilms(films);
        const moveSnapshot = JSON.stringify(move);
        if (filmsTable && moveSnapshot !== lastServerMove) {
            lastServerMove = moveSnapshot;
            if (!pendingAction || (pendingAction.action === "move" && pendingAction.output === move?.output && isActiveMove(move))) {
                showMove(move);
            }
        }
        jobsMessage.textContent = jobs.length ? "" : "No conversions queued.";
        jobsTable.hidden = jobs.length === 0;

        const snapshot = JSON.stringify(jobs);
        if (snapshot === lastJobs) return;
        const rows = document.createDocumentFragment();
        for (const job of jobs) {
            const row = document.createElement("tr");
            row.insertCell().textContent = job.source;
            row.insertCell().textContent = `#${job.track_index}`;
            row.insertCell().textContent = job.output;
            const cell = row.insertCell();
            const status = document.createElement("strong");
            status.className = `status ${job.status}`;
            status.textContent = job.status;
            cell.append(status);
            if (job.status === "running") {
                const progress = document.createElement("progress");
                progress.max = 100;
                progress.setAttribute("aria-label", `Conversion progress for ${job.source}`);
                const indicator = document.createElement("div");
                indicator.className = "job-progress";
                indicator.append(progress);
                if (typeof job.progress === "number") {
                    progress.value = job.progress;
                    const percentage = document.createElement("span");
                    percentage.textContent = `${job.progress}%`;
                    percentage.setAttribute("aria-hidden", "true");
                    indicator.append(percentage);
                }
                cell.append(indicator);
            }
            if (job.message) {
                const message = document.createElement("small");
                message.textContent = job.message;
                cell.append(message);
            }
            rows.append(row);
        }
        jobsTable.tBodies[0].replaceChildren(rows);
        lastJobs = snapshot;
    } catch {
        jobsMessage.textContent = "Could not load job status. Retrying…";
    } finally {
        refreshingJobs = false;
    }
}

if (conversionForm) {
    conversionForm.addEventListener("change", updateButton);
    conversionForm.addEventListener("submit", async event => {
        event.preventDefault();
        const selected = choices.filter(selectedForQueue);
        if (submitting || !selected.length) return;
        const selections = selected.map(choice => {
            const row = choice.closest("tr");
            return {
                source: row.dataset.source,
                track_index: Number(choice.value),
                make_default: row.querySelector(".make-default").checked,
            };
        });

        submitting = true;
        updateButton();
        queueMessage.textContent = "Queuing…";
        try {
            const response = await fetch(conversionForm.action, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(selections),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(typeof result.detail === "string" ? result.detail : "Could not queue selected files.");
            }
            const queued = `${result.queued} queued.`;
            const active = result.already_active ? ` ${result.already_active} already queued or running.` : "";
            queueMessage.textContent = queued + active;
            for (const choice of selected) {
                choice.value = "";
                choice.closest("tr").querySelector(".make-default").checked = false;
            }
            refreshJobs();
        } catch (error) {
            queueMessage.textContent = error.message;
        } finally {
            submitting = false;
            updateButton();
        }
    });
    updateButton();
}

refreshJobs();
setInterval(refreshJobs, 1500);
