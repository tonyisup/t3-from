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

    // Reset UI
    setStatus('Processing file... This might take a while for large files.', 'info');
    showProgress(true);
    setProgress(0);
    downloadLink.style.display = 'none';
    submitButton.disabled = true;

    try {
        // Simulate some progress during processing
        setProgress(30);
        
        // Convert the file
        const convertedData = await convertFile(file);
        
        setProgress(70);

        // Create and trigger download
        const blob = new Blob([JSON.stringify(convertedData, null, 2)], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        
        downloadLink.href = url;
        downloadLink.download = convertedData.metadata.filename;
        downloadLink.style.display = 'inline-block';
        
        setProgress(100);
        setStatus('Conversion successful! Click the link below to download.', 'success');

    } catch (error) {
        console.error('Error during conversion:', error);
        setStatus(`Error: ${error.message}`, 'error');
        showProgress(false);
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
} 