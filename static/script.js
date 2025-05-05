// Constants
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
const CHUNK_SIZE = 512 * 1024; // 512KB chunks (reduced from 1MB)
const RETRY_DELAY = 2000; // 2 seconds
const MAX_RETRIES = 3;
const UPLOAD_CHUNK_SIZE = 512 * 1024; // 512KB upload chunks

// DOM Elements
const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const submitButton = document.getElementById('submit-button');
const statusMessage = document.getElementById('status-message');
const progressBarContainer = document.querySelector('.progress-bar-container');
const progressBar = document.querySelector('.progress-bar');
const downloadLink = document.getElementById('download-link');
const statsContainer = document.createElement('div');
statsContainer.id = 'stats-container';
document.querySelector('.container').appendChild(statsContainer);

// Helper Functions
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function updateProgress(percent) {
    progressBar.style.width = `${percent}%`;
    statusMessage.textContent = `Processing: ${percent}%`;
}

function showError(message) {
    statusMessage.textContent = `Error: ${message}`;
    statusMessage.style.color = 'red';
    submitButton.disabled = false;
}

function showSuccess(message) {
    statusMessage.textContent = message;
    statusMessage.style.color = 'green';
}

function showStats(stats) {
    statsContainer.innerHTML = `
        <h3>Server Status</h3>
        <p>Active Conversions: ${stats.active_conversions}/${stats.max_concurrent_conversions}</p>
        <p>Max File Size: ${formatFileSize(stats.max_file_size)}</p>
    `;
}

async function fetchStats() {
    try {
        const response = await fetch('/api/stats');
        if (response.ok) {
            const stats = await response.json();
            showStats(stats);
        }
    } catch (error) {
        console.error('Failed to fetch stats:', error);
    }
}

// File Validation
fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.json')) {
        showError('Please select a JSON file');
        fileInput.value = '';
        return;
    }

    if (file.size > MAX_FILE_SIZE) {
        showError(`File too large. Maximum size is ${formatFileSize(MAX_FILE_SIZE)}`);
        fileInput.value = '';
        return;
    }

    statusMessage.textContent = `Selected file: ${file.name} (${formatFileSize(file.size)})`;
    statusMessage.style.color = 'black';
});

async function splitAndUploadFile(file) {
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const fileId = `${Date.now()}_${file.name}`;
    let processedChunks = 0;

    try {
        // Create chunks directory on server
        const createResponse = await fetch('/api/create-chunks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: fileId })
        });

        if (!createResponse.ok) {
            const error = await createResponse.json();
            throw new Error(`Failed to create chunks directory: ${error.detail || 'Unknown error'}`);
        }

        // Upload chunks
        for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
            const start = chunkIndex * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunk = file.slice(start, end);

            // Create a new File object for the chunk
            const chunkFile = new File([chunk], `chunk_${chunkIndex}`, {
                type: 'application/octet-stream'
            });

            const formData = new FormData();
            formData.append('file', chunkFile);
            formData.append('filename', fileId);
            formData.append('chunk_index', chunkIndex.toString());
            formData.append('total_chunks', totalChunks.toString());

            let retryCount = 0;
            while (retryCount < MAX_RETRIES) {
                try {
                    const response = await fetch('/api/upload-chunk', {
                        method: 'POST',
                        body: formData
                    });

                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(`Failed to upload chunk ${chunkIndex + 1}: ${error.detail || 'Unknown error'}`);
                    }

                    processedChunks++;
                    updateProgress((processedChunks / totalChunks) * 100);
                    break; // Success, exit retry loop
                } catch (chunkError) {
                    retryCount++;
                    if (retryCount === MAX_RETRIES) {
                        throw new Error(`Failed to upload chunk ${chunkIndex + 1} after ${MAX_RETRIES} attempts: ${chunkError.message}`);
                    }
                    console.warn(`Retrying chunk ${chunkIndex + 1} (attempt ${retryCount + 1}/${MAX_RETRIES})`);
                    await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
                }
            }
        }

        // Start conversion
        console.log('Starting conversion for file:', fileId);
        const convertResponse = await fetch('/api/convert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: fileId })
        });

        if (!convertResponse.ok) {
            const error = await convertResponse.json();
            throw new Error(`Conversion failed: ${error.detail || 'Unknown error'}`);
        }

        const blob = await convertResponse.blob();
        const url = window.URL.createObjectURL(blob);
        downloadLink.href = url;
        
        // Extract filename from Content-Disposition header
        const contentDisposition = convertResponse.headers.get('Content-Disposition');
        let filename = 'converted.json';
        if (contentDisposition) {
            const matches = /filename="([^"]+)"/.exec(contentDisposition);
            if (matches && matches[1]) {
                filename = matches[1];
            }
        }
        downloadLink.download = filename;
        downloadLink.style.display = 'block';
        showSuccess('Conversion successful! Click the download link to save your file.');

    } catch (error) {
        console.error('Error during file processing:', error);
        showError(error.message);
    } finally {
        submitButton.disabled = false;
        progressBarContainer.style.display = 'none';
    }
}

// Event Listeners
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];

    if (!file) {
        showError('Please select a file');
        return;
    }

    submitButton.disabled = true;
    progressBarContainer.style.display = 'block';
    progressBar.style.width = '0%';
    downloadLink.style.display = 'none';
    statusMessage.style.color = '';

    try {
        await splitAndUploadFile(file);
    } catch (error) {
        showError(error.message);
    }
});

// Initial stats fetch
fetchStats();
// Update stats every 30 seconds
setInterval(fetchStats, 30000); 