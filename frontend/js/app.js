/**
 * WCAG 2.1 AA PDF Conversion Tool — Frontend Application
 * Handles file upload, progress tracking, batch ZIP download, and form clearing.
 */

(function () {
    "use strict";

    const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25MB
    const MAX_FILES = 100;
    const POLL_INTERVAL = 2000; // 2 seconds

    let selectedFiles = [];
    let activeJobs = new Map();
    let currentBatchId = null;
    let completedCount = 0;
    let totalQueuedCount = 0;

    // DOM elements
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const fileList = document.getElementById("file-list");
    const uploadBtn = document.getElementById("upload-btn");
    const progressSection = document.getElementById("progress-section");
    const progressContainer = document.getElementById("progress-container");
    const resultsSection = document.getElementById("results-section");
    const resultsContainer = document.getElementById("results-container");
    const errorDisplay = document.getElementById("error-display");

    // --- File Selection ---

    dropZone.addEventListener("click", function () {
        fileInput.click();
    });

    dropZone.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInput.click();
        }
    });

    dropZone.addEventListener("dragover", function (e) {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragleave", function () {
        dropZone.classList.remove("drag-over");
    });

    dropZone.addEventListener("drop", function (e) {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        handleFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener("change", function () {
        handleFiles(fileInput.files);
        fileInput.value = "";
    });

    function handleFiles(fileListObj) {
        for (var i = 0; i < fileListObj.length; i++) {
            var file = fileListObj[i];

            if (selectedFiles.length >= MAX_FILES) {
                showError("Maximum " + MAX_FILES + " files per batch.");
                break;
            }

            if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
                showError("Only PDF files are accepted: " + file.name);
                continue;
            }

            if (file.size > MAX_FILE_SIZE) {
                showError(file.name + " exceeds the 25MB size limit.");
                continue;
            }

            selectedFiles.push(file);
        }

        renderFileList();
        updateUploadButton();
    }

    function renderFileList() {
        fileList.innerHTML = "";
        selectedFiles.forEach(function (file, index) {
            var item = document.createElement("div");
            item.className = "file-item";

            var nameSpan = document.createElement("span");
            nameSpan.className = "file-name";
            nameSpan.textContent = file.name;

            var sizeSpan = document.createElement("span");
            sizeSpan.className = "file-size";
            sizeSpan.textContent = formatSize(file.size);

            var removeBtn = document.createElement("button");
            removeBtn.className = "remove-btn";
            removeBtn.textContent = "\u00D7";
            removeBtn.setAttribute("aria-label", "Remove " + file.name);
            removeBtn.addEventListener("click", function () {
                selectedFiles.splice(index, 1);
                renderFileList();
                updateUploadButton();
            });

            item.appendChild(nameSpan);
            item.appendChild(sizeSpan);
            item.appendChild(removeBtn);
            fileList.appendChild(item);
        });
    }

    function updateUploadButton() {
        uploadBtn.disabled = selectedFiles.length === 0;
    }

    // --- Upload ---

    uploadBtn.addEventListener("click", function () {
        if (selectedFiles.length === 0) return;
        uploadFiles();
    });

    function uploadFiles() {
        hideError();
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Uploading...";
        completedCount = 0;
        totalQueuedCount = 0;

        var formData = new FormData();
        selectedFiles.forEach(function (file) {
            formData.append("files", file);
        });

        fetch("/api/upload", {
            method: "POST",
            body: formData,
        })
            .then(function (response) {
                if (!response.ok) {
                    return response.json().then(function (data) {
                        throw new Error(data.detail || data.error || "Upload failed");
                    });
                }
                return response.json();
            })
            .then(function (data) {
                handleUploadResponse(data);
            })
            .catch(function (error) {
                showError(error.message);
                uploadBtn.disabled = false;
                uploadBtn.textContent = "Upload & Process";
            });
    }

    function handleUploadResponse(data) {
        currentBatchId = data.batch_id;
        progressSection.classList.remove("hidden");
        progressContainer.innerHTML = "";

        data.jobs.forEach(function (job) {
            if (job.status === "queued" && job.job_id) {
                totalQueuedCount++;
                activeJobs.set(job.job_id, {
                    filename: job.filename,
                    status: "queued",
                });
                addProgressItem(job.job_id, job.filename);
                pollJobStatus(job.job_id);
            } else if (job.status === "rejected" || job.status === "error") {
                addProgressItem(job.job_id || "error", job.filename, "failed", job.error);
            }
        });

        selectedFiles = [];
        renderFileList();
        uploadBtn.textContent = "Upload & Process";
        updateUploadButton();
    }

    // --- Progress Tracking ---

    function addProgressItem(jobId, filename, status, error) {
        var item = document.createElement("div");
        item.className = "progress-item" + (status === "failed" ? " failed" : "");
        item.id = "progress-" + jobId;

        var nameDiv = document.createElement("div");
        nameDiv.className = "filename";
        nameDiv.textContent = filename;

        var barContainer = document.createElement("div");
        barContainer.className = "progress-bar-container";
        barContainer.setAttribute("role", "progressbar");
        barContainer.setAttribute("aria-valuenow", "0");
        barContainer.setAttribute("aria-valuemin", "0");
        barContainer.setAttribute("aria-valuemax", "100");
        barContainer.setAttribute("aria-label", filename + " progress");

        var bar = document.createElement("div");
        bar.className = "progress-bar";
        bar.style.width = "0%";
        barContainer.appendChild(bar);

        var textDiv = document.createElement("div");
        textDiv.className = "progress-text";
        textDiv.textContent = error || "Queued...";

        item.appendChild(nameDiv);
        item.appendChild(barContainer);
        item.appendChild(textDiv);
        progressContainer.appendChild(item);
    }

    function updateProgressItem(jobId, data) {
        var item = document.getElementById("progress-" + jobId);
        if (!item) return;

        var bar = item.querySelector(".progress-bar");
        var text = item.querySelector(".progress-text");
        var barContainer = item.querySelector(".progress-bar-container");

        var pct = 0;
        if (data.total_checkpoints > 0) {
            pct = Math.round((data.current_checkpoint / data.total_checkpoints) * 100);
        }

        bar.style.width = pct + "%";
        barContainer.setAttribute("aria-valuenow", String(pct));

        if (data.status === "completed") {
            bar.style.width = "100%";
            barContainer.setAttribute("aria-valuenow", "100");
            item.classList.add("completed");
            text.textContent = "Completed in " + (data.processing_time_seconds || 0).toFixed(1) + "s";
            addResultItem(jobId, data);
            completedCount++;
            checkBatchComplete();
        } else if (data.status === "failed") {
            item.classList.add("failed");
            text.textContent = "Failed: " + (data.error_message || "Unknown error");
            completedCount++;
            checkBatchComplete();
        } else {
            text.textContent = "Processing checkpoint " + data.current_checkpoint + " of " + data.total_checkpoints;
        }
    }

    function checkBatchComplete() {
        if (completedCount >= totalQueuedCount && totalQueuedCount > 0) {
            showBatchActions();
        }
    }

    function showBatchActions() {
        var existing = document.getElementById("batch-actions");
        if (existing) return;

        var actionsDiv = document.createElement("div");
        actionsDiv.id = "batch-actions";
        actionsDiv.className = "batch-actions";

        // Download All ZIP button
        if (currentBatchId) {
            var zipBtn = document.createElement("a");
            zipBtn.href = "/api/download-all/" + currentBatchId;
            zipBtn.className = "btn btn-zip";
            zipBtn.textContent = "Download All as ZIP";
            zipBtn.setAttribute("aria-label", "Download all remediated files and reports as a single ZIP file");
            actionsDiv.appendChild(zipBtn);
        }

        // Clear & Start New Batch button
        var clearBtn = document.createElement("button");
        clearBtn.className = "btn btn-clear";
        clearBtn.textContent = "Clear & Start New Batch";
        clearBtn.setAttribute("aria-label", "Clear all results and start a new batch upload");
        clearBtn.addEventListener("click", clearForm);
        actionsDiv.appendChild(clearBtn);

        resultsSection.appendChild(actionsDiv);

        // Announce to screen readers
        var announcement = document.createElement("div");
        announcement.setAttribute("role", "status");
        announcement.setAttribute("aria-live", "polite");
        announcement.className = "visually-hidden";
        announcement.textContent = "All files processed. Download All as ZIP or Clear to start a new batch.";
        document.body.appendChild(announcement);
        setTimeout(function () {
            document.body.removeChild(announcement);
        }, 3000);
    }

    function clearForm() {
        // Reset all state
        selectedFiles = [];
        activeJobs = new Map();
        currentBatchId = null;
        completedCount = 0;
        totalQueuedCount = 0;

        // Clear UI sections
        fileList.innerHTML = "";
        progressContainer.innerHTML = "";
        resultsContainer.innerHTML = "";
        progressSection.classList.add("hidden");
        resultsSection.classList.add("hidden");
        hideError();

        // Remove batch actions
        var batchActions = document.getElementById("batch-actions");
        if (batchActions) batchActions.remove();

        // Reset upload button
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Upload & Process";

        // Focus back to upload area
        dropZone.focus();
    }

    function pollJobStatus(jobId) {
        fetch("/api/status/" + jobId)
            .then(function (response) {
                if (!response.ok) throw new Error("Status check failed");
                return response.json();
            })
            .then(function (data) {
                updateProgressItem(jobId, data);

                if (data.status === "completed" || data.status === "failed") {
                    activeJobs.delete(jobId);
                } else {
                    setTimeout(function () {
                        pollJobStatus(jobId);
                    }, POLL_INTERVAL);
                }
            })
            .catch(function () {
                setTimeout(function () {
                    pollJobStatus(jobId);
                }, POLL_INTERVAL * 2);
            });
    }

    // --- Results ---

    function addResultItem(jobId, data) {
        resultsSection.classList.remove("hidden");

        var jobInfo = activeJobs.get(jobId) || { filename: "Unknown" };

        var item = document.createElement("div");
        item.className = "result-item";

        var heading = document.createElement("h3");
        heading.textContent = jobInfo.filename || data.original_filename || "Processed File";

        var linksDiv = document.createElement("div");
        linksDiv.className = "download-links";

        var pdfLink = document.createElement("a");
        pdfLink.href = "/api/download/" + jobId + "/pdf";
        pdfLink.textContent = "Download Remediated PDF";
        pdfLink.setAttribute("aria-label", "Download remediated PDF: " + (jobInfo.filename || "file"));

        var reportLink = document.createElement("a");
        reportLink.href = "/api/download/" + jobId + "/report";
        reportLink.textContent = "Download Compliance Report";
        reportLink.setAttribute("aria-label", "Download compliance report for: " + (jobInfo.filename || "file"));

        linksDiv.appendChild(pdfLink);
        linksDiv.appendChild(reportLink);

        item.appendChild(heading);
        item.appendChild(linksDiv);
        resultsContainer.appendChild(item);
    }

    // --- Error Display ---

    function showError(message) {
        errorDisplay.textContent = message;
        errorDisplay.classList.remove("hidden");
    }

    function hideError() {
        errorDisplay.textContent = "";
        errorDisplay.classList.add("hidden");
    }

    // --- Utilities ---

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }
})();
