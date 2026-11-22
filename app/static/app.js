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
let lastFilms;
let changingFilm = false;
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

async function changeFilm(film, action) {
    if (changingFilm) return;
    const deleting = action === "delete_original";
    const location = film.in_library ? "library folder" : "output folder";
    if (deleting && !window.confirm(
        `Permanently delete the original "${film.source}"?\n\nThe converted file "${film.output}" will stay in the ${location}.`
    )) return;
    changingFilm = true;
    for (const button of filmsTable.querySelectorAll("button")) button.disabled = true;
    filmMessage.textContent = deleting ? "Verifying the original streams before deletion…" : "Verifying and moving the converted file…";
    try {
        const response = await fetch(filmsTable.dataset.url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, source: film.source, output: film.output }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "The file action failed.");
        filmMessage.textContent = deleting
            ? `Deleted original: ${film.source}. Converted file kept in the ${location}.`
            : `Moved ${film.output} to the library folder.`;
    } catch (error) {
        filmMessage.textContent = error.message;
    } finally {
        changingFilm = false;
        for (const button of filmsTable.querySelectorAll("button")) button.disabled = false;
        refreshJobs();
    }
}

function showConvertedFilms(films) {
    if (!filmsTable) return;
    const snapshot = JSON.stringify(films);
    if (snapshot === lastFilms) return;
    const rows = document.createDocumentFragment();
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
            button.disabled = changingFilm;
            button.addEventListener("click", () => changeFilm(film, action));
            actions.append(button);
        }
        if (film.in_output) addButton("Move output to library", "move");
        if (film.source !== null) addButton("Delete original", "delete_original");
        row.insertCell().append(actions);
        rows.append(row);
    }
    filmsTable.tBodies[0].replaceChildren(rows);
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
        const { jobs, stats, pending_sources: pendingSources, converted_films: films } = await response.json();
        for (const counter of statCounters) {
            counter.textContent = formatCount.format(stats[counter.dataset.stat]);
        }
        showPendingRows(pendingSources);
        showConvertedFilms(films);
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
