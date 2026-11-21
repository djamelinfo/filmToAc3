const scanForm = document.querySelector("#scan-form");
scanForm.addEventListener("submit", () => {
    const button = scanForm.querySelector("button");
    button.disabled = true;
    button.textContent = "Scanning…";
});

const conversionForm = document.querySelector("#conversion-form");
const jobsTable = document.querySelector("#jobs-table");
const jobsMessage = document.querySelector("#jobs-message");
const statCounters = document.querySelectorAll("[data-stat]");
const formatCount = new Intl.NumberFormat();
let lastJobs;
let refreshingJobs = false;

async function refreshJobs() {
    if (refreshingJobs) return;
    refreshingJobs = true;
    try {
        const response = await fetch(jobsTable.dataset.url, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const { jobs, stats } = await response.json();
        for (const counter of statCounters) {
            counter.textContent = formatCount.format(stats[counter.dataset.stat]);
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
    const queueButton = conversionForm.querySelector("button");
    const queueMessage = document.querySelector("#queue-message");
    const choices = Array.from(conversionForm.querySelectorAll(".track-choice"));
    let submitting = false;

    function updateButton() {
        queueButton.disabled = submitting || !choices.some(choice => choice.value !== "");
    }

    conversionForm.addEventListener("change", updateButton);
    conversionForm.addEventListener("submit", async event => {
        event.preventDefault();
        const selected = choices.filter(choice => choice.value !== "");
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
