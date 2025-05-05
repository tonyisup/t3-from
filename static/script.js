const form = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const statusMessage = document.getElementById('status-message');
const progressBarContainer = document.querySelector('.progress-bar-container');
const progressBar = document.querySelector('.progress-bar');
const downloadLink = document.getElementById('download-link');
const submitButton = document.getElementById('submit-button');

form.addEventListener('submit', async (event) => {
    event.preventDefault();

    const file = fileInput.files[0];
    if (!file) {
        setStatus('Please select a file first.', 'error');
        return;
    }

    if (!file.name.endsWith('.json')) {
        setStatus('Please upload a valid .json file.', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    // Reset UI
    setStatus('Uploading and processing... This might take a while for large files.', 'info');
    showProgress(true);
    setProgress(0);
    downloadLink.style.display = 'none';
    submitButton.disabled = true;

    try {
        // We don't have real progress for the server processing with ijson,
        // so simulate some progress during upload and then wait.
        // A more advanced solution might use websockets.
        setProgress(30); // Simulate upload start

        const response = await fetch('/api/convert', {
            method: 'POST',
            body: formData,
        });

        setProgress(70); // Simulate processing start

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown server error occurred.' }));
            throw new Error(errorData.detail || `HTTP error! Status: ${response.status}`);
        }

        setStatus('Processing complete. Preparing download...', 'success');
        setProgress(100);

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);

        downloadLink.href = url;
        // Extract filename from Content-Disposition header if available, otherwise use default
        const disposition = response.headers.get('content-disposition');
        let filename = 'openai_converted_threads.json';
        if (disposition && disposition.indexOf('attachment') !== -1) {
            const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
            const matches = filenameRegex.exec(disposition);
            if (matches != null && matches[1]) {
                filename = matches[1].replace(/['"]/g, '');
            }
        }
        downloadLink.download = filename;
        downloadLink.style.display = 'inline-block';
        setStatus('Conversion successful! Click the link below to download.', 'success');

    } catch (error) {
        console.error('Error during conversion:', error);
        setStatus(`Error: ${error.message}`, 'error');
        showProgress(false); // Hide progress bar on error
    } finally {
        submitButton.disabled = false;
        // Keep progress bar visible on success until next upload
        if (statusMessage.style.color !== 'green') {
            showProgress(false); 
        }
    }
});

function setStatus(message, type = 'info') {
    statusMessage.textContent = message;
    switch (type) {
        case 'error':
            statusMessage.style.color = 'red';
            break;
        case 'success':
            statusMessage.style.color = 'green';
            break;
        default:
            statusMessage.style.color = '#333';
    }
}

function showProgress(show) {
    progressBarContainer.style.display = show ? 'block' : 'none';
}

function setProgress(percentage) {
    progressBar.style.width = `${percentage}%`;
    // progressBar.textContent = `${percentage}%`; // Optional: show percentage text
} 