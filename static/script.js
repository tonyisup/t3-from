// Constants
const MAX_FILE_SIZE = 4 * 1024 * 1024; // 4MB
const CHUNK_SIZE = 8192; // 8KB chunks

// DOM Elements
const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const submitButton = document.getElementById('submit-button');
const statusMessage = document.getElementById('status-message');
const progressBarContainer = document.querySelector('.progress-bar-container');
const progressBar = document.querySelector('.progress-bar');
const downloadLink = document.getElementById('download-link');

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

function showError(message) {
    statusMessage.textContent = message;
    statusMessage.style.color = 'red';
    submitButton.disabled = false;
    progressBarContainer.style.display = 'none';
}

function showSuccess(message) {
    statusMessage.textContent = message;
    statusMessage.style.color = 'green';
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

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/convert', {
            method: 'POST',
            body: formData,
            onUploadProgress: (progressEvent) => {
                updateProgress(progressEvent.loaded, progressEvent.total);
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Conversion failed');
        }

        // Get the filename from the Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        const filename = contentDisposition
            ? contentDisposition.split('filename=')[1].replace(/"/g, '')
            : 'converted.json';

        // Create download link
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        downloadLink.href = url;
        downloadLink.download = filename;
        downloadLink.style.display = 'block';
        
        showSuccess('Conversion successful! Click the download link to save your file.');
    } catch (error) {
        showError(error.message);
    } finally {
        submitButton.disabled = false;
        progressBarContainer.style.display = 'none';
    }
}); 