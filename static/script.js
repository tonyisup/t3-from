// Constants
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
const RETRY_DELAY = 2000; // 2 seconds
const MAX_RETRIES = 3;
const UPLOAD_CHUNK_SIZE = 1024 * 1024; // 1MB upload chunks

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

function updateProgress(loaded, total) {
    const percent = (loaded / total) * 100;
    progressBar.style.width = percent + '%';
    statusMessage.textContent = `Uploading: ${formatFileSize(loaded)} of ${formatFileSize(total)} (${Math.round(percent)}%)`;
}

function showError(message, isRetryable = false) {
    statusMessage.textContent = message;
    statusMessage.style.color = 'red';
    submitButton.disabled = false;
    progressBarContainer.style.display = 'none';
    
    if (isRetryable) {
        const retryButton = document.createElement('button');
        retryButton.textContent = 'Retry';
        retryButton.className = 'retry-button';
        retryButton.onclick = () => {
            retryButton.remove();
            uploadForm.dispatchEvent(new Event('submit'));
        };
        statusMessage.appendChild(document.createElement('br'));
        statusMessage.appendChild(retryButton);
    }
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

// Chunked Upload
async function uploadInChunks(file) {
    const totalChunks = Math.ceil(file.size / UPLOAD_CHUNK_SIZE);
    const formData = new FormData();
    formData.append('filename', file.name);
    formData.append('totalChunks', totalChunks.toString());
    
    let uploadedSize = 0;
    
    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
        const start = chunkIndex * UPLOAD_CHUNK_SIZE;
        const end = Math.min(start + UPLOAD_CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);
        
        formData.set('chunk', chunk);
        formData.set('chunkIndex', chunkIndex.toString());
        
        const response = await fetch('/api/upload-chunk', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`Failed to upload chunk ${chunkIndex + 1} of ${totalChunks}`);
        }
        
        uploadedSize += chunk.size;
        updateProgress(uploadedSize, file.size);
    }
    
    // Start conversion after all chunks are uploaded
    const convertResponse = await fetch('/api/convert', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            filename: file.name
        })
    });
    
    if (!convertResponse.ok) {
        const error = await convertResponse.json();
        throw new Error(error.detail || 'Conversion failed');
    }
    
    return convertResponse;
}

async function handleResponse(response) {
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Conversion failed');
        }
        return data;
    } else {
        const text = await response.text();
        if (!response.ok) {
            throw new Error(text || 'Conversion failed');
        }
        return text;
    }
}

// Form Submission
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const file = fileInput.files[0];
    if (!file) {
        showError('Please select a file first');
        return;
    }

    // Reset UI
    submitButton.disabled = true;
    downloadLink.style.display = 'none';
    progressBarContainer.style.display = 'block';
    progressBar.style.width = '0%';
    statusMessage.style.color = 'black';

    let retryCount = 0;
    
    while (retryCount < MAX_RETRIES) {
        try {
            let response;
            
            if (file.size > 10 * 1024 * 1024) { // Use chunked upload for files > 10MB
                response = await uploadInChunks(file);
            } else {
                const formData = new FormData();
                formData.append('file', file);

                response = await fetch('/api/convert', {
                    method: 'POST',
                    body: formData,
                    onUploadProgress: (progressEvent) => {
                        updateProgress(progressEvent.loaded, progressEvent.total);
                    }
                });
            }

            if (!response.ok) {
                // Handle specific error cases
                if (response.status === 429) {
                    // Rate limit or concurrent conversion limit
                    await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
                    retryCount++;
                    continue;
                }
                
                const error = await handleResponse(response);
                throw new Error(error.detail || 'Conversion failed');
            }

            // Get the filename from the Content-Disposition header
            const contentDisposition = response.headers.get('Content-Disposition');
            const filename = contentDisposition
                ? contentDisposition.split('filename=')[1].replace(/"/g, '')
                : 'converted.json';

            // Get processing metrics
            const processingTime = response.headers.get('X-Processing-Time');
            const threadCount = response.headers.get('X-Thread-Count');
            const messageCount = response.headers.get('X-Message-Count');

            // Create download link
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            downloadLink.href = url;
            downloadLink.download = filename;
            downloadLink.style.display = 'block';
            
            showSuccess(`Conversion successful! Processed ${threadCount} threads and ${messageCount} messages in ${processingTime}s. Click the download link to save your file.`);
            
            // Update stats
            await fetchStats();
            break;
        } catch (error) {
            console.error('Error during conversion:', error);
            if (retryCount < MAX_RETRIES - 1) {
                retryCount++;
                await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
                continue;
            }
            showError(error.message || 'An unexpected error occurred', true);
        } finally {
            submitButton.disabled = false;
            progressBarContainer.style.display = 'none';
        }
    }
});

// Initial stats fetch
fetchStats();
// Update stats every 30 seconds
setInterval(fetchStats, 30000); 